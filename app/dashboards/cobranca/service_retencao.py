from app.core.db import query, query_one
from datetime import datetime, timezone, timedelta


def _calc_score(dias_atraso, total_pagas, pagas_em_dia, dias_ativado):
    score = 0

    # Atraso
    if dias_atraso >= 60:
        score += 35
    elif dias_atraso >= 30:
        score += 25
    elif dias_atraso >= 15:
        score += 15
    else:
        score += 5

    # Histórico bom de pagamentos
    if total_pagas >= 6 and pagas_em_dia >= total_pagas * 0.7:
        score += 20
    elif total_pagas >= 3:
        score += 10

    # Cliente novo
    if dias_ativado <= 90:
        score += 10

    return min(score, 100)


def get_retencao(pagina=1, por_pagina=30, score_min=30):
    off = (pagina - 1) * por_pagina

    candidatos = query("""
        SELECT
            d.id_cliente,
            c.razao,
            COALESCE(c.whatsapp, c.telefone_celular, c.fone, '') AS telefone,
            d.dias_atraso,
            d.total_aberto,
            COALESCE(p.pagas_em_dia, 0) AS pagas_em_dia,
            COALESCE(p.total_pagas, 0) AS total_pagas,
            DATEDIFF(CURDATE(), cc.data_ativacao) AS dias_ativado,
            cc.data_ativacao
        FROM (
            SELECT
                f.id_cliente,
                MAX(DATEDIFF(CURDATE(), f.data_vencimento)) AS dias_atraso,
                SUM(f.valor_aberto) AS total_aberto
            FROM ixcprovedor.fn_areceber f
            WHERE f.status = 'A'
              AND f.data_vencimento < CURDATE()
            GROUP BY f.id_cliente
        ) d

        INNER JOIN ixcprovedor.cliente c
            ON c.id = d.id_cliente

        INNER JOIN (
            SELECT
                id_cliente,
                MIN(data_ativacao) AS data_ativacao
            FROM ixcprovedor.cliente_contrato
            WHERE status = 'A'
            GROUP BY id_cliente
        ) cc
            ON cc.id_cliente = d.id_cliente

        LEFT JOIN (
            SELECT
                fr.id_cliente,
                COUNT(
                    DISTINCT CASE
                        WHEN fr.baixa_data IS NOT NULL
                         AND DATEDIFF(fr.baixa_data, fr.data_vencimento) <= 5
                        THEN fr.id
                    END
                ) AS pagas_em_dia,
                COUNT(DISTINCT fr.id) AS total_pagas
            FROM ixcprovedor.fn_areceber fr
            WHERE fr.status = 'R'
            GROUP BY fr.id_cliente
        ) p
            ON p.id_cliente = d.id_cliente

        WHERE d.dias_atraso BETWEEN 5 AND 90
        ORDER BY d.id_cliente
    """, ())

    scored = []

    for r in candidatos:
        score = _calc_score(
            int(r["dias_atraso"] or 0),
            int(r["total_pagas"] or 0),
            int(r["pagas_em_dia"] or 0),
            int(r["dias_ativado"] or 0),
        )

        if score < score_min:
            continue

        pagas_t = int(r.get("total_pagas") or 0)
        em_dia_t = int(r.get("pagas_em_dia") or 0)
        dias_t = int(r.get("dias_atraso") or 0)

        eh_bom = (
            pagas_t >= 6
            and em_dia_t >= pagas_t * 0.7
            and dias_t <= 60
        )

        if score >= 70:
            nivel = "critico"
        elif score >= 40:
            nivel = "atencao"
        elif eh_bom:
            nivel = "bom"
        else:
            nivel = "ok"

        scored.append({
            **r,
            "score": score,
            "nivel": nivel,
            "vendedor": "—",
            "cidade": "—",
            "total_aberto": float(r["total_aberto"] or 0),
            "total_pagas": pagas_t,
            "pagas_em_dia": em_dia_t,
        })

    scored.sort(key=lambda x: -x["score"])

    total = len(scored)

    return scored[off:off + por_pagina], total

def get_kpis_retencao():
    rows, total = get_retencao(
        pagina=1,
        por_pagina=9999,
        score_min=0,
    )

    criticos = sum(
        1 for r in rows
        if r["nivel"] == "critico"
    )

    atencao = sum(
        1 for r in rows
        if r["nivel"] == "atencao"
    )

    # Valor real diretamente do IXC.
    r_val = query_one("""
        SELECT SUM(f.valor_aberto) AS total
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente_contrato cc
            ON cc.id_cliente = f.id_cliente
           AND cc.status = 'A'
        WHERE f.status = 'A'
          AND f.data_vencimento < CURDATE()
          AND DATEDIFF(CURDATE(), f.data_vencimento)
              BETWEEN 5 AND 90
    """, ())

    valor = float(r_val["total"] or 0) if r_val else 0

    clientes_bons = sum(
        1 for r in rows
        if int(r.get("total_pagas") or 0) >= 6
        and int(r.get("pagas_em_dia") or 0)
            >= int(r.get("total_pagas") or 0) * 0.7
        and int(r.get("dias_atraso") or 0) <= 60
    )

    return {
        "total": total,
        "criticos": criticos,
        "atencao": atencao,
        "valor": valor,
        "clientes_bons": clientes_bons,
    }
