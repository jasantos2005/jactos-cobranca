from app.core.db import query, query_one


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

    result = []
    for r in rows:
        pagas = int(r["parcelas_pagas"] or 0)
        em_dia = int(r["pagas_em_dia"] or 0)
        atras = int(r["pagas_atrasadas"] or 0)
        suporte = int(r["qtd_suporte"] or 0)

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
            "vendedor": "—",
            "cidade":   "—",
            "plano":    r["plano"] or "—",
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
