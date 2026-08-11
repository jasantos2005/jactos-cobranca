#!/usr/bin/env python3
"""
Alerta Telegram: clientes REPROVADOS no Serasa mas ATIVADOS
excepcionalmente (liberação de supervisor/admin).

- Só envia alerta para quem está ATUALMENTE INADIMPLENTE.
- Clientes "ok" ou "cancelado" não geram alerta (e não ficam marcados
  como alertados, então se depois ficarem inadimplentes, entram no
  próximo ciclo normalmente).
- Uma vez alertado (inadimplente), nunca mais reenviado — controle via
  tabela local cob_alertas_serasa_aprovado.
- Grupo: GESTÃO | COMERCIAL
"""
import sys, os, time
sys.path.insert(0, '/opt/automacoes/cliquedf/cobranca')
os.chdir('/opt/automacoes/cliquedf/cobranca')

from datetime import datetime, timezone, timedelta
import requests

from app.core.db_local import local_query, local_execute
from app.dashboards.cobranca.service_reprovados import get_reprovados_ativados

TZ_BR = timezone(timedelta(hours=-3))
def now_br():
    return datetime.now(TZ_BR)

def log(msg):
    print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)

TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHAT  = "-5142280642"  # GESTÃO | COMERCIAL

STATUS_INFO = {
    "inadimplente": ("🔴", "Inadimplente"),
    "ok":           ("✅", "Pagando em dia"),
    "cancelado":    ("❌", "Cancelado"),
}

def telegram(msg):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
        if r.status_code != 200:
            log(f"[TELEGRAM ERRO] status={r.status_code} body={r.text[:300]}")
        return r.status_code == 200
    except Exception as e:
        log(f"[TELEGRAM ERRO] {e}")
        return False

def garantir_tabela():
    local_execute("""
        CREATE TABLE IF NOT EXISTS cob_alertas_serasa_aprovado (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            precadastro_id INTEGER NOT NULL UNIQUE,
            alertado_em TEXT NOT NULL
        )
    """, ())

def montar_mensagem(r):
    emoji, label = STATUS_INFO.get(r["status"], ("⚪", r["status"]))
    liberado_por = r.get("liberado_por") or "não identificado"
    serasa = r.get("serasa_detalhes") or "sem detalhes"
    criado_em = r.get("criado_em") or "—"

    linhas = [
        "⚠️ <b>REPROVADO NO SERASA — APROVADO EXCEPCIONALMENTE</b>",
        f"👤 <b>{r['razao']}</b>",
        f"📍 {r.get('cidade') or '—'} | Vendedor: {r.get('vendedor') or '—'}",
        f"🔴 Serasa: {serasa}",
        f"✅ {liberado_por}",
        f"📅 Ativado em: {criado_em}",
        f"📌 Situação atual: {emoji} {label}",
    ]
    if r["status"] == "inadimplente":
        linhas.append(f"💰 R$ {r['total_aberto']:.2f} em aberto — {r['maior_atraso']}d de parcela vencida")
    linhas.append(f"<i>HubCobrança · {now_br().strftime('%d/%m/%Y %H:%M')}</i>")
    return "\n".join(linhas)

def main():
    log("=== ALERTA SERASA APROVADO EXCEPCIONALMENTE (somente inadimplentes) ===")
    garantir_tabela()

    rows = get_reprovados_ativados(data_ini="2020-01-01")
    if not rows:
        log("Nenhum registro encontrado")
        return

    ja_alertados = {r["precadastro_id"] for r in local_query(
        "SELECT precadastro_id FROM cob_alertas_serasa_aprovado", ()
    )}

    # Só considera quem ainda não foi alertado
    pendentes = [r for r in rows if r["id"] not in ja_alertados]

    # E, dentre esses, só quem está INADIMPLENTE agora.
    # Quem está "ok"/"cancelado" fica de fora e NÃO é marcado como
    # alertado, para ser reavaliado em execuções futuras caso mude
    # de situação.
    inadimplentes = [r for r in pendentes if r["status"] == "inadimplente"]

    log(
        f"Total na base: {len(rows)} | já alertados: {len(ja_alertados)} | "
        f"pendentes: {len(pendentes)} | inadimplentes p/ envio: {len(inadimplentes)}"
    )

    if not inadimplentes:
        return

    enviados = 0
    for r in inadimplentes:
        msg = montar_mensagem(r)
        ok = telegram(msg)
        if ok:
            local_execute(
                "INSERT OR IGNORE INTO cob_alertas_serasa_aprovado (precadastro_id, alertado_em) VALUES (?,?)",
                (r["id"], now_br().strftime('%Y-%m-%d %H:%M:%S')),
            )
            enviados += 1
        time.sleep(1)  # evita rate limit do Telegram em envios em lote

    log(f"Alertas enviados: {enviados}/{len(inadimplentes)}")

if __name__ == "__main__":
    main()
