#!/usr/bin/env python3
"""
Cron Telegram — relatórios horários, ranking e resumo semanal
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/cliquedf/cobranca')
os.chdir('/opt/automacoes/cliquedf/cobranca')

from datetime import datetime, timezone, timedelta, date
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)

from app.core.db_local import local_query, local_query_one
from app.core.db import query_one
import requests

TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHAT  = "-4989557189"
META_DIA       = 150
META_MEIO_DIA  = 75

def enviar(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=10)

def fmt_valor(v):
    return f"R$ {float(v):,.2f}".replace(",","X").replace(".",",").replace("X",".")

def get_cobrancas_dia(dia: str):
    return local_query("""
        SELECT u.nome,
               COUNT(i.id) AS total,
               SUM(CASE WHEN i.acao='Promessa de pagamento' THEN 1 ELSE 0 END) AS promessas,
               SUM(CASE WHEN i.pago=1 THEN 1 ELSE 0 END) AS pagos
        FROM cob_interacoes i
        LEFT JOIN cob_usuarios u ON u.id = i.usuario_id
        WHERE date(i.criado_em) = ? AND u.nome IS NOT NULL
        GROUP BY i.usuario_id, u.nome
        ORDER BY total DESC
    """, (dia,))

def get_valor_pago_dia(dia: str) -> float:
    pagos = local_query("SELECT fn_areceber_id FROM cob_interacoes WHERE date(criado_em)=? AND pago=1", (dia,))
    if not pagos:
        return 0.0
    ids = [str(r["fn_areceber_id"]) for r in pagos if r["fn_areceber_id"]]
    if not ids:
        return 0.0
    ph  = ",".join(["%s"]*len(ids))
    res = query_one(f"SELECT COALESCE(SUM(valor_recebido),0) AS total FROM ixcprovedor.fn_areceber WHERE id IN ({ph}) AND status='R'", tuple(ids))
    return float(res["total"]) if res else 0.0

def get_cobrancas_semana():
    hoje = now_br().date()
    seg  = hoje - timedelta(days=hoje.weekday())
    result = []
    for i in range(hoje.weekday()+1):
        dia = (seg + timedelta(days=i)).isoformat()
        result.append({"dia": dia, "rows": get_cobrancas_dia(dia), "valor": get_valor_pago_dia(dia)})
    return result

# ── RELATÓRIO HORÁRIO ─────────────────────────────────────────────────────────
def relatorio_horario():
    agora     = now_br()
    hora      = agora.hour
    hoje      = agora.strftime('%Y-%m-%d')
    rows      = get_cobrancas_dia(hoje)
    valor     = get_valor_pago_dia(hoje)
    ret       = local_query_one("SELECT COUNT(*) AS total FROM cob_retiradas_agendamentos WHERE status='agendado'")
    total_ret = ret["total"] if ret else 0
    meta_ref  = META_MEIO_DIA if hora < 13 else META_DIA
    meta_label= "meta até 12h" if hora < 13 else "meta do dia"

    linhas = [
        f"📊 <b>COBRANÇA — ATUALIZAÇÃO {agora.strftime('%H:%M')}</b>",
        f"📅 {agora.strftime('%d/%m/%Y')}  |  🎯 Meta: {meta_ref} cobranças ({meta_label})",
        "",
        "👥 <b>DESEMPENHO HOJE</b>",
    ]
    total_geral = 0
    for c in rows:
        t     = c["total"]
        p     = c["promessas"]
        pg    = c["pagos"]
        efic  = round(pg/t*100) if t > 0 else 0
        falta = max(0, meta_ref - t)
        total_geral += t
        meta_str = "✅ Meta atingida!" if t >= meta_ref else f"⚠️ Faltam {falta} para a meta"
        linhas.append(
            f"  • <b>{c['nome']}</b>\n"
            f"    📞 {t} cobranças  🤝 {p} promessas  ✅ {pg} pagos  ⚡ {efic}%\n"
            f"    {meta_str}"
        )
    if not rows:
        linhas.append("  Nenhuma cobrança registrada ainda.")

    total_falta = max(0, meta_ref * len(rows) - total_geral) if rows else 0
    linhas += [
        "",
        f"📞 <b>Total equipe:</b> {total_geral}  |  ⚠️ Faltam {total_falta} para meta da equipe",
        f"💰 <b>Valor pago:</b> {fmt_valor(valor)}",
        f"📦 <b>OS retiradas agendadas:</b> {total_ret}",
        "",
        "<i>IaTechHub</i>",
    ]
    return "\n".join(linhas)

# ── RANKING COM META ──────────────────────────────────────────────────────────
def relatorio_ranking(fechamento=False):
    agora    = now_br()
    hoje     = agora.strftime('%Y-%m-%d')
    rows     = get_cobrancas_dia(hoje)
    valor    = get_valor_pago_dia(hoje)
    meta_ref = META_DIA if fechamento else META_MEIO_DIA
    titulo   = f"🏆 <b>RANKING FINAL DO DIA — {agora.strftime('%d/%m/%Y')}</b>" if fechamento else f"🏆 <b>RANKING MEIO-DIA — {agora.strftime('%d/%m/%Y')}</b>"

    linhas = [titulo, f"🎯 Meta: {meta_ref} cobranças", ""]
    medalhas = ["🥇","🥈","🥉","4️⃣","5️⃣"]

    for i, c in enumerate(rows):
        t     = c["total"]
        falta = max(0, meta_ref - t)
        efic  = round(c["pagos"]/t*100) if t > 0 else 0
        medal = medalhas[i] if i < len(medalhas) else "▪️"
        if t >= meta_ref:
            status = "✅ <b>META ATINGIDA!</b> 🎉 Excelente trabalho! Continue assim!"
        elif falta <= 10:
            status = f"🔥 Faltam apenas <b>{falta}</b> para a meta! Não para agora!"
        elif falta <= 30:
            status = f"⚡ Faltam <b>{falta}</b>. Foque nos clientes com promessas vencidas!"
        else:
            status = f"⚠️ Faltam <b>{falta}</b>. Priorize devedores +60d, envie WhatsApp e registre todas as tentativas."
        linhas.append(
            f"{medal} <b>{c['nome']}</b>\n"
            f"    📞 {t} cobranças  🤝 {c['promessas']} promessas  ✅ {c['pagos']} pagos  ⚡ {efic}%\n"
            f"    {status}"
        )

    if not rows:
        linhas.append("Nenhuma cobrança registrada ainda hoje.")

    linhas += ["", f"💰 <b>Valor pago hoje:</b> {fmt_valor(valor)}", "", "<i>IaTechHub</i>"]
    return "\n".join(linhas)

# ── RESUMO SEMANAL ────────────────────────────────────────────────────────────
def relatorio_semanal():
    agora      = now_br()
    semana     = get_cobrancas_semana()
    dias_pt    = ["Segunda","Terça","Quarta","Quinta","Sexta","Sábado","Domingo"]
    total_sem  = 0
    valor_sem  = 0.0
    operadores = {}

    linhas = [
        f"📅 <b>RESUMO SEMANAL DE COBRANÇA</b>",
        f"Semana encerrada em {agora.strftime('%d/%m/%Y')}",
        "",
    ]
    for entry in semana:
        d        = date.fromisoformat(entry["dia"])
        subtotal = sum(r["total"] for r in entry["rows"])
        total_sem  += subtotal
        valor_sem  += entry["valor"]
        linhas.append(f"  📆 <b>{dias_pt[d.weekday()]} {d.strftime('%d/%m')}:</b> {subtotal} cobranças | {fmt_valor(entry['valor'])}")
        for r in entry["rows"]:
            k = r["nome"]
            if k not in operadores:
                operadores[k] = {"total":0,"promessas":0,"pagos":0}
            operadores[k]["total"]     += r["total"]
            operadores[k]["promessas"] += r["promessas"]
            operadores[k]["pagos"]     += r["pagos"]

    linhas += ["", "👥 <b>RESULTADO POR COLABORADOR NA SEMANA</b>"]
    dias_uteis = len(semana)
    for nome, d in sorted(operadores.items(), key=lambda x: -x[1]["total"]):
        t         = d["total"]
        efic      = round(d["pagos"]/t*100) if t > 0 else 0
        meta_sem  = META_DIA * dias_uteis
        atingiu   = "✅" if t >= meta_sem else "⚠️"
        linhas.append(
            f"  {atingiu} <b>{nome}</b>\n"
            f"    📞 {t} cobranças  🤝 {d['promessas']} promessas  ✅ {d['pagos']} pagos  ⚡ {efic}%\n"
            f"    Meta semana: {meta_sem} | {'Atingiu!' if t >= meta_sem else f'Faltaram {meta_sem-t}'}"
        )

    linhas += [
        "",
        f"📊 <b>TOTAIS DA SEMANA</b>",
        f"  📞 Total cobranças: <b>{total_sem}</b>",
        f"  💰 Valor recuperado: <b>{fmt_valor(valor_sem)}</b>",
        "",
        "<i>IaTechHub</i>",
    ]
    return "\n".join(linhas)

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    agora   = now_br()
    hora    = agora.hour
    dia_sem = agora.weekday()  # 0=seg ... 5=sab ... 6=dom

    try:
        if dia_sem == 5 and hora == 18:
            msg = relatorio_semanal()
        elif hora == 12:
            msg = relatorio_ranking(fechamento=False)
        elif hora == 18:
            msg = relatorio_ranking(fechamento=True)
        else:
            msg = relatorio_horario()

        enviar(msg)
        print(f"[{agora.strftime('%d/%m/%Y %H:%M')}] Enviado OK")
    except Exception as e:
        print(f"[ERRO] {e}")
        enviar(f"⚠️ Erro no relatório Cliquedf: {e}")
