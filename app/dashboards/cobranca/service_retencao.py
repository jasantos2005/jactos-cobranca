from app.core.db import query, query_one
import sqlite3, re
from datetime import datetime, timezone, timedelta

COMERCIAL_DB = "/opt/automacoes/cliquedf/comercial/hub_comercial.db"

def _get_opa_index(dias=30):
    from datetime import datetime, timezone, timedelta
    data_limite = (datetime.now(timezone(timedelta(hours=-3))) - timedelta(days=dias)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(COMERCIAL_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT canal_cliente, setor, COUNT(*) AS total
        FROM opa_atendimentos
        WHERE data_abertura >= ?
        GROUP BY canal_cliente, setor
    """, (data_limite,))
    rows = cur.fetchall()
    conn.close()
    index = {}
    for o in rows:
        canal = re.sub(r"[^0-9]", "", (o["canal_cliente"] or "").replace("@c.us",""))
        if canal.startswith("55"): canal = canal[2:]
        if canal not in index: index[canal] = {}
        index[canal][o["setor"]] = index[canal].get(o["setor"], 0) + int(o["total"])
    return index

def _calc_score(dias_atraso, total_pagas, pagas_em_dia, opa_fin, opa_sup, dias_ativado):
    score = 0
    # Atraso
    if dias_atraso >= 60: score += 35
    elif dias_atraso >= 30: score += 25
    elif dias_atraso >= 15: score += 15
    else: score += 5
    # OPA financeiro
    if opa_fin >= 3: score += 30
    elif opa_fin >= 2: score += 20
    elif opa_fin >= 1: score += 10
    # OPA suporte
    if opa_sup >= 3: score += 25
    elif opa_sup >= 2: score += 15
    elif opa_sup >= 1: score += 8
    # Histórico bom
    if total_pagas >= 6 and pagas_em_dia >= total_pagas * 0.7: score += 20
    elif total_pagas >= 3: score += 10
    # Cliente novo
    if dias_ativado <= 90: score += 10
    return min(score, 100)

def get_retencao(pagina=1, por_pagina=30, score_min=30):
    import sqlite3 as _sq
    opa_index = _get_opa_index(dias=30)
    off = (pagina-1)*por_pagina

    candidatos = query("""
        SELECT cc.id_cliente, c.razao,
               COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone,
               MAX(DATEDIFF(CURDATE(), f.data_vencimento)) AS dias_atraso,
               SUM(CASE WHEN f.data_vencimento < CURDATE() THEN f.valor_aberto ELSE 0 END) AS total_aberto,
               COUNT(DISTINCT CASE WHEN fr.status='R' AND DATEDIFF(fr.baixa_data, fr.data_vencimento) <= 5 THEN fr.id END) AS pagas_em_dia,
               COUNT(DISTINCT CASE WHEN fr.status='R' THEN fr.id END) AS total_pagas,
               DATEDIFF(CURDATE(), cc.data_ativacao) AS dias_ativado,
               cc.data_ativacao
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.cliente c ON c.id=cc.id_cliente
        INNER JOIN ixcprovedor.fn_areceber f ON f.id_cliente=cc.id_cliente
            AND f.status='A' AND f.data_vencimento < CURDATE()
        LEFT JOIN ixcprovedor.fn_areceber fr ON fr.id_cliente=cc.id_cliente AND fr.status='R'
        WHERE cc.status='A'
        GROUP BY cc.id_cliente, c.razao, cc.data_ativacao,
                 c.whatsapp, c.telefone_celular, c.fone
        HAVING dias_atraso BETWEEN 5 AND 90
    """, ())

    # Busca vendedor
    if candidatos:
        ids = tuple(r["id_cliente"] for r in candidatos)
        ph  = ",".join("?"*len(ids))
        conn2 = _sq.connect(COMERCIAL_DB)
        conn2.row_factory = _sq.Row
        cur2  = conn2.cursor()
        cur2.execute(f"SELECT ixc_cliente_id, vendedor_nome, cidade_nome FROM hc_contratos_cache WHERE ixc_cliente_id IN ({ph})", ids)
        com_map = {r["ixc_cliente_id"]: dict(r) for r in cur2.fetchall()}
        conn2.close()
    else:
        com_map = {}

    scored = []
    vistos = set()
    for r in candidatos:
        if r["id_cliente"] in vistos: continue
        vistos.add(r["id_cliente"])
        fone = re.sub(r"[^0-9]", "", r["telefone"])
        if fone.startswith("55"): fone = fone[2:]
        opa  = opa_index.get(fone, {})
        opa_fin = opa.get("Financeiro", 0)
        opa_sup = opa.get("Suporte", 0)
        score = _calc_score(
            int(r["dias_atraso"] or 0),
            int(r["total_pagas"] or 0),
            int(r["pagas_em_dia"] or 0),
            opa_fin, opa_sup,
            int(r["dias_ativado"] or 0)
        )
        if score < score_min: continue
        com = com_map.get(r["id_cliente"], {})
        pagas_t = int(r.get("total_pagas") or 0)
        em_dia_t = int(r.get("pagas_em_dia") or 0)
        dias_t = int(r.get("dias_atraso") or 0)
        eh_bom = pagas_t >= 6 and em_dia_t >= pagas_t * 0.7 and dias_t <= 60
        if score >= 70: nivel = "critico"
        elif score >= 40: nivel = "atencao"
        elif eh_bom: nivel = "bom"
        else: nivel = "ok"
        scored.append({
            **r,
            "score": score,
            "nivel": nivel,
            "opa_fin": opa_fin,
            "opa_sup": opa_sup,
            "vendedor": com.get("vendedor_nome", "—"),
            "cidade":   com.get("cidade_nome", "—"),
            "total_aberto": float(r["total_aberto"] or 0),
            "total_pagas":  int(r["total_pagas"] or 0),
            "pagas_em_dia": int(r["pagas_em_dia"] or 0),
        })

    scored.sort(key=lambda x: -x["score"])
    total = len(scored)
    return scored[off:off+por_pagina], total

def get_kpis_retencao():
    rows, total = get_retencao(pagina=1, por_pagina=9999, score_min=0)
    criticos  = sum(1 for r in rows if r["nivel"]=="critico")
    atencao   = sum(1 for r in rows if r["nivel"]=="atencao")
    com_opa   = sum(1 for r in rows if r["opa_fin"]>0 or r["opa_sup"]>0)
    # Busca valor real direto do banco sem multiplicação
    from app.core.db import query_one
    r_val = query_one("""
        SELECT SUM(f.valor_aberto) AS total
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id_cliente=f.id_cliente AND cc.status='A'
        WHERE f.status='A'
          AND f.data_vencimento < CURDATE()
          AND DATEDIFF(CURDATE(), f.data_vencimento) BETWEEN 5 AND 90
    """, ())
    valor = float(r_val["total"] or 0) if r_val else 0
    clientes_bons = sum(1 for r in rows if
        int(r.get("total_pagas") or 0) >= 6 and
        int(r.get("pagas_em_dia") or 0) >= int(r.get("total_pagas") or 0) * 0.7 and
        int(r.get("dias_atraso") or 0) <= 60
    )
    return {"total": total, "criticos": criticos, "atencao": atencao, "com_opa": com_opa, "valor": valor, "clientes_bons": clientes_bons}
