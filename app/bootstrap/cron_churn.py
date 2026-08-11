#!/usr/bin/env python3
"""
Cron Churn Mensal — roda todo dia 1 do mes as 9h
Relatorio de clientes cancelados: tempo na base, vendedor, receita perdida
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/cliquedf/cobranca')
os.chdir('/opt/automacoes/cliquedf/cobranca')
from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)
import sqlite3, requests
from app.core.db import query

TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHAT  = "-4989557189"
COMERCIAL_DB   = "/opt/automacoes/cliquedf/comercial/hub_comercial.db"

def telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        log(f"[TELEGRAM ERRO] {e}")

def get_comercial(sql, params=()):
    conn = sqlite3.connect(COMERCIAL_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def main():
    agora   = now_br()
    mes_ant = (agora.replace(day=1) - timedelta(days=1))
    mes_str = mes_ant.strftime("%Y-%m")
    mes_ini = mes_str + "-01"
    mes_fim = agora.replace(day=1).strftime("%Y-%m-%d")
    log(f"=== CHURN {mes_str} ===")

    cancelados = query("""
        SELECT c.id, c.razao, cc.data_ativacao,
               cc.data_cancelamento,
               DATEDIFF(cc.data_cancelamento, cc.data_ativacao) AS dias_na_base,
               cc.descricao_aux_plano_venda AS plano_nome,
               cc.valor_unitario AS plano_valor
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.cliente c ON c.id=cc.id_cliente
        WHERE cc.status='I'
          AND cc.data_cancelamento >= %s
          AND cc.data_cancelamento < %s
        ORDER BY cc.data_cancelamento DESC
    """, (mes_ini, mes_fim))

    if not cancelados:
        log("Nenhum cancelamento no periodo")
        return

    ids = tuple(c["id"] for c in cancelados)
    ph  = ",".join("?" * len(ids))
    vendedores_map = {}
    rows_com = get_comercial(f"SELECT ixc_cliente_id, vendedor_nome FROM hc_contratos_cache WHERE ixc_cliente_id IN ({ph})", ids)
    for r in rows_com:
        vendedores_map[r["ixc_cliente_id"]] = r["vendedor_nome"]

    total_receita_perdida = sum(float(c["plano_valor"] or 0) for c in cancelados)
    menos30  = [c for c in cancelados if c["dias_na_base"] is not None and int(c["dias_na_base"]) < 30]
    menos90  = [c for c in cancelados if c["dias_na_base"] is not None and 30 <= int(c["dias_na_base"]) < 90]
    mais90   = [c for c in cancelados if c["dias_na_base"] is not None and int(c["dias_na_base"]) >= 90]

    por_vendedor = {}
    for c in cancelados:
        v = vendedores_map.get(c["id"], "— IXC direto")
        if v not in por_vendedor:
            por_vendedor[v] = {"total": 0, "receita": 0.0, "menos30": 0}
        por_vendedor[v]["total"]   += 1
        por_vendedor[v]["receita"] += float(c["plano_valor"] or 0)
        if c["dias_na_base"] is not None and int(c["dias_na_base"]) < 30:
            por_vendedor[v]["menos30"] += 1

    linhas = [
        f"📉 <b>RELATÓRIO DE CHURN — {mes_ant.strftime('%B/%Y').upper()}</b>",
        f"Total cancelados: <b>{len(cancelados)}</b> | Receita perdida: <b>R$ {total_receita_perdida:.2f}/mês</b>",
        "",
        f"⏱ <b>Tempo na base:</b>",
        f"  • Menos de 30 dias: {len(menos30)} ({round(len(menos30)/len(cancelados)*100)}%)",
        f"  • 30 a 90 dias: {len(menos90)} ({round(len(menos90)/len(cancelados)*100)}%)",
        f"  • Mais de 90 dias: {len(mais90)} ({round(len(mais90)/len(cancelados)*100)}%)",
        "",
        f"👤 <b>Por vendedor:</b>",
    ]
    for v, d in sorted(por_vendedor.items(), key=lambda x: -x[1]["total"]):
        alerta = " ⚠️" if d["menos30"] > 0 else ""
        linhas.append(f"  • <b>{v}</b>: {d['total']} cancelados | R$ {d['receita']:.2f} | {d['menos30']} saíram em <30d{alerta}")

    linhas += ["", f"<i>IaTechHub · {agora.strftime('%d/%m/%Y %H:%M')}</i>"]

    msg = "\n".join(linhas)
    while msg:
        telegram(msg[:4000])
        msg = msg[4000:]
    log(f"Relatorio enviado: {len(cancelados)} cancelamentos")

if __name__ == "__main__":
    main()
