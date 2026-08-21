#!/usr/bin/env python3
"""
Cron Previsao Receita em Risco — roda toda segunda as 8h
Projeta quanto o provedor vai perder nos proximos 3 meses
baseado na inadimplencia atual
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/jactos/cobranca')
os.chdir('/opt/automacoes/jactos/cobranca')
from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)
import requests
from app.core.db import query, query_one

TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHAT  = "2135602169"

def telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        log(f"[TELEGRAM ERRO] {e}")

def main():
    agora = now_br()
    log("=== PREVISAO RECEITA EM RISCO ===")

    # Receita mensal total — baseada em faturas do mês atual
    receita = query_one("""
        SELECT COUNT(DISTINCT f.id_cliente) AS total_contratos,
               SUM(f.valor) AS receita_mensal,
               AVG(f.valor) AS ticket_medio
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id=f.id_contrato AND cc.status='A'
        WHERE MONTH(f.data_vencimento)=MONTH(CURDATE())
          AND YEAR(f.data_vencimento)=YEAR(CURDATE())
    """, ())

    # Inadimplentes atuais
    inad = query_one("""
        SELECT COUNT(DISTINCT f.id_cliente) AS total_inad,
               SUM(f.valor_aberto) AS total_em_aberto
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id_cliente=f.id_cliente AND cc.status='A'
        WHERE f.status='A'
          AND f.data_vencimento < CURDATE()
    """, ())

    # Cancelamentos últimos 3 meses com valor real das faturas
    cancel = query_one("""
        SELECT COUNT(DISTINCT cc.id_cliente) AS total_cancel,
               AVG(DATEDIFF(cc.data_cancelamento, cc.data_ativacao)) AS media_dias,
               SUM(f.valor) AS receita_perdida
        FROM ixcprovedor.cliente_contrato cc
        LEFT JOIN ixcprovedor.fn_areceber f ON f.id_contrato=cc.id
            AND MONTH(f.data_vencimento)=MONTH(cc.data_cancelamento)
            AND YEAR(f.data_vencimento)=YEAR(cc.data_cancelamento)
        WHERE cc.status='I'
          AND cc.data_cancelamento >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
    """, ())

    # Novos clientes últimos 3 meses com receita real da 1ª fatura
    novos = query_one("""
        SELECT COUNT(DISTINCT cc.id_cliente) AS total_novos,
               SUM(f.valor) AS receita_nova
        FROM ixcprovedor.cliente_contrato cc
        LEFT JOIN ixcprovedor.fn_areceber f ON f.id_cliente=cc.id_cliente
            AND f.status IN ('A','R')
            AND f.data_vencimento >= cc.data_ativacao
            AND f.data_vencimento <= DATE_ADD(cc.data_ativacao, INTERVAL 1 MONTH)
        WHERE cc.status IN ('A','I')
          AND cc.data_ativacao >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
    """, ())

    receita_mensal  = float(receita["receita_mensal"] or 0)
    ticket_medio    = float(receita["ticket_medio"] or 0)
    total_contratos = int(receita["total_contratos"] or 0)
    total_inad      = int(inad["total_inad"] or 0)
    total_aberto    = float(inad["total_em_aberto"] or 0)
    taxa_inad       = round(total_inad / total_contratos * 100, 1) if total_contratos else 0
    cancel_3m       = int(cancel["total_cancel"] or 0)
    receita_perdida = float(cancel["receita_perdida"] or 0)
    media_dias      = float(cancel["media_dias"] or 0)
    novos_3m        = int(novos["total_novos"] or 0)
    receita_nova    = float(novos["receita_nova"] or 0)

    # Projecoes
    cancel_mes          = cancel_3m / 3
    perda_mensal        = receita_perdida / 3
    ganho_mensal        = receita_nova / 3
    saldo_mensal        = ganho_mensal - perda_mensal
    projecao_1m         = receita_mensal + saldo_mensal
    projecao_3m         = receita_mensal + (saldo_mensal * 3)
    risco_inad_cobranca = total_aberto * 0.4  # 40% dos inadimplentes nao paga

    linhas = [
        "💰 <b>PREVISÃO DE RECEITA EM RISCO</b>",
        f"📅 {agora.strftime(' %d/%m/%Y')}",
        "",
        "<b>📊 SITUAÇÃO ATUAL:</b>",
        f"  • Contratos ativos: {total_contratos}",
        f"  • Receita mensal: R$ {receita_mensal:.2f} (ticket médio R$ {ticket_medio:.2f})",
        f"  • Inadimplentes: {total_inad} ({taxa_inad}%) | R$ {total_aberto:.2f} em aberto",
        f"  • Risco real (40% não paga): R$ {risco_inad_cobranca:.2f}",
        "",
        "<b>📉 ÚLTIMOS 3 MESES:</b>",
        f"  • Cancelamentos: {cancel_3m} ({cancel_mes:.0f}/mês) | R$ {receita_perdida:.2f} perdidos",
        f"  • Tempo médio na base: {media_dias:.0f} dias",
        f"  • Novos clientes: {novos_3m} ({ganho_mensal:.0f}/mês) | R$ {receita_nova:.2f} ganhos",
        f"  • Saldo mensal: {'✅' if saldo_mensal >= 0 else '🔴'} R$ {saldo_mensal:.2f}",
        "",
        "<b>🔮 PROJEÇÃO:</b>",
        f"  • Próximo mês: R$ {projecao_1m:.2f} {'📈' if projecao_1m > receita_mensal else '📉'}",
        f"  • Próximos 3 meses: R$ {projecao_3m:.2f} {'📈' if projecao_3m > receita_mensal else '📉'}",
        f"  • Perda projetada 3 meses: R$ {abs(receita_mensal - projecao_3m):.2f}",
        "",
        f"<i>IaTechHub · {agora.strftime(' %d/%m/%Y %H:%M')}</i>",
    ]
    telegram("\n".join(linhas))
    log("Relatorio enviado")

if __name__ == "__main__":
    main()
