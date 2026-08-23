#!/usr/bin/env python3
"""
Cron Alerta Fatura Não Liberada — roda diariamente às 7h
Detecta faturas com liberado=N em aberto e vencidas (possível boleto duplicado/substituído)
e alerta no grupo de cobrança via Telegram.
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/jactos/cobranca')
os.chdir('/opt/automacoes/jactos/cobranca')
from datetime import datetime, timezone, timedelta
import requests
from app.core.db import query

TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)

TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHAT  = "-4989557189"  # Grupo Laura

def telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        log(f"Telegram erro: {e}")

def auditar():
    log("=== AUDITORIA FATURAS NÃO LIBERADAS ===")

    rows = query("""
        SELECT f.id AS fn_id, f.data_vencimento, f.valor_aberto,
               f.documento, c.id AS id_cliente, c.razao,
               DATEDIFF(CURDATE(), f.data_vencimento) AS dias,
               -- Verifica se existe outra fatura paga no mesmo período
               (SELECT COUNT(*) FROM ixcprovedor.fn_areceber f2
                WHERE f2.id_cliente=f.id_cliente
                  AND f2.id_contrato=f.id_contrato
                  AND f2.status IN ('R','C')
                  AND f2.data_vencimento BETWEEN 
                      DATE_SUB(f.data_vencimento, INTERVAL 10 DAY) AND
                      DATE_ADD(f.data_vencimento, INTERVAL 10 DAY)
                  AND f2.id != f.id
               ) AS tem_paga_periodo
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente c ON c.id=f.id_cliente
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id=f.id_contrato AND cc.status='A'
        WHERE f.status='A'
          AND f.liberado='N'
          AND f.data_vencimento < CURDATE()
          AND c.ativo='S'
        ORDER BY dias DESC
    """, ())

    log(f"Faturas não liberadas encontradas: {len(rows)}")

    if not rows:
        log("Nenhuma fatura não liberada — tudo OK!")
        return

    # Separa as que têm fatura paga no mesmo período (duplicadas)
    duplicadas = [r for r in rows if r['tem_paga_periodo'] > 0]
    sem_par    = [r for r in rows if r['tem_paga_periodo'] == 0]

    msg = f"⚠️ <b>AUDITORIA — Faturas Não Liberadas</b>\n"
    msg += f"📅 {now_br().strftime('%d/%m/%Y %H:%M')}\n\n"

    if duplicadas:
        msg += f"🔴 <b>{len(duplicadas)} fatura(s) com possível boleto duplicado/substituído:</b>\n"
        for r in duplicadas[:10]:
            msg += (f"  • {r['razao'][:30]}\n"
                    f"    Fat#{r['fn_id']} | venc:{str(r['data_vencimento'])[:10]} | "
                    f"R$ {float(r['valor_aberto'] or 0):.2f} | {r['dias']}d\n")
        if len(duplicadas) > 10:
            msg += f"  ... e mais {len(duplicadas)-10} faturas\n"

    if sem_par:
        msg += f"\n🟡 <b>{len(sem_par)} fatura(s) não liberada(s) sem par pago:</b>\n"
        for r in sem_par[:5]:
            msg += (f"  • {r['razao'][:30]}\n"
                    f"    Fat#{r['fn_id']} | venc:{str(r['data_vencimento'])[:10]} | "
                    f"R$ {float(r['valor_aberto'] or 0):.2f} | {r['dias']}d\n")

    msg += f"\n⚙️ Verificar e regularizar no IXC.\n<i>HubCobrança Jactos</i>"

    telegram(msg)
    log(f"Alerta enviado — {len(duplicadas)} duplicadas, {len(sem_par)} sem par")

if __name__ == "__main__":
    auditar()
