from app.core.db import query
from app.core.db_local import local_query, local_query_one
import sqlite3

COMERCIAL_DB = "/opt/automacoes/cliquedf/comercial/hub_comercial.db"

def get_nunca_pagaram(pagina=1, por_pagina=30):
    off = (pagina-1) * por_pagina

    # Busca clientes com promessa ativa (futura ou hoje)
    from app.core.db_local import local_query
    from datetime import date
    hoje = date.today().isoformat()
    com_promessa = local_query("""
        SELECT DISTINCT f.id_cliente FROM cob_interacoes i
        INNER JOIN ixcprovedor.fn_areceber f ON f.id=i.fn_areceber_id
        WHERE i.data_promessa >= ? AND i.pago=0 AND (i.resolvido IS NULL OR i.resolvido=0)
    """.replace("ixcprovedor.fn_areceber", "fn_areceber_cache"), (hoje,)) if False else []

    # Alternativa: busca fn_areceber_ids com promessa ativa
    fn_com_promessa = local_query("""
        SELECT DISTINCT fn_areceber_id FROM cob_interacoes
        WHERE data_promessa >= ? AND pago=0 AND (resolvido IS NULL OR resolvido=0)
    """, (hoje,))
    fn_ids_promessa = tuple(r["fn_areceber_id"] for r in fn_com_promessa if r["fn_areceber_id"])

    # Busca id_clientes dessas faturas no IXC
    ids_com_promessa = set()
    if fn_ids_promessa:
        ph_fn = ",".join(["%s"]*len(fn_ids_promessa))
        clientes_promessa = query(f"SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber WHERE id IN ({ph_fn})", fn_ids_promessa)
        ids_com_promessa = {r["id_cliente"] for r in clientes_promessa}

    rows = query("""
        SELECT cc.id_cliente, c.razao,
               COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone,
               cc.data_ativacao,
               DATEDIFF(CURDATE(), cc.data_ativacao) AS dias_ativado,
               MAX(DATEDIFF(CURDATE(), f.data_vencimento)) AS maior_atraso,
               SUM(f.valor_aberto) AS total_aberto,
               MIN(f.nparcela) AS menor_parcela,
               COUNT(f.id) AS qtd_faturas
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.cliente c ON c.id=cc.id_cliente
        INNER JOIN ixcprovedor.fn_areceber f ON f.id_cliente=cc.id_cliente
            AND f.status='A' AND f.data_vencimento < CURDATE()
        WHERE cc.status='A'
          AND DATEDIFF(CURDATE(), cc.data_ativacao) <= 90
          AND cc.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber WHERE status='R'
          )
          AND EXISTS (
            SELECT 1 FROM ixcprovedor.fn_areceber f2
            WHERE f2.id_cliente=cc.id_cliente
              AND f2.status='A'
              AND f2.data_vencimento < CURDATE()
              AND f2.data_vencimento >= cc.data_ativacao
          )
        GROUP BY cc.id_cliente, c.razao, c.whatsapp, c.telefone_celular, c.fone, cc.data_ativacao
        ORDER BY dias_ativado DESC
        LIMIT %s OFFSET %s
    """, (por_pagina, off))
    # Filtra clientes com promessa ativa
    if ids_com_promessa:
        rows = [r for r in rows if r["id_cliente"] not in ids_com_promessa]

    if not rows:
        return []

    # Busca vendedor no comercial
    ids = tuple(r["id_cliente"] for r in rows)
    ph  = ",".join("?" * len(ids))
    conn = sqlite3.connect(COMERCIAL_DB)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()
    cur.execute(f"SELECT ixc_cliente_id, vendedor_nome, cidade_nome FROM hc_contratos_cache WHERE ixc_cliente_id IN ({ph})", ids)
    comercial = {r["ixc_cliente_id"]: dict(r) for r in cur.fetchall()}
    conn.close()

    # Busca ultima interacao
    fn_ids = []
    for r in rows:
        fat = query("""SELECT id FROM ixcprovedor.fn_areceber
            WHERE id_cliente=%s AND status='A' AND data_vencimento < CURDATE()
            ORDER BY data_vencimento ASC LIMIT 1""", (r["id_cliente"],))
        if fat:
            fn_ids.append((r["id_cliente"], fat[0]["id"]))

    interacoes_map = {}
    for id_cli, fn_id in fn_ids:
        inter = local_query_one("""
            SELECT acao, strftime('%d/%m/%Y', criado_em) AS data_inter
            FROM cob_interacoes WHERE fn_areceber_id=?
            ORDER BY criado_em DESC LIMIT 1
        """, (fn_id,))
        interacoes_map[id_cli] = inter

    result = []
    for r in rows:
        com = comercial.get(r["id_cliente"], {})
        fat = next((f[1] for f in fn_ids if f[0] == r["id_cliente"]), None)
        result.append({
            **r,
            "vendedor":    com.get("vendedor_nome", "— IXC direto"),
            "cidade":      com.get("cidade_nome", "—"),
            "fn_id":       fat,
            "ultima_inter": interacoes_map.get(r["id_cliente"]),
        })
    return result

def _ids_com_promessa():
    """Retorna set de id_cliente com promessa ativa."""
    from app.core.db_local import local_query
    from datetime import date
    hoje = date.today().isoformat()
    fn_ids = local_query("""
        SELECT DISTINCT fn_areceber_id FROM cob_interacoes
        WHERE data_promessa >= ? AND pago=0 AND (resolvido IS NULL OR resolvido=0)
    """, (hoje,))
    fn_ids_t = tuple(r["fn_areceber_id"] for r in fn_ids if r["fn_areceber_id"])
    if not fn_ids_t:
        return set()
    ph = ",".join(["%s"]*len(fn_ids_t))
    clientes = query(f"SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber WHERE id IN ({ph})", fn_ids_t)
    return {r["id_cliente"] for r in clientes}

def count_nunca_pagaram():
    rows = get_nunca_pagaram(pagina=1, por_pagina=9999)
    return len(rows)

def get_kpis_nunca_pagaram():
    ids_promessa = _ids_com_promessa()
    rows = get_nunca_pagaram(pagina=1, por_pagina=9999)
    total = len(rows)
    total_aberto = sum(float(r.get("total_aberto") or 0) for r in rows)
    media_dias = sum(int(r.get("dias_ativado") or 0) for r in rows) / total if total else 0
    # Busca OS retirada
    if rows:
        ids = tuple(r["id_cliente"] for r in rows)
        ph = ",".join(["%s"]*len(ids))
        os_ret = query(f"""
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_cliente IN ({ph}) AND id_assunto IN (22,39) AND status NOT IN ('F')
        """, ids)
        com_retirada = len(os_ret)
    else:
        com_retirada = 0
    return {"total": total, "total_aberto": total_aberto, "media_dias": round(media_dias), "com_retirada": com_retirada}
