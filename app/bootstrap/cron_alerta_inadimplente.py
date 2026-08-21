#!/usr/bin/env python3
import sys, os
sys.path.insert(0, '/opt/automacoes/jactos/cobranca')
os.chdir('/opt/automacoes/jactos/cobranca')
from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)
import sqlite3, requests
from app.core.db import query
from app.core.db_local import local_query, local_execute

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
    log("=== ALERTA INADIMPLENTE ===")
    novos_inadimplentes = query("""
        SELECT c.id AS id_cliente, c.razao,
               cc.data_ativacao,
               DATEDIFF(CURDATE(), cc.data_ativacao) AS dias_ativado,
               MAX(DATEDIFF(CURDATE(), f.data_vencimento)) AS maior_atraso,
               SUM(f.valor_aberto) AS total_aberto,
               MIN(f.nparcela) AS menor_parcela
        FROM ixcprovedor.cliente c
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id_cliente=c.id AND cc.status='A'
        INNER JOIN ixcprovedor.fn_areceber f ON f.id_cliente=c.id
            AND f.status='A' AND f.data_vencimento < CURDATE()
        WHERE DATEDIFF(CURDATE(), cc.data_ativacao) <= 90
          AND cc.data_ativacao IS NOT NULL
        GROUP BY c.id, c.razao, cc.data_ativacao
        HAVING maior_atraso >= 1
    """, ())
    if not novos_inadimplentes:
        log("Nenhum novo inadimplente recente")
        return
    ids_alertados = set()
    try:
        rows = local_query("SELECT cliente_id FROM cob_alertas_inadimplente", ())
        ids_alertados = {r["cliente_id"] for r in rows}
    except:
        local_execute("""CREATE TABLE IF NOT EXISTS cob_alertas_inadimplente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            alertado_em TEXT NOT NULL)""", ())
    novos = [r for r in novos_inadimplentes if r["id_cliente"] not in ids_alertados]
    log(f"Novos inadimplentes recentes: {len(novos)}")
    if not novos:
        return
    ids_clientes = tuple(r["id_cliente"] for r in novos)
    ph = ",".join("?" * len(ids_clientes))
    vendedores_map = {}
    rows_com = get_comercial(f"SELECT ixc_cliente_id, vendedor_nome FROM hc_contratos_cache WHERE ixc_cliente_id IN ({ph})", ids_clientes)
    for r in rows_com:
        vendedores_map[r["ixc_cliente_id"]] = r["vendedor_nome"]
    # Registra todos como alertados
    for r in novos:
        local_execute("INSERT INTO cob_alertas_inadimplente (cliente_id, alertado_em) VALUES (?,?)",
            (r["id_cliente"], now_br().strftime('%Y-%m-%d %H:%M:%S')))

    # Envia resumo geral
    total_valor = sum(float(r["total_aberto"]) for r in novos)
    header = [
        "🚨 <b>NOVOS INADIMPLENTES — Clientes Recentes</b>",
        f"📅 {now_br().strftime('%d/%m/%Y %H:%M')} | {len(novos)} clientes | R$ {total_valor:.2f} em risco",
        "",
    ]
    # Agrupa por vendedor
    por_vendedor = {}
    for r in novos:
        v = vendedores_map.get(r["id_cliente"], "— IXC direto")
        if v not in por_vendedor:
            por_vendedor[v] = []
        por_vendedor[v].append(r)

    for v, clientes in sorted(por_vendedor.items(), key=lambda x: -len(x[1])):
        total_v = sum(float(c["total_aberto"]) for c in clientes)
        header.append(f"👤 <b>{v}</b> — {len(clientes)} cliente(s) | R$ {total_v:.2f}")
        for c in clientes[:5]:
            parcela = c["menor_parcela"] or "?"
            header.append(f"  • {c['razao']} | {parcela}ª parcela | {c['dias_ativado']}d ativado | {c['maior_atraso']}d atraso")
        if len(clientes) > 5:
            header.append(f"  ... e mais {len(clientes)-5} clientes")
        header.append("")

    header.append(f"<i>IaTechHub · {now_br().strftime('%d/%m/%Y %H:%M')}</i>")

    # Divide em lotes de 4000 chars
    msg = "\n".join(header)
    while msg:
        telegram(msg[:4000])
        msg = msg[4000:]
    log(f"Alerta enviado: {len(novos)} clientes")

if __name__ == "__main__":
    main()
