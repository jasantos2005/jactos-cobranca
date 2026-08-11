from app.core.db import query, query_one
import sqlite3

COMERCIAL_DB = "/opt/automacoes/cliquedf/comercial/hub_comercial.db"

def get_cancelamentos_inadimplencia(data_ini=None, data_fim=None, pagina=1, por_pagina=30):
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone(timedelta(hours=-3)))
    ini = data_ini or agora.strftime("%Y-%m-01")
    fim = data_fim or agora.strftime("%Y-%m-%d")
    off = (pagina-1)*por_pagina

    rows = query(f"""
        SELECT c.id AS id_cliente, c.razao,
               COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone,
               DATE_FORMAT(cc.data_ativacao,'%%d/%%m/%%Y') AS data_ativacao,
               DATE_FORMAT(cc.data_cancelamento,'%%d/%%m/%%Y') AS data_cancelamento,
               cc.obs_cancelamento,
               DATEDIFF(cc.data_cancelamento, cc.data_ativacao) AS dias_na_base,
               cc.descricao_aux_plano_venda AS plano,
               -- Saude financeira
               COUNT(DISTINCT CASE WHEN f.status='R' THEN f.id END) AS parcelas_pagas,
               COUNT(DISTINCT CASE WHEN f.status='R' AND DATEDIFF(f.baixa_data, f.data_vencimento) <= 5 THEN f.id END) AS pagas_em_dia,
               COUNT(DISTINCT CASE WHEN f.status='R' AND DATEDIFF(f.baixa_data, f.data_vencimento) > 5 THEN f.id END) AS pagas_atrasadas,
               MAX(CASE WHEN f.status='R' THEN DATEDIFF(f.baixa_data, f.data_vencimento) END) AS maior_atraso_pago,
               -- Suporte
               COUNT(DISTINCT CASE WHEN o.id_assunto IN (16,20,21) THEN o.id END) AS qtd_suporte,
               COUNT(DISTINCT CASE WHEN o.id_assunto=20 THEN o.id END) AS sem_acesso,
               COUNT(DISTINCT CASE WHEN o.id_assunto=21 THEN o.id END) AS lenta,
               COUNT(DISTINCT CASE WHEN o.id_assunto=16 THEN o.id END) AS manutencao
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.cliente c ON c.id=cc.id_cliente
        LEFT JOIN ixcprovedor.fn_areceber f ON f.id_cliente=cc.id_cliente
        LEFT JOIN ixcprovedor.su_oss_chamado o ON o.id_cliente=cc.id_cliente
            AND o.id_assunto IN (16,20,21)
            AND o.data_abertura >= DATE_SUB(cc.data_cancelamento, INTERVAL 6 MONTH)
        WHERE cc.status='I'
          AND cc.motivo_cancelamento=13
          AND cc.data_cancelamento >= '{ini}'
          AND cc.data_cancelamento <= '{fim}'
        GROUP BY c.id, c.razao, c.whatsapp, c.telefone_celular, c.fone,
                 cc.data_ativacao, cc.data_cancelamento, cc.obs_cancelamento, cc.descricao_aux_plano_venda
        ORDER BY cc.data_cancelamento DESC
        LIMIT {por_pagina} OFFSET {off}
    """, ())

    if not rows:
        return []

    # Busca vendedor no comercial
    ids = tuple(r["id_cliente"] for r in rows)
    ph  = ",".join("?"*len(ids))
    conn = sqlite3.connect(COMERCIAL_DB)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()
    cur.execute(f"SELECT ixc_cliente_id, vendedor_nome, cidade_nome, plano_nome FROM hc_contratos_cache WHERE ixc_cliente_id IN ({ph})", ids)
    com_map = {r["ixc_cliente_id"]: dict(r) for r in cur.fetchall()}
    conn.close()

    # Busca atendimentos OPA por telefone
    import re
    # Carrega todos atendimentos OPA de suporte/financeiro de uma vez
    conn_opa = sqlite3.connect(COMERCIAL_DB)
    conn_opa.row_factory = sqlite3.Row
    cur_opa = conn_opa.cursor()
    cur_opa.execute("""
        SELECT canal_cliente, setor, COUNT(*) AS total
        FROM opa_atendimentos
        GROUP BY canal_cliente, setor
    """)
    opa_all = cur_opa.fetchall()
    conn_opa.close()

    # Indexa por numero limpo (remove @c.us e prefixo 55)
    opa_index = {}
    for o in opa_all:
        canal = (o["canal_cliente"] or "").replace("@c.us","")
        if canal.startswith("55") and len(canal) >= 12:
            canal = canal[2:]
        canal = re.sub(r"[^0-9]","", canal)
        if canal not in opa_index:
            opa_index[canal] = {}
        opa_index[canal][o["setor"]] = opa_index[canal].get(o["setor"], 0) + int(o["total"])

    # Busca todos telefones dos clientes no IXC
    ids_clientes = tuple(r["id_cliente"] for r in rows)
    ph_ids = ",".join(["%s"]*len(ids_clientes))
    todos_fones = query(f"""
        SELECT id,
               REGEXP_REPLACE(COALESCE(whatsapp,''), '[^0-9]', '') AS f1,
               REGEXP_REPLACE(COALESCE(telefone_celular,''), '[^0-9]', '') AS f2,
               REGEXP_REPLACE(COALESCE(fone,''), '[^0-9]', '') AS f3
        FROM ixcprovedor.cliente WHERE id IN ({ph_ids})
    """, ids_clientes)

    opa_map = {}
    for tf in todos_fones:
        merged = {}
        for campo in ["f1","f2","f3"]:
            fone = tf[campo] or ""
            if len(fone) >= 10:
                match = opa_index.get(fone)
                if match:
                    for setor, qtd in match.items():
                        merged[setor] = merged.get(setor, 0) + qtd
        if merged:
            opa_map[tf["id"]] = merged

    result = []
    for r in rows:
        com   = com_map.get(r["id_cliente"], {})
        pagas = int(r["parcelas_pagas"] or 0)
        em_dia= int(r["pagas_em_dia"] or 0)
        atras = int(r["pagas_atrasadas"] or 0)
        suporte = int(r["qtd_suporte"] or 0)
        opa   = opa_map.get(r["id_cliente"], {})

        # Classificação saúde financeira
        if pagas == 0:
            saude = "nunca_pagou"
        elif em_dia >= atras:
            saude = "boa"
        else:
            saude = "irregular"

        # Causa provável
        if suporte > 0 and saude in ("boa", "irregular"):
            causa = "suporte"
        elif pagas == 0:
            causa = "nunca_pagou"
        else:
            causa = "financeira"

        result.append({
            **r,
            "opa_suporte":   opa.get("Suporte", 0),
            "opa_financeiro": opa.get("Financeiro", 0),
            "opa_agvirtual":  opa.get("Ag. Virtual", 0),
            "vendedor": com.get("vendedor_nome", "—"),
            "cidade":   com.get("cidade_nome", "—"),
            "plano":    r["plano"] or com.get("plano_nome", "—"),
            "saude":    saude,
            "causa":    causa,
            "parcelas_pagas": pagas,
            "pagas_em_dia":   em_dia,
            "pagas_atrasadas":atras,
            "qtd_suporte":    suporte,
            "sem_acesso":     int(r["sem_acesso"] or 0),
            "lenta":          int(r["lenta"] or 0),
            "manutencao":     int(r["manutencao"] or 0),
        })
    return result

def get_kpis_cancelamentos_inad(data_ini=None, data_fim=None):
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone(timedelta(hours=-3)))
    ini = data_ini or agora.strftime("%Y-%m-01")
    fim = data_fim or agora.strftime("%Y-%m-%d")
    rows = get_cancelamentos_inadimplencia(data_ini=ini, data_fim=fim, pagina=1, por_pagina=9999)
    total = len(rows)
    nunca = sum(1 for r in rows if r["saude"]=="nunca_pagou")
    boa   = sum(1 for r in rows if r["saude"]=="boa")
    irreg = sum(1 for r in rows if r["saude"]=="irregular")
    com_sup = sum(1 for r in rows if r["qtd_suporte"]>0)
    causa_sup = sum(1 for r in rows if r["causa"]=="suporte")
    return {
        "total": total, "nunca_pagou": nunca,
        "saude_boa": boa, "saude_irregular": irreg,
        "com_suporte": com_sup, "causa_suporte": causa_sup,
    }

def count_cancelamentos_inad(data_ini=None, data_fim=None):
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone(timedelta(hours=-3)))
    ini = data_ini or agora.strftime("%Y-%m-01")
    fim = data_fim or agora.strftime("%Y-%m-%d")
    r = query_one(f"""
        SELECT COUNT(*) AS total FROM ixcprovedor.cliente_contrato
        WHERE status='I' AND motivo_cancelamento=13
          AND data_cancelamento >= '{ini}' AND data_cancelamento <= '{fim}'
    """, ())
    return int(r["total"]) if r else 0
