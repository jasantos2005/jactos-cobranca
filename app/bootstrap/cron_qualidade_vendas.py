#!/usr/bin/env python3
"""
Cron Qualidade de Vendas — roda todo dia às 18h seg-sab
Alerta no Telegram quando vendedor ultrapassar 15% de inadimplência
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/cliquedf/cobranca')
os.chdir('/opt/automacoes/cliquedf/cobranca')

from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)

import requests
from app.dashboards.cobranca.service_qualidade import get_kpis_qualidade, get_ranking_planos, get_qualidade_vendas

TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHAT  = "-4989557189"
LIMITE_PCT     = 15
MINIMO_VENDAS  = 3
COMISSAO_POR_VENDA = 50  # R$ estimado por ativação

def telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        log(f"[TELEGRAM ERRO] {e}")

def verificar_primeira_parcela(agora):
    mes  = agora.strftime('%Y-%m')
    rows = get_qualidade_vendas(mes=mes, parcela=1)
    if not rows:
        return
    por_vendedor = {}
    for r in rows:
        v = r["vendedor_nome"] or "—"
        if v not in por_vendedor:
            por_vendedor[v] = []
        por_vendedor[v].append(r)

    linhas = [
        "🚨 <b>ALERTA — Clientes sem pagar 1ª parcela</b>",
        f"📅 {mes} | {len(rows)} clientes",
        "",
    ]
    for v, clientes in sorted(por_vendedor.items(), key=lambda x: -len(x[1])):
        linhas.append(f"👤 <b>{v}</b> — {len(clientes)} cliente(s):")
        for c in clientes[:3]:
            linhas.append(f"  • {c['razao']} — ativado {c['data_ativacao'][:10]} — {c['maior_atraso']}d")
        if len(clientes) > 3:
            linhas.append(f"  ... e mais {len(clientes)-3}")
    linhas.append(f"\n<i>IaTechHub · {agora.strftime('%d/%m/%Y %H:%M')}</i>")
    telegram("\n".join(linhas))
    log(f"Alerta 1ª parcela: {len(rows)} clientes")

def relatorio_qualidade(mes, label, agora):
    kpis   = get_kpis_qualidade(mes=mes)
    planos = get_ranking_planos(mes=mes)

    if not kpis["total"]:
        log(f"Sem dados para {mes}")
        return

    alertas  = []
    ok_list  = []
    for v in kpis["ranking"]:
        if v["total"] < MINIMO_VENDAS:
            continue
        pct = round(v["na_cobranca"] / v["total"] * 100)
        if pct >= LIMITE_PCT:
            alertas.append({**v, "pct": pct})
        else:
            ok_list.append({**v, "pct": pct})

    planos_criticos = [p for p in planos if p["taxa"] >= LIMITE_PCT and p["total"] >= MINIMO_VENDAS]

    linhas = [
        f"📊 <b>QUALIDADE DE VENDAS — {label.upper()}</b>",
        f"📅 {mes} | {kpis['total']} ativados | {kpis['na_cobranca']} na cobrança | {kpis['taxa']}% inadimplência",
        "",
    ]

    CUSTO_INST = 303.58
    if alertas:
        linhas.append(f"🔴 <b>VENDEDORES ACIMA DE {LIMITE_PCT}%:</b>")
        for v in alertas:
            prejuizo = (v["na_cobranca"] * CUSTO_INST) + (v["na_cobranca"] * COMISSAO_POR_VENDA) + v["valor_risco"]
            linhas.append(f"  • <b>{v['vendedor']}</b>: {v['na_cobranca']}/{v['total']} ({v['pct']}%)")
            linhas.append(f"    💸 Prejuízo: R$ {prejuizo:.2f} | 📦 Equip: R$ {v['na_cobranca']*CUSTO_INST:.2f} | 🤝 Comissão: R$ {v['na_cobranca']*COMISSAO_POR_VENDA:.0f} | 💰 Receita: R$ {v['valor_risco']:.2f}")
    else:
        linhas.append(f"✅ <b>Todos vendedores abaixo de {LIMITE_PCT}%</b>")

    if ok_list:
        linhas.append("")
        linhas.append("✅ <b>Dentro do limite:</b>")
        for v in ok_list:
            linhas.append(f"  • {v['vendedor']}: {v['na_cobranca']}/{v['total']} ({v['pct']}%)")

    if planos_criticos:
        linhas.append("")
        linhas.append(f"📦 <b>PLANOS CRÍTICOS (>{LIMITE_PCT}%):</b>")
        for p in planos_criticos:
            linhas.append(f"  • {p['plano']}: {p['na_cobranca']}/{p['total']} ({p['taxa']}%) — R$ {p['valor_risco']:.2f}")

    # Ranking retenção
    retencao = sorted(
        [{**v, "pct": round(v["na_cobranca"]/v["total"]*100)} for v in kpis["ranking"] if v["total"] >= MINIMO_VENDAS],
        key=lambda x: x["pct"]
    )
    if retencao:
        linhas.append("")
        linhas.append("🏆 <b>RANKING DE RETENÇÃO (melhor → pior):</b>")
        medalhas = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣"]
        for i, v in enumerate(retencao):
            medal    = medalhas[i] if i < len(medalhas) else "▪️"
            CUSTO_INST = 303.58
            prejuizo = (v["na_cobranca"] * CUSTO_INST) + (v["na_cobranca"] * COMISSAO_POR_VENDA) + v.get("valor_risco", 0)
            linhas.append(f"  {medal} <b>{v['vendedor']}</b>: {v['pct']}% inadimplência | {v['total']} vendas | 💸 Prejuízo: R$ {prejuizo:.2f}")

    linhas.append(f"\n<i>IaTechHub · {agora.strftime('%d/%m/%Y %H:%M')}</i>")
    telegram("\n".join(linhas))
    log(f"Telegram enviado — {len(alertas)} alertas")

def main():
    agora   = now_br()
    mes_ant = (agora.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    mes_atu = agora.strftime('%Y-%m')

    relatorio_qualidade(mes_ant, "mês anterior", agora)
    relatorio_qualidade(mes_atu, "mês atual", agora)
    verificar_primeira_parcela(agora)

if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
    verificar_primeira_parcela(now_br())
    # Envia resumo prejuizo para bot privado
    import requests
    from app.dashboards.cobranca.service_qualidade import get_kpis_qualidade, get_score_vendedores
    TOKEN_PRIV = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
    CHAT_PRIV  = "2135602169"
    agora2 = now_br()
    mes_ant2 = (agora2.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    mes_atu2 = agora2.strftime("%Y-%m")
    for mes, label in [(mes_ant2, "MES ANTERIOR"), (mes_atu2, "MES ATUAL")]:
        kpis  = get_kpis_qualidade(mes=mes)
        score = get_score_vendedores(mes=mes)
        if not kpis["total"]: continue
        linhas = [
            f"💸 PREJUIZO QUALIDADE VENDAS — {label}",
            f"📅 {mes} | {kpis['total']} ativados | {kpis['na_cobranca']} inadimplentes | {kpis['taxa']}%",
            f"💸 Prejuizo total: R$ {kpis['prejuizo_total']:.2f}",
            "",
            "Por vendedor:",
        ]
        for v in sorted(score, key=lambda x: -x.get("prejuizo",0)):
            if v.get("prejuizo", 0) > 0:
                linhas.append(f"  - {v['vendedor']}: R$ {v['prejuizo']:.2f} ({v['inadimplentes']} inad/{v['total']} vendas)")
        linhas.append(f"IaTechHub - {agora2.strftime('%d/%m/%Y %H:%M')}")
        requests.post(f"https://api.telegram.org/bot{TOKEN_PRIV}/sendMessage",
            data={"chat_id": CHAT_PRIV, "text": "\n".join(linhas), "parse_mode": "HTML"}, timeout=10)
    log("Resumo prejuizo enviado ao bot privado")
