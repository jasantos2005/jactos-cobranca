from app.core.db_local import local_query
from datetime import datetime, timezone, timedelta

def now_br():
    return datetime.now(timezone(timedelta(hours=-3)))

def get_sessoes_dashboard():
    hoje = now_br().strftime('%Y-%m-%d')
    agora = now_br().strftime('%Y-%m-%d %H:%M:%S')

    # Online agora
    online_raw = local_query(
        "SELECT * FROM cob_sessoes WHERE logout_em IS NULL ORDER BY login_em DESC", ()
    )
    online = []
    for s in online_raw:
        try:
            ini = datetime.strptime(s["login_em"], '%Y-%m-%d %H:%M:%S')
            ini = ini.replace(tzinfo=timezone(timedelta(hours=-3)))
            mins = int((now_br() - ini).total_seconds() / 60)
            h, m = divmod(mins, 60)
            tempo = f"{h}h{m:02d}min" if h else f"{m}min"
        except: tempo = "—"
        online.append({**dict(s), "tempo_online": tempo})

    # Histórico hoje
    historico = local_query(
        "SELECT * FROM cob_sessoes WHERE login_em LIKE ? ORDER BY login_em DESC",
        (f"{hoje}%",)
    )

    # KPIs
    total_hoje = len(historico)
    mins_list = [s["duracao_min"] for s in historico if s["duracao_min"]]
    media_min = round(sum(mins_list) / len(mins_list)) if mins_list else 0
    total_inatividade = sum(1 for s in historico if s["motivo_logout"] == "Inatividade")

    # Resumo por usuário
    resumo_map = {}
    for s in historico:
        nome = s["usuario_nome"]
        if nome not in resumo_map:
            resumo_map[nome] = {"usuario_nome": nome, "sessoes": 0, "total_min": 0, "inatividades": 0}
        resumo_map[nome]["sessoes"] += 1
        resumo_map[nome]["total_min"] += int(s["duracao_min"] or 0)
        if s["motivo_logout"] == "Inatividade":
            resumo_map[nome]["inatividades"] += 1
    resumo = sorted(resumo_map.values(), key=lambda x: -x["total_min"])

    return {
        "online": online,
        "historico": list(historico),
        "total_hoje": total_hoje,
        "media_min": media_min,
        "total_inatividade": total_inatividade,
        "resumo": resumo,
    }
