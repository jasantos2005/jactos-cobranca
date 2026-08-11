#!/usr/bin/env python3
"""Cron Retenção — toda segunda 8h — top 10 em risco no Telegram privado"""
import sys, os
sys.path.insert(0, '/opt/automacoes/cliquedf/cobranca')
os.chdir('/opt/automacoes/cliquedf/cobranca')
from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)
import requests
from app.dashboards.cobranca.service_retencao import get_retencao, get_kpis_retencao

TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHATS = ["2135602169", "2135602169"]

def telegram(msg):
    for chat in TELEGRAM_CHATS:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                data={"chat_id": chat, "text": msg, "parse_mode": "HTML"}, timeout=10)
        except Exception as e:
            log(f"[TELEGRAM ERRO] {e}")

def main():
    log("=== RELATÓRIO RETENÇÃO ===")
    rows, total = get_retencao(pagina=1, por_pagina=15, score_min=35)
    kpis = get_kpis_retencao()

    linhas = [
        "🛡️ <b>RELATÓRIO DE RETENÇÃO</b>",
        f"📅 {now_br().strftime('%d/%m/%Y')} | {kpis['total']} clientes monitorados",
        f"🔴 Críticos: {kpis['criticos']} | 🟡 Atenção: {kpis['atencao']} | 📱 Com OPA: {kpis['com_opa']}",
        f"💸 Valor em risco: R$ {kpis['valor']:.2f}",
        "",
        "<b>🔝 Top clientes em risco:</b>",
    ]
    for r in rows[:10]:
        nivel = "🔴" if r["nivel"]=="critico" else "🟡"
        opa_info = ""
        if r["opa_fin"] > 0: opa_info += f" 💰{r['opa_fin']}x"
        if r["opa_sup"] > 0: opa_info += f" 🔧{r['opa_sup']}x"
        linhas.append(f"  {nivel} <b>{r['razao']}</b> — score {r['score']} | {r['dias_atraso']}d atraso | {r['total_pagas']} parcelas{opa_info}")

    linhas.append(f"\n<i>IaTechHub · {now_br().strftime('%d/%m/%Y %H:%M')}</i>")
    telegram("\n".join(linhas))
    log(f"Relatório enviado — {len(rows)} clientes")

if __name__ == "__main__":
    main()
