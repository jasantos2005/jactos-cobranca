from app.core.db import query, query_one
import sqlite3

COMERCIAL_DB = "/opt/automacoes/cliquedf/comercial/hub_comercial.db"

def _filtro_base(data_ini, data_fim):
    where = f"cc.data_ativacao >= '{data_ini}'"
    if data_fim:
        where += f" AND cc.data_ativacao <= '{data_fim}'"
    return where

def _subquery_nunca_pagou():
    return """
        cc.id_cliente NOT IN (
            SELECT DISTINCT f.id_cliente FROM ixcprovedor.fn_areceber f
            WHERE f.status='R'
              AND f.baixa_data <= DATE_ADD(
                (SELECT cc2.data_ativacao FROM ixcprovedor.cliente_contrato cc2
                 WHERE cc2.id_cliente=f.id_cliente ORDER BY cc2.data_ativacao ASC LIMIT 1),
                INTERVAL 30 DAY)
        )
        AND EXISTS (
            SELECT 1 FROM ixcprovedor.fn_areceber f2
            WHERE f2.id_cliente=cc.id_cliente
              AND f2.status='A'
              AND f2.data_vencimento < CURDATE()
              AND f2.data_vencimento >= cc.data_ativacao
        )
    """

def get_kpis_resultado(data_ini="2026-01-01", data_fim=None):
    filtro = _filtro_base(data_ini, data_fim)
    nunca  = _subquery_nunca_pagou()
    r = query_one(f"""
        SELECT
            COUNT(DISTINCT cc.id_cliente) AS total,
            SUM(CASE WHEN pag.id_cliente IS NOT NULL THEN 1 ELSE 0 END) AS pagou,
            SUM(CASE WHEN cc.status='A' AND pag.id_cliente IS NULL AND os39.id_cliente IS NOT NULL THEN 1 ELSE 0 END) AS em_retirada,
            SUM(CASE WHEN cc.status='I' AND pag.id_cliente IS NULL AND os39f.id_cliente IS NOT NULL THEN 1 ELSE 0 END) AS retirado_cancelado,
            SUM(CASE WHEN cc.status='I' AND pag.id_cliente IS NULL AND os39f.id_cliente IS NULL THEN 1 ELSE 0 END) AS cancelado,
            SUM(CASE WHEN cc.status='A' AND pag.id_cliente IS NULL AND os39.id_cliente IS NULL THEN 1 ELSE 0 END) AS pendente
        FROM ixcprovedor.cliente_contrato cc
        LEFT JOIN (SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber WHERE status='R') pag ON pag.id_cliente=cc.id_cliente
        LEFT JOIN (SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado WHERE id_assunto=39 AND status NOT IN ('F')) os39 ON os39.id_cliente=cc.id_cliente
        LEFT JOIN (SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado WHERE id_assunto=39 AND status='F') os39f ON os39f.id_cliente=cc.id_cliente
        WHERE {filtro} AND {nunca}
    """, ())
    total = int(r["total"] or 0)
    pagou = int(r["pagou"] or 0)
    return {
        "total": total, "pagou": pagou,
        "em_retirada": int(r["em_retirada"] or 0),
        "cancelado": int(r["cancelado"] or 0),
        "retirado_cancelado": int(r["retirado_cancelado"] or 0),
        "pendente": int(r["pendente"] or 0),
        "taxa_recuperacao": round(pagou/total*100, 1) if total else 0,
    }

def count_resultado_nunca_pagaram(data_ini="2026-01-01", data_fim=None):
    filtro = _filtro_base(data_ini, data_fim)
    nunca  = _subquery_nunca_pagou()
    r = query_one(f"""
        SELECT COUNT(DISTINCT cc.id_cliente) AS total
        FROM ixcprovedor.cliente_contrato cc
        WHERE {filtro} AND {nunca}
    """, ())
    return int(r["total"]) if r else 0

def get_resultado_nunca_pagaram(data_ini="2026-01-01", data_fim=None, pagina=1, por_pagina=30):
    filtro = _filtro_base(data_ini, data_fim)
    nunca  = _subquery_nunca_pagou()
    off    = (pagina-1)*por_pagina
    rows = query(f"""
        SELECT cc.id AS contrato_id, cc.id_cliente, c.razao,
               COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone,
               DATE_FORMAT(cc.data_ativacao,'%%d/%%m/%%Y') AS data_ativacao,
               DATE_FORMAT(cc.data_cancelamento,'%%d/%%m/%%Y') AS data_cancelamento,
               cc.status AS contrato_status,
               DATEDIFF(CURDATE(), cc.data_ativacao) AS dias_ativado,
               cc.descricao_aux_plano_venda AS plano,
               (SELECT COUNT(*) FROM ixcprovedor.fn_areceber f WHERE f.id_cliente=cc.id_cliente AND f.status='R') AS total_pago,
               (SELECT SUM(f.valor) FROM ixcprovedor.fn_areceber f WHERE f.id_cliente=cc.id_cliente AND f.status='R') AS valor_pago,
               (SELECT o.id FROM ixcprovedor.su_oss_chamado o WHERE o.id_cliente=cc.id_cliente AND o.id_assunto=39 ORDER BY o.data_abertura DESC LIMIT 1) AS os39_id,
               (SELECT o.status FROM ixcprovedor.su_oss_chamado o WHERE o.id_cliente=cc.id_cliente AND o.id_assunto=39 ORDER BY o.data_abertura DESC LIMIT 1) AS os39_status,
               (SELECT SUM(f.valor_aberto) FROM ixcprovedor.fn_areceber f WHERE f.id_cliente=cc.id_cliente AND f.status='A' AND f.data_vencimento < CURDATE()) AS total_aberto
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.cliente c ON c.id=cc.id_cliente
        WHERE {filtro} AND {nunca}
        ORDER BY cc.data_ativacao DESC
        LIMIT {por_pagina} OFFSET {off}
    """, ())

    if not rows:
        return []

    ids = tuple(r["contrato_id"] for r in rows)
    ph  = ",".join("?"*len(ids))
    conn = sqlite3.connect(COMERCIAL_DB)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()
    cur.execute(f"SELECT ixc_contrato_id, vendedor_nome, cidade_nome, plano_nome FROM hc_contratos_cache WHERE ixc_contrato_id IN ({ph})", ids)
    com_map = {r["ixc_contrato_id"]: dict(r) for r in cur.fetchall()}
    conn.close()

    result = []
    for r in rows:
        com   = com_map.get(r["contrato_id"], {})
        pago  = int(r["total_pago"] or 0)
        aberto= float(r["total_aberto"] or 0)
        os39  = r["os39_status"]
        cancel= r["contrato_status"] == "I"
        if pago > 0:
            situacao = "pagou"
        elif cancel and os39 == "F":
            situacao = "retirado_cancelado"
        elif cancel:
            situacao = "cancelado"
        elif os39 and os39 not in ("F",):
            situacao = "em_retirada"
        else:
            situacao = "pendente"
        result.append({
            **r,
            "vendedor":    com.get("vendedor_nome", "—"),
            "cidade":      com.get("cidade_nome", "—"),
            "plano":       r["plano"] or com.get("plano_nome", "—"),
            "situacao":    situacao,
            "valor_pago":  float(r["valor_pago"] or 0),
            "total_aberto":aberto,
        })
    return result
