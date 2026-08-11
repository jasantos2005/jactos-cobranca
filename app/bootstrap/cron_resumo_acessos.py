#!/usr/bin/env python3
"""Cron Resumo Acessos — todo dia às 18h — envia resumo no Telegram privado
   Duração somada considera apenas expediente: 08:00-12:00 e 14:00-18:00
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/cliquedf/cobranca')
os.chdir('/opt/automacoes/cliquedf/cobranca')
from datetime import datetime, timezone, timedelta, time as dtime
import requests, sqlite3

TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)

TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHATS = ["2135602169", "2135602169"]
DB_PATH = "/opt/automacoes/cliquedf/cobranca/cobranca_local.db"

# Janelas de expediente consideradas no cálculo
WORK_WINDOWS = [(dtime(8, 0), dtime(12, 0)), (dtime(14, 0), dtime(18, 0))]


def telegram(msg):
    for chat in TELEGRAM_CHATS:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                data={"chat_id": chat, "text": msg, "parse_mode": "HTML"}, timeout=10)
        except Exception as e:
            print(f"Telegram erro ({chat}): {e}")


def parse_dt(s):
    """Converte string do SQLite (naive, já em horário BR) para datetime naive."""
    if not s:
        return None
    s = str(s)
    fmt = "%Y-%m-%d %H:%M:%S" if len(s) > 16 else "%Y-%m-%d %H:%M"
    try:
        return datetime.strptime(s[:19], fmt)
    except ValueError:
        return None


def overlap_minutes_in_window(start, end, day_date, window_start_t, window_end_t):
    win_start = datetime.combine(day_date, window_start_t)
    win_end = datetime.combine(day_date, window_end_t)
    lo = max(start, win_start)
    hi = min(end, win_end)
    delta = (hi - lo).total_seconds() / 60
    return delta if delta > 0 else 0


def business_minutes(login_em, logout_em):
    """Soma os minutos da sessão que caem dentro de 08-12 e 14-18,
    cobrindo o caso de a sessão atravessar mais de um dia."""
    start = parse_dt(login_em)
    end = parse_dt(logout_em) or now_br().replace(tzinfo=None)
    if not start or end <= start:
        return 0
    total = 0
    day = start.date()
    while day <= end.date():
        for w_start, w_end in WORK_WINDOWS:
            total += overlap_minutes_in_window(start, end, day, w_start, w_end)
        day += timedelta(days=1)
    return total


def main():
    hoje = now_br().strftime('%Y-%m-%d')
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Sessões cruas do dia (cálculo de duração feito em Python, respeitando expediente)
    cur.execute("""
        SELECT usuario_nome, login_em, logout_em, motivo_logout
        FROM cob_sessoes
        WHERE login_em LIKE ?
        ORDER BY usuario_nome, login_em
    """, (f"{hoje}%",))
    rows = cur.fetchall()

    # Interações do dia
    cur.execute("""
        SELECT u.nome, COUNT(*) AS total_interacoes
        FROM cob_interacoes i
        INNER JOIN cob_usuarios u ON u.id = i.usuario_id
        WHERE i.criado_em LIKE ?
        GROUP BY u.nome
        ORDER BY total_interacoes DESC
    """, (f"{hoje}%",))
    interacoes = {r["nome"]: r["total_interacoes"] for r in cur.fetchall()}
    conn.close()

    if not rows:
        telegram(f"📊 <b>Resumo do dia {now_br().strftime('%d/%m/%Y')}</b>\n\nNenhum acesso registrado hoje.")
        return

    # Agrega por usuário
    usuarios = {}
    for r in rows:
        nome = r["usuario_nome"]
        u = usuarios.setdefault(nome, {
            "sessoes": 0, "total_min": 0, "primeiro_login": None,
            "ultimo_acesso": None, "inatividades": 0
        })
        u["sessoes"] += 1
        u["total_min"] += business_minutes(r["login_em"], r["logout_em"])
        if not u["primeiro_login"] or r["login_em"] < u["primeiro_login"]:
            u["primeiro_login"] = r["login_em"]
        ultimo = r["logout_em"] or now_br().strftime("%Y-%m-%d %H:%M:%S")
        if not u["ultimo_acesso"] or ultimo > u["ultimo_acesso"]:
            u["ultimo_acesso"] = ultimo
        if r["motivo_logout"] == "Inatividade":
            u["inatividades"] += 1

    sessoes = sorted(usuarios.items(), key=lambda kv: kv[1]["total_min"], reverse=True)

    linhas = [
        f"📊 <b>RESUMO DE ACESSOS — {now_br().strftime('%d/%m/%Y')}</b>",
        f"🕐 Gerado às {now_br().strftime('%H:%M')}",
        f"🗓️ Horário considerado: 08h-12h e 14h-18h",
        ""
    ]
    total_min_geral = 0
    for nome, s in sessoes:
        h, m = divmod(int(round(s["total_min"])), 60)
        dur = f"{h}h{m:02d}min" if h else f"{m}min"
        primeiro = str(s["primeiro_login"])[11:16] if s["primeiro_login"] else "—"
        ultimo   = str(s["ultimo_acesso"])[11:16] if s["ultimo_acesso"] else "—"
        inat     = f" | ⏰ {s['inatividades']}x inatividade" if s["inatividades"] else ""
        inter    = interacoes.get(nome, 0)
        inter_txt = f" | 📋 {inter} interações" if inter else ""
        linhas.append(f"👤 <b>{nome}</b>")
        linhas.append(f"   ⏱ {dur} | 🕐 {primeiro}–{ultimo}{inat}{inter_txt}")
        linhas.append("")
        total_min_geral += s["total_min"]

    h, m = divmod(int(round(total_min_geral)), 60)
    total_inter = sum(interacoes.values())
    linhas.append(f"📈 <b>Total:</b> {len(sessoes)} usuários | {h}h{m:02d}min | {total_inter} interações")
    linhas.append(f"\n<i>IaTechHub · HubCobrança</i>")
    telegram("\n".join(linhas))
    print(f"Resumo enviado — {len(sessoes)} usuários — {h}h{m:02d}min (expediente)")


if __name__ == "__main__":
    main()
