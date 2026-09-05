#!/usr/bin/env python3
"""
Cron Churn Mensal — roda todo dia 1 do mes as 9h
Relatorio de clientes cancelados: tempo na base, vendedor, receita perdida
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/jactos/cobranca')
os.chdir('/opt/automacoes/jactos/cobranca')
from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)
import requests
from app.core.db import query
from app.core.telegram import TELEGRAM_CHAT, telegram_url




def telegram(msg):
    try:
        requests.post(telegram_url(),
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        log(f"[TELEGRAM ERRO] {e}")

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

    # Dados comerciais do ClickDF removidos.

    total_receita_perdida = sum(float(c["plano_valor"] or 0) for c in cancelados)
    menos30  = [c for c in cancelados if c["dias_na_base"] is not None and int(c["dias_na_base"]) < 30]
    menos90  = [c for c in cancelados if c["dias_na_base"] is not None and 30 <= int(c["dias_na_base"]) < 90]
    mais90   = [c for c in cancelados if c["dias_na_base"] is not None and int(c["dias_na_base"]) >= 90]

    # Agrupamento por vendedor removido: vendedor comercial era dado do ClickDF.

    linhas = [
        f"📉 <b>RELATÓRIO DE CHURN — {mes_ant.strftime('%B/%Y').upper()}</b>",
        f"Total cancelados: <b>{len(cancelados)}</b> | Receita perdida: <b>R$ {total_receita_perdida:.2f}/mês</b>",
        "",
        f"⏱ <b>Tempo na base:</b>",
        f"  • Menos de 30 dias: {len(menos30)} ({round(len(menos30)/len(cancelados)*100)}%)",
        f"  • 30 a 90 dias: {len(menos90)} ({round(len(menos90)/len(cancelados)*100)}%)",
        f"  • Mais de 90 dias: {len(mais90)} ({round(len(mais90)/len(cancelados)*100)}%)",
        "",
    ]
    linhas += ["", f"<i>IaTechHub · {agora.strftime('%d/%m/%Y %H:%M')}</i>"]

    msg = "\n".join(linhas)
    while msg:
        telegram(msg[:4000])
        msg = msg[4000:]
    log(f"Relatorio enviado: {len(cancelados)} cancelamentos")

if __name__ == "__main__":
    main()
