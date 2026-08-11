#!/usr/bin/env python3
"""Detecta clientes que pagaram parcela errada nos últimos 3 meses — por contrato"""
import sys, os
sys.path.insert(0, '/opt/automacoes/cliquedf/cobranca')
os.chdir('/opt/automacoes/cliquedf/cobranca')
from datetime import datetime, timezone, timedelta
import requests
from app.core.db import query
from app.core.db_local import local_query, local_execute

TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)

TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHAT  = "-4989557189"

def telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        log(f"Telegram erro: {e}")

def detectar_parcelas_erradas():
    log("=== DETECÇÃO PARCELAS FORA DE ORDEM (últimos 3 meses) ===")
    hoje = now_br().strftime('%Y-%m-%d')
    data_3m = (now_br() - timedelta(days=90)).strftime('%Y-%m-%d')

    resultado = query("""
        SELECT 
            f.id_contrato,
            f.id_cliente,
            c.razao,
            COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone,
            MAX(CASE WHEN f.status='R' THEN f.data_vencimento END) AS max_paga,
            MIN(CASE WHEN f.status='A' AND f.data_vencimento < CURDATE() THEN f.data_vencimento END) AS min_aberta,
            GROUP_CONCAT(CASE WHEN f.status='R' THEN f.data_vencimento END ORDER BY f.data_vencimento) AS datas_pagas,
            GROUP_CONCAT(CASE WHEN f.status='A' AND f.data_vencimento < CURDATE() THEN f.data_vencimento END ORDER BY f.data_vencimento) AS datas_abertas
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente c ON c.id=f.id_cliente
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id=f.id_contrato AND cc.status='A'
        WHERE f.data_vencimento >= %s
          AND f.id_contrato IS NOT NULL
        GROUP BY f.id_contrato, f.id_cliente, c.razao, c.whatsapp, c.telefone_celular, c.fone
        HAVING max_paga > min_aberta AND min_aberta IS NOT NULL
    """, (data_3m,))

    log(f"Contratos com parcela fora de ordem: {len(resultado)}")

    # Filtra alertados hoje
    ja_alertados = {r["cliente_id"] for r in local_query("""
        SELECT cliente_id FROM cob_alertas_inadimplente
        WHERE tipo='PARCELA_ERRADA' AND date(alertado_em)=?
    """, (hoje,))}

    alertas = [r for r in resultado if r["id_cliente"] not in ja_alertados]
    log(f"Novos alertas: {len(alertas)}")

    if not alertas:
        log("Nenhum novo alerta")
        return 0

    def fmt_datas(datas_str):
        if not datas_str: return "—"
        datas = str(datas_str).split(",")
        return ", ".join(
            datetime.strptime(d.strip()[:10], "%Y-%m-%d").strftime("%m/%Y")
            for d in datas if d.strip()
        )

    linhas = [f"⚠️ <b>PARCELAS PAGAS FORA DE ORDEM</b>", f"📅 {now_br().strftime('%d/%m/%Y %H:%M')}", ""]
    for a in alertas[:10]:
        pagas   = fmt_datas(a["datas_pagas"])
        abertas = fmt_datas(a["datas_abertas"])
        linhas.append(f"👤 <b>{a['razao']}</b> {a['telefone'] or ''}")
        linhas.append(f"   ✅ Pagou: {pagas} | ❌ Em aberto: {abertas}")
        linhas.append("")
        local_execute("""
            INSERT INTO cob_alertas_inadimplente (cliente_id, alertado_em, tipo)
            VALUES (?, datetime('now','-3 hours'), 'PARCELA_ERRADA')
        """, (a["id_cliente"],))

    if len(alertas) > 10:
        linhas.append(f"... e mais {len(alertas)-10} clientes")
    linhas.append("💡 Verificar e cobrar as parcelas em aberto!")
    telegram("\n".join(linhas))
    log(f"Alerta enviado: {len(alertas)} clientes")
    return len(alertas)

if __name__ == "__main__":
    detectar_parcelas_erradas()
