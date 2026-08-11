from app.core.db import query, query_one
from app.core.db_local import local_query_one
import sqlite3, re
from datetime import datetime, timezone, timedelta

COMERCIAL_DB = "/opt/automacoes/cliquedf/comercial/hub_comercial.db"

def now_br():
    return datetime.now(timezone(timedelta(hours=-3)))

def get_dashboard_gerencial():
    agora   = now_br()
    mes_atu = agora.strftime("%Y-%m")
    mes_ant = (agora.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    # === ANO ANTERIOR (mesmo período) ===
    ano_ant = agora.year - 1
    mes_num = agora.month

    rec_ant = query_one("""
        SELECT COUNT(DISTINCT f.id_cliente) AS contratos,
               SUM(f.valor) AS receita_mensal
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id=f.id_contrato AND cc.status='A'
        WHERE MONTH(f.data_vencimento)=%s AND YEAR(f.data_vencimento)=%s
    """, (mes_num, ano_ant))

    cancel_ant = query_one(f"""
        SELECT COUNT(*) AS total FROM ixcprovedor.cliente_contrato
        WHERE status='I' AND MONTH(data_cancelamento)={mes_num} AND YEAR(data_cancelamento)={ano_ant}
    """, ())

    rec_ant_v      = float(rec_ant["receita_mensal"] or 0)
    contratos_ant  = int(rec_ant["contratos"] or 0)
    cancel_ant_v   = int(cancel_ant["total"] or 0)

    # Inadimplência ano anterior
    inad_ant_yy = query_one(f"""
        SELECT COUNT(DISTINCT f.id_cliente) AS total_inad,
               SUM(f.valor_aberto) AS total_aberto
        FROM ixcprovedor.fn_areceber f
        WHERE f.status='A'
          AND f.data_vencimento < '{ano_ant}-{agora.month:02d}-{agora.day:02d}'
          AND MONTH(f.data_vencimento) <= {agora.month}
          AND YEAR(f.data_vencimento) = {ano_ant}
    """, ())
    inad_ant_total   = int(inad_ant_yy["total_inad"] or 0)
    inad_ant_aberto  = float(inad_ant_yy["total_aberto"] or 0)

    # Cancelamentos por inadimplência ano anterior
    cancel_inad_ant = query_one(f"""
        SELECT COUNT(*) AS total FROM ixcprovedor.cliente_contrato
        WHERE status='I' AND motivo_cancelamento=13
        AND MONTH(data_cancelamento)={agora.month} AND YEAR(data_cancelamento)={ano_ant}
    """, ())
    cancel_inad_ant_v = int(cancel_inad_ant["total"] or 0)

    # === SAÚDE FINANCEIRA ===
    receita = query_one("""
        SELECT COUNT(DISTINCT f.id_cliente) AS contratos,
               SUM(f.valor) AS receita_mensal,
               AVG(f.valor) AS ticket_medio
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id=f.id_contrato AND cc.status='A'
        WHERE MONTH(f.data_vencimento)=MONTH(CURDATE())
          AND YEAR(f.data_vencimento)=YEAR(CURDATE())
    """, ())

    inad = query_one("""
        SELECT COUNT(DISTINCT f.id_cliente) AS total_inad,
               SUM(f.valor_aberto) AS total_aberto
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id_cliente=f.id_cliente AND cc.status='A'
        WHERE f.status='A' AND f.data_vencimento < CURDATE()
    """, ())

    # Inadimplência segmentada por ano de ativação
    inad_seg = query("""
        SELECT YEAR(cc.data_ativacao) AS ano_ativ,
               COUNT(DISTINCT f.id_cliente) AS total,
               SUM(f.valor_aberto) AS valor
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id_cliente=f.id_cliente AND cc.status='A'
        WHERE f.status='A' AND f.data_vencimento < CURDATE()
        GROUP BY YEAR(cc.data_ativacao)
        ORDER BY ano_ativ DESC
    """, ())
    inad_ano_atual = next((r for r in inad_seg if r["ano_ativ"] == agora.year), {})
    inad_ano_ant_s = next((r for r in inad_seg if r["ano_ativ"] == agora.year-1), {})
    inad_historico = sum(int(r["total"]) for r in inad_seg if r["ano_ativ"] < agora.year-1)

    # Inadimplência mês anterior para tendência
    inad_ant = query_one("""
        SELECT COUNT(DISTINCT f.id_cliente) AS total_inad_ant
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id_cliente=f.id_cliente AND cc.status='A'
        WHERE f.status='A'
          AND MONTH(f.data_vencimento)=MONTH(DATE_SUB(CURDATE(), INTERVAL 1 MONTH))
          AND YEAR(f.data_vencimento)=YEAR(DATE_SUB(CURDATE(), INTERVAL 1 MONTH))
    """, ())

    contratos   = int(receita["contratos"] or 0)
    rec_mensal  = float(receita["receita_mensal"] or 0)
    ticket      = float(receita["ticket_medio"] or 0)
    total_inad  = int(inad["total_inad"] or 0)
    total_aberto= float(inad["total_aberto"] or 0)
    taxa_inad   = round(total_inad/contratos*100, 1) if contratos else 0
    risco_real  = round(total_aberto*0.4, 2)
    inad_ant_v  = int(inad_ant["total_inad_ant"] or 0)
    tend_inad   = "up" if total_inad > inad_ant_v else "down" if total_inad < inad_ant_v else "stable"

    # === ALERTAS ===
    nunca_pagaram = query_one("""
        SELECT COUNT(DISTINCT cc.id_cliente) AS total
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.fn_areceber f ON f.id_cliente=cc.id_cliente
            AND f.status='A' AND f.data_vencimento < CURDATE()
            AND f.data_vencimento >= cc.data_ativacao
        WHERE cc.status='A'
          AND DATEDIFF(CURDATE(), cc.data_ativacao) <= 90
          AND cc.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber WHERE status='R'
          )
    """, ())

    os39_abertas = query_one("""
        SELECT COUNT(*) AS total FROM ixcprovedor.su_oss_chamado
        WHERE id_assunto=39 AND status NOT IN ('F')
    """, ())

    os38_pendentes = query_one("""
        SELECT COUNT(*) AS total FROM ixcprovedor.su_oss_chamado
        WHERE id_assunto=38 AND status NOT IN ('F')
    """, ())

    # === QUALIDADE VENDAS ===
    from app.dashboards.cobranca.service_qualidade import get_kpis_qualidade, get_score_vendedores
    kpis_qual = get_kpis_qualidade(mes=mes_atu)
    kpis_qual_ant = get_kpis_qualidade(mes=mes_ant)
    score_vend = get_score_vendedores(mes=mes_ant)
    score_vend_com_prej = [v for v in score_vend if v.get("prejuizo",0) > 0]
    pior_vend = max(score_vend_com_prej, key=lambda x: x.get("prejuizo",0)) if score_vend_com_prej else {}

    # === CANCELAMENTOS DO MÊS ===
    cancel = query_one(f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN motivo_cancelamento=13 THEN 1 ELSE 0 END) AS por_inad,
               SUM(valor_unitario) AS receita_perdida
        FROM ixcprovedor.cliente_contrato
        WHERE status='I'
          AND DATE_FORMAT(data_cancelamento,'%%Y-%%m')='{mes_atu}'
    """, ())

    # OPA alertas
    conn = sqlite3.connect(COMERCIAL_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    data_30 = (agora - timedelta(days=30)).strftime('%Y-%m-%d')
    cur.execute("""
        SELECT COUNT(DISTINCT canal_cliente) AS total
        FROM (
            SELECT canal_cliente, SUM(cnt) AS total_chamados
            FROM (
                SELECT canal_cliente, COUNT(*) AS cnt
                FROM opa_atendimentos
                WHERE setor IN ('Suporte','Financeiro') AND data_abertura >= ?
                GROUP BY canal_cliente, setor
            ) t GROUP BY canal_cliente
            HAVING total_chamados >= 2
        ) u
    """, (data_30,))
    row_opa = cur.fetchone()
    opa_criticos = int(row_opa["total"] if row_opa else 0)
    conn.close()

    # === RETENÇÃO ===
    from app.dashboards.cobranca.service_retencao import get_kpis_retencao
    kpis_ret = get_kpis_retencao()
    retidos_mes = local_query_one("""
        SELECT COUNT(*) AS total FROM cob_retencao_resultados
        WHERE criado_em >= date('now','start of month')
    """)
    contatos_mes = local_query_one("""
        SELECT COUNT(*) AS total FROM cob_retencao_contatos
        WHERE criado_em >= date('now','start of month')
    """)

    # Vendedores acima de 15%
    vend_problema = [v for v in score_vend if v.get("pct_inad",0) >= 15 and v.get("total",0) >= 3]

    return {
        # Saúde financeira
        "contratos":     contratos,
        "rec_mensal":    rec_mensal,
        "ticket":        ticket,
        "total_inad":    total_inad,
        "taxa_inad":     taxa_inad,
        "total_aberto":  total_aberto,
        "risco_real":    risco_real,
        "tend_inad":     tend_inad,
        # Alertas
        "nunca_pagaram": int(nunca_pagaram["total"] or 0),
        "os39_abertas":  int(os39_abertas["total"] or 0),
        "os38_pendentes":int(os38_pendentes["total"] or 0),
        "opa_criticos":  opa_criticos,
        # Qualidade vendas
        "qual_total":    kpis_qual.get("total", 0),
        "qual_inad":     kpis_qual.get("na_cobranca", 0),
        "qual_taxa":     kpis_qual.get("taxa", 0),
        "qual_prejuizo": kpis_qual.get("prejuizo_total", 0),
        "pior_vendedor": pior_vend.get("vendedor","—"),
        "pior_prejuizo": pior_vend.get("prejuizo", 0),
        "vend_problema": len(vend_problema),
        # Cancelamentos
        "cancel_total":  int(cancel["total"] or 0),
        "cancel_inad":   int(cancel["por_inad"] or 0),
        "cancel_receita":float(cancel["receita_perdida"] or 0),
        # Retenção
        "retidos_mes":   int(retidos_mes["total"] if retidos_mes else 0),
        "contatos_mes":  int(contatos_mes["total"] if contatos_mes else 0),
        "ret_total":     kpis_ret.get("total", 0),
        "ret_criticos":  kpis_ret.get("criticos", 0),
        "ret_atencao":   kpis_ret.get("atencao", 0),
        "mes_atu":       mes_atu,
        "mes_ant":       mes_ant,
        "ano_ant":       ano_ant,
        "rec_ant":       rec_ant_v,
        "contratos_ant": contratos_ant,
        "cancel_ant":    cancel_ant_v,
        "rec_var":       round((rec_mensal - rec_ant_v) / rec_ant_v * 100, 1) if rec_ant_v else 0,
        "cancel_var":    round((int(cancel["total"] or 0) - cancel_ant_v) / cancel_ant_v * 100, 1) if cancel_ant_v else 0,
        "contratos_var":   round((contratos - contratos_ant) / contratos_ant * 100, 1) if contratos_ant else 0,
        "inad_ano_atual":  int(inad_ano_atual.get("total") or 0),
        "inad_ano_atual_v": float(inad_ano_atual.get("valor") or 0),
        "inad_ano_ant_s":  int(inad_ano_ant_s.get("total") or 0),
        "inad_historico":  inad_historico,
        "inad_ant":        inad_ant_total,
        "inad_ant_aberto": inad_ant_aberto,
        "inad_var":        round((total_inad - inad_ant_total) / inad_ant_total * 100, 1) if inad_ant_total else 0,
        "cancel_inad_ant": cancel_inad_ant_v,
        "cancel_inad_var": round((int(cancel["por_inad"] or 0) - cancel_inad_ant_v) / cancel_inad_ant_v * 100, 1) if cancel_inad_ant_v else 0,
    }
