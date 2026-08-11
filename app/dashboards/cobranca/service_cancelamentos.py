from app.core.db import query, query_one
import sqlite3

COMERCIAL_DB = "/opt/automacoes/cliquedf/comercial/hub_comercial.db"

# Busca motivos direto do IXC na inicialização
def _carregar_motivos():
    try:
        from app.core.db import query
        rows = query("SELECT id, motivo FROM ixcprovedor.fn_areceber_mot_cancelamento ORDER BY id", ())
        import re
        motivos = {}
        for r in rows:
            # Remove prefixos como [CON], [BOL], [CONT], [FIN]
            nome = re.sub(r"\[\w+\]\s*", "", r["motivo"]).strip()
            motivos[r["id"]] = nome if nome else r["motivo"]
        return motivos
    except:
        return {}

MOTIVOS_CANCELAMENTO = _carregar_motivos()

def get_cancelamentos(mes=None, data_ini=None, data_fim=None, pagina=1, por_pagina=30):
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone(timedelta(hours=-3)))
    if not data_ini:
        data_ini = agora.strftime("%Y-%m-01")
    if not data_fim:
        data_fim = agora.strftime("%Y-%m-%d")

    off = (pagina-1)*por_pagina
    rows = query("""
        SELECT cc.id AS contrato_id, cc.id_cliente, c.razao,
               DATE_FORMAT(cc.data_ativacao,'%%d/%%m/%%Y') AS data_ativacao,
               DATE_FORMAT(cc.data_cancelamento,'%%d/%%m/%%Y') AS data_cancelamento,
               cc.descricao_aux_plano_venda AS plano,
               cc.obs_cancelamento, cc.motivo_cancelamento,
               cc.valor_unitario,
               DATEDIFF(cc.data_cancelamento, cc.data_ativacao) AS dias_na_base,
               COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.cliente c ON c.id=cc.id_cliente
        WHERE cc.status='I'
          AND cc.data_cancelamento >= %s
          AND cc.data_cancelamento <= %s
        ORDER BY cc.data_cancelamento DESC
        LIMIT %s OFFSET %s
    """, (data_ini, data_fim, por_pagina, off))

    if not rows:
        return []

    ids = tuple(r["id_cliente"] for r in rows)
    ph  = ",".join(["%s"]*len(ids))

    # Parcelas pagas por cliente
    parcelas = query(f"""
        SELECT id_cliente,
               COUNT(CASE WHEN status='R' THEN 1 END) AS pagas,
               COUNT(CASE WHEN status='A' THEN 1 END) AS abertas
        FROM ixcprovedor.fn_areceber
        WHERE id_cliente IN ({ph})
        GROUP BY id_cliente
    """, ids)
    parc_map = {r["id_cliente"]: r for r in parcelas}

    # Suporte últimos 6 meses (assuntos 16, 20, 21)
    suporte = query(f"""
        SELECT id_cliente, COUNT(*) AS qtd_suporte,
               GROUP_CONCAT(DISTINCT sa.assunto ORDER BY sa.assunto SEPARATOR ', ') AS tipos
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.su_oss_assunto sa ON sa.id=o.id_assunto
        WHERE o.id_cliente IN ({ph})
          AND o.id_assunto IN (16, 20, 21)
          AND o.data_abertura >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
        GROUP BY id_cliente
    """, ids)
    sup_map = {r["id_cliente"]: r for r in suporte}

    # Desconexões últimos 3 meses via radacct
    logins_map = {}
    for r in rows:
        login_row = query("""
            SELECT login FROM ixcprovedor.radusuarios WHERE id_cliente=%s LIMIT 1
        """, (r["id_cliente"],))
        if login_row:
            logins_map[r["id_cliente"]] = login_row[0]["login"]

    desconexoes_map = {}
    if logins_map:
        logins = tuple(logins_map.values())
        ph_l = ",".join(["%s"]*len(logins))
        descon = query(f"""
            SELECT username,
                   COUNT(*) AS total_descon,
                   SUM(CASE WHEN acctterminatecause='Lost-Carrier' THEN 1 ELSE 0 END) AS lost_carrier,
                   SUM(CASE WHEN acctterminatecause='User-Request' THEN 1 ELSE 0 END) AS user_request
            FROM ixcprovedor.radacct
            WHERE username IN ({ph_l})
              AND acctstoptime >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
              AND acctterminatecause != ''
            GROUP BY username
        """, logins)
        descon_by_login = {r['username']: r for r in descon}
        for id_cli, login in logins_map.items():
            if login in descon_by_login:
                desconexoes_map[id_cli] = descon_by_login[login]

    # Vendedor, plano e cidade no comercial
    conn = sqlite3.connect(COMERCIAL_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(f"SELECT ixc_contrato_id, ixc_cliente_id, vendedor_nome, cidade_nome, plano_nome, plano_valor FROM hc_contratos_cache WHERE ixc_contrato_id IN ({','.join('?'*len(ids))})", tuple(r["contrato_id"] for r in rows))
    com_map = {r["ixc_contrato_id"]: dict(r) for r in cur.fetchall()}
    conn.close()

    result = []
    for r in rows:
        parc  = parc_map.get(r["id_cliente"], {})
        sup   = sup_map.get(r["id_cliente"], {})
        com   = com_map.get(r["contrato_id"], {})
        motivo_id = r["motivo_cancelamento"] or 0
        result.append({
            **r,
            "parcelas_pagas": int(parc.get("pagas") or 0),
            "parcelas_abertas": int(parc.get("abertas") or 0),
            "motivo_desc": MOTIVOS_CANCELAMENTO.get(int(motivo_id), f"Motivo #{motivo_id}") if motivo_id else "—",
            "suporte_qtd": int(sup.get("qtd_suporte") or 0),
            "suporte_tipos": sup.get("tipos") or "—",
            "desconexoes": int(desconexoes_map.get(r["id_cliente"], {}).get("total_descon") or 0),
            "lost_carrier": int(desconexoes_map.get(r["id_cliente"], {}).get("lost_carrier") or 0),
            "user_request": int(desconexoes_map.get(r["id_cliente"], {}).get("user_request") or 0),
            "vendedor": com.get("vendedor_nome", "—"),
            "cidade": com.get("cidade_nome", "—"),
            "plano": r["plano"] or com.get("plano_nome", "—"),
            "plano_valor": float(com.get("plano_valor") or r.get("valor_unitario") or 0),
        })
    return result

def count_cancelamentos(data_ini=None, data_fim=None):
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone(timedelta(hours=-3)))
    if not data_ini:
        data_ini = agora.strftime("%Y-%m-01")
    if not data_fim:
        data_fim = agora.strftime("%Y-%m-%d")
    r = query_one("""
        SELECT COUNT(*) AS total, SUM(valor_unitario) AS receita_perdida
        FROM ixcprovedor.cliente_contrato
        WHERE status='I' AND data_cancelamento >= %s AND data_cancelamento <= %s
    """, (data_ini, data_fim))
    return r if r else {}

def get_resumo_motivos(data_ini=None, data_fim=None):
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone(timedelta(hours=-3)))
    ini = data_ini or agora.strftime("%Y-%m-01")
    fim = data_fim or agora.strftime("%Y-%m-%d")
    rows = query("""
        SELECT cc.motivo_cancelamento, cc.obs_cancelamento, COUNT(*) AS total
        FROM ixcprovedor.cliente_contrato cc
        WHERE cc.status='I' AND cc.data_cancelamento >= %s AND cc.data_cancelamento <= %s
        GROUP BY cc.motivo_cancelamento, cc.obs_cancelamento
        ORDER BY total DESC
    """, (ini, fim))
    por_motivo = {}
    for r in rows:
        mid = int(r["motivo_cancelamento"] or 0)
        desc = MOTIVOS_CANCELAMENTO.get(mid, f"Motivo #{mid}" if mid else "Não informado")
        if desc not in por_motivo:
            por_motivo[desc] = 0
        por_motivo[desc] += int(r["total"])
    return sorted([{"motivo": k, "total": v} for k,v in por_motivo.items()], key=lambda x: -x["total"])

def get_resumo_parcelas(data_ini=None, data_fim=None):
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone(timedelta(hours=-3)))
    ini = data_ini or agora.strftime("%Y-%m-01")
    fim = data_fim or agora.strftime("%Y-%m-%d")
    rows = query("""
        SELECT cc.id_cliente
        FROM ixcprovedor.cliente_contrato cc
        WHERE cc.status='I' AND cc.data_cancelamento >= %s AND cc.data_cancelamento <= %s
    """, (ini, fim))
    if not rows:
        return {"zero": 0, "um_dois": 0, "tres_mais": 0}
    ids = tuple(r["id_cliente"] for r in rows)
    ph  = ",".join(["%s"]*len(ids))
    parc = query(f"""
        SELECT id_cliente, COUNT(CASE WHEN status='R' THEN 1 END) AS pagas
        FROM ixcprovedor.fn_areceber WHERE id_cliente IN ({ph}) GROUP BY id_cliente
    """, ids)
    parc_map = {r["id_cliente"]: int(r["pagas"] or 0) for r in parc}
    zero = sum(1 for r in rows if parc_map.get(r["id_cliente"], 0) == 0)
    um_dois = sum(1 for r in rows if 1 <= parc_map.get(r["id_cliente"], 0) <= 2)
    tres_mais = sum(1 for r in rows if parc_map.get(r["id_cliente"], 0) >= 3)
    return {"zero": zero, "um_dois": um_dois, "tres_mais": tres_mais}

def get_kpis_cancelamentos(data_ini=None, data_fim=None):
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone(timedelta(hours=-3)))
    if not data_ini:
        data_ini = agora.strftime("%Y-%m-01")
    if not data_fim:
        data_fim = agora.strftime("%Y-%m-%d")
    rows = query("""
        SELECT cc.id_cliente,
               DATEDIFF(cc.data_cancelamento, cc.data_ativacao) AS dias_na_base,
               cc.motivo_cancelamento, cc.valor_unitario
        FROM ixcprovedor.cliente_contrato cc
        WHERE cc.status='I'
          AND cc.data_cancelamento >= %s AND cc.data_cancelamento <= %s
    """, (data_ini, data_fim))
    if not rows:
        return {}
    ids = tuple(r["id_cliente"] for r in rows)
    ph  = ",".join(["%s"]*len(ids))
    parc_all = query(f"""
        SELECT id_cliente, COUNT(CASE WHEN status='R' THEN 1 END) AS pagas
        FROM ixcprovedor.fn_areceber WHERE id_cliente IN ({ph}) GROUP BY id_cliente
    """, ids)
    parc_map = {r["id_cliente"]: int(r["pagas"] or 0) for r in parc_all}
    total    = len(rows)
    sem_pagar= sum(1 for r in rows if parc_map.get(r["id_cliente"], 0) == 0)
    com_sup  = 0
    if ids:
        s = query_one(f"""
            SELECT COUNT(DISTINCT id_cliente) AS total
            FROM ixcprovedor.su_oss_chamado
            WHERE id_cliente IN ({ph}) AND id_assunto IN (16,20,21)
              AND data_abertura >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
        """, ids)
        com_sup = int(s["total"]) if s else 0
    receita = sum(float(r["valor_unitario"] or 0) for r in rows)
    media_dias = sum(int(r["dias_na_base"] or 0) for r in rows) / total if total else 0
    return {
        "total": total, "sem_pagar": sem_pagar, "com_suporte": com_sup,
        "receita_perdida": receita, "media_dias": round(media_dias),
    }
