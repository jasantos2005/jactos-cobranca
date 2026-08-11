COMERCIAL_DB = "/opt/automacoes/cliquedf/comercial/hub_comercial.db"
COMISSAO_VENDA = 20.0
CUSTO_INSTALACAO_MEDIO = 303.58
import sqlite3
from app.core.db import query, query_one
from app.core.db_local import local_query

COMERCIAL_DB = "/opt/automacoes/cliquedf/comercial/hub_comercial.db"

def get_comercial(sql, params=()):
    conn = sqlite3.connect(COMERCIAL_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def _get_serasa_map(ids_clientes):
    if not ids_clientes:
        return {}
    conn = sqlite3.connect(COMERCIAL_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    ph = ",".join("?" * len(ids_clientes))
    cur.execute(f"""
        SELECT p.ixc_cliente_id, al.resultado, al.detalhes
        FROM hc_precadastros p
        JOIN hc_auditoria_log al ON al.precadastro_id=p.id
        WHERE p.ixc_cliente_id IN ({ph})
          AND al.resultado IN ('ok','reprovado','pendente')
          AND (al.regra LIKE '%serasa%' OR al.regra LIKE '%credito%' OR al.regra LIKE '%CREDITONM%')
        ORDER BY al.id DESC
    """, ids_clientes)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    serasa_map = {}
    for r in rows:
        cid = str(r["ixc_cliente_id"])
        if cid not in serasa_map:
            serasa_map[cid] = {"resultado": r["resultado"], "detalhes": r["detalhes"]}
    return serasa_map

def get_qualidade_vendas(mes=None, vendedor=None, parcela=None):
    """
    Cruza clientes ativados no período com os que entraram na cobrança.
    """
    filtro = "WHERE data_ativacao IS NOT NULL AND data_ativacao != ''"
    params = []
    if mes:
        filtro += " AND strftime('%Y-%m', data_ativacao) = ?"
        params.append(mes)
    if vendedor:
        filtro += " AND vendedor_nome = ?"
        params.append(vendedor)

    contratos = get_comercial(f"""
        SELECT ixc_contrato_id, ixc_cliente_id, razao, vendedor_nome,
               data_ativacao, plano_nome, plano_valor, status_contrato
        FROM hc_contratos_cache
        {filtro}
        ORDER BY data_ativacao DESC
    """, params)

    if not contratos:
        return []

    # Busca quais estão na cobrança
    ids_clientes = tuple(c["ixc_cliente_id"] for c in contratos if c["ixc_cliente_id"])
    ph = ",".join(["%s"]*len(ids_clientes))

    clientes_cobranca = query(f"""
        SELECT f.id_cliente,
               MAX(DATEDIFF(CURDATE(), f.data_vencimento)) AS maior_atraso,
               SUM(f.valor_aberto) AS total_aberto,
               COUNT(f.id) AS qtd_faturas,
               MIN(f.nparcela) AS menor_parcela,
               (SELECT COUNT(*) FROM ixcprovedor.fn_areceber fp
                WHERE fp.id_cliente=f.id_cliente AND fp.status='R') AS meses_pagos
        FROM ixcprovedor.fn_areceber f
        WHERE f.id_cliente IN ({ph})
          AND f.status='A' AND f.data_vencimento < CURDATE()
        GROUP BY f.id_cliente
    """, ids_clientes) if ids_clientes else []

    cobranca_map = {str(r["id_cliente"]): r for r in clientes_cobranca}
    serasa_map   = _get_serasa_map(ids_clientes)

    result = []
    for c in contratos:
        cob    = cobranca_map.get(str(c["ixc_cliente_id"]))
        serasa = serasa_map.get(str(c["ixc_cliente_id"]), {})
        result.append({
            **c,
            "na_cobranca":   bool(cob),
            "maior_atraso":  int(cob["maior_atraso"]) if cob and cob["maior_atraso"] else 0,
            "total_aberto":  float(cob["total_aberto"]) if cob and cob["total_aberto"] else 0,
            "qtd_faturas":   int(cob["qtd_faturas"]) if cob and cob["qtd_faturas"] else 0,
            "menor_parcela": int(cob["menor_parcela"]) if cob and cob["menor_parcela"] else 0,
            "meses_pagos":   int(cob["meses_pagos"]) if cob and cob["meses_pagos"] else 0,
            "serasa":        serasa.get("resultado", "—"),
            "serasa_det":    serasa.get("detalhes", ""),
        })
    if parcela is not None:
        result = [r for r in result if r["na_cobranca"] and r["menor_parcela"] == int(parcela)]
    return result

def get_kpis_qualidade(mes=None, parcela=None):
    rows = get_qualidade_vendas(mes=mes, parcela=parcela)
    mes_ref = mes
    # Total sempre sem filtro de parcela
    total_mes = get_qualidade_vendas(mes=mes)
    total = len(total_mes) if parcela else len(rows)
    na_cobranca = sum(1 for r in rows if r["na_cobranca"])
    por_vendedor = {}
    for r in rows:
        v = r["vendedor_nome"] or "—"
        if v not in por_vendedor:
            por_vendedor[v] = {"vendedor": v, "total": 0, "na_cobranca": 0, "valor_risco": 0}
        por_vendedor[v]["total"] += 1
        if r["na_cobranca"]:
            por_vendedor[v]["na_cobranca"] += 1
            por_vendedor[v]["valor_risco"] += r["total_aberto"]
    ranking = sorted(por_vendedor.values(), key=lambda x: x["na_cobranca"], reverse=True)
    # Calcula prejuizo total somando de todos os vendedores
    score_ranks = get_score_vendedores(mes=mes_ref)
    prejuizo_total = sum(v.get("prejuizo", 0) for v in score_ranks)
    return {
        "total": total,
        "na_cobranca": na_cobranca,
        "taxa": round(na_cobranca / total * 100, 1) if total else 0,
        "ranking": ranking,
        "prejuizo_total": round(prejuizo_total, 2),
    }

def get_meses_disponiveis():
    rows = get_comercial("""
        SELECT DISTINCT strftime('%Y-%m', data_ativacao) AS mes
        FROM hc_contratos_cache
        WHERE data_ativacao IS NOT NULL AND data_ativacao != ''
        ORDER BY mes DESC LIMIT 12
    """)
    return [r["mes"] for r in rows if r["mes"]]

def get_ranking_planos(mes=None):
    rows = get_qualidade_vendas(mes=mes)
    por_plano = {}
    for r in rows:
        p = r["plano_nome"] or "—"
        if p not in por_plano:
            por_plano[p] = {"plano": p, "total": 0, "na_cobranca": 0, "valor_risco": 0.0}
        por_plano[p]["total"] += 1
        if r["na_cobranca"]:
            por_plano[p]["na_cobranca"] += 1
            por_plano[p]["valor_risco"] += r["total_aberto"]
    ranking = sorted(por_plano.values(), key=lambda x: -x["na_cobranca"])
    for p in ranking:
        p["taxa"] = round(p["na_cobranca"] / p["total"] * 100) if p["total"] else 0
    return ranking


def get_score_vendedores(mes=None):
    """
    Score de qualidade 0-10 por vendedor baseado em:
    - % inadimplência (peso 50%)
    - % que pagou 3+ meses (peso 30%)
    - % 1ª parcela não paga (peso 20%)
    """
    rows = get_qualidade_vendas(mes=mes)
    por_vendedor = {}
    for r in rows:
        v = r["vendedor_nome"] or "—"
        if v not in por_vendedor:
            por_vendedor[v] = {"vendedor": v, "total": 0, "inadimplentes": 0,
                               "pagou_3_meses": 0, "nao_pagou_1a": 0, "valor_risco": 0}
        por_vendedor[v]["total"] += 1
        if r["na_cobranca"]:
            por_vendedor[v]["inadimplentes"] += 1
            por_vendedor[v]["valor_risco"]   += r["total_aberto"]
            if r["menor_parcela"] == 1:
                por_vendedor[v]["nao_pagou_1a"] += 1
        else:
            if r["meses_pagos"] >= 3:
                por_vendedor[v]["pagou_3_meses"] += 1

    resultado = []
    for v, d in por_vendedor.items():
        if d["total"] == 0:
            continue
        pct_inad   = d["inadimplentes"] / d["total"]
        pct_3m     = d["pagou_3_meses"] / d["total"]
        pct_1a     = d["nao_pagou_1a"]  / d["total"]
        score = 10 - (pct_inad * 5) - (pct_1a * 3) + (pct_3m * 2)
        score = max(0, min(10, round(score, 1)))
        # Prejuizo total = equipamentos + comissao + receita perdida
        prejuizo = (d["inadimplentes"] * CUSTO_INSTALACAO_MEDIO) +                    (d["inadimplentes"] * COMISSAO_VENDA) +                    d["valor_risco"]
        resultado.append({
            **d,
            "pct_inad":   round(pct_inad * 100),
            "pct_3m":     round(pct_3m * 100),
            "pct_1a":     round(pct_1a * 100),
            "score":      score,
            "prejuizo":   round(prejuizo, 2),
            "custo_instalacao": round(d["inadimplentes"] * CUSTO_INSTALACAO_MEDIO, 2),
            "custo_comissao":   round(d["inadimplentes"] * COMISSAO_VENDA, 2),
        })
    return sorted(resultado, key=lambda x: -x["score"])


def get_inadimplencia_cidade():
    import sqlite3
    COMERCIAL_DB = "/opt/automacoes/cliquedf/comercial/hub_comercial.db"
    conn = sqlite3.connect(COMERCIAL_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT cidade_nome, ixc_cliente_id
        FROM hc_contratos_cache
        WHERE cidade_nome IS NOT NULL AND cidade_nome != ''
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    if not rows:
        return []

    cidade_map  = {r["ixc_cliente_id"]: r["cidade_nome"] for r in rows}
    total_cidade = {}
    for r in rows:
        c = r["cidade_nome"]
        total_cidade[c] = total_cidade.get(c, 0) + 1

    ids = tuple(cidade_map.keys())
    ph  = ",".join(["%s"]*len(ids))
    inadimplentes = query(f"""
        SELECT f.id_cliente, SUM(f.valor_aberto) AS total_aberto
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id_cliente=f.id_cliente AND cc.status='A'
        WHERE f.status='A' AND f.data_vencimento < CURDATE()
        AND f.id_cliente IN ({ph})
        GROUP BY f.id_cliente
    """, ids)

    por_cidade = {}
    for r in inadimplentes:
        cidade = cidade_map.get(r["id_cliente"], "—")
        if cidade not in por_cidade:
            por_cidade[cidade] = {"cidade": cidade, "inad": 0, "valor": 0.0}
        por_cidade[cidade]["inad"]  += 1
        por_cidade[cidade]["valor"] += float(r["total_aberto"])

    resultado = []
    for cidade, d in por_cidade.items():
        total = total_cidade.get(cidade, 0)
        taxa  = round(d["inad"] / total * 100) if total else 0
        resultado.append({**d, "total": total, "taxa": taxa})
    return sorted(resultado, key=lambda x: -x["taxa"])


def get_vendedores_disponiveis():
    rows = get_comercial("""
        SELECT DISTINCT vendedor_nome FROM hc_contratos_cache
        WHERE vendedor_nome IS NOT NULL AND vendedor_nome != ''
        ORDER BY vendedor_nome
    """)
    return [r["vendedor_nome"] for r in rows]
