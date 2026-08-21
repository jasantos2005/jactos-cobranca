from app.core.db import query, query_one, execute
from app.core.db_local import local_query, local_query_one, local_execute
from app.core.filters import FiltrosGlobais

# ─── DEGRAU DE COBRANÇA (controle global de faixa liberada) ─────────────────
# Ordem de degraus: 120 (+90d) → 90 (61-90d) → 60 (31-60d) → 30 (1-30d)
DEGRAUS = ["120", "90", "60", "30"]

def get_degrau_liberado() -> str:
    """Retorna a faixa atualmente liberada pra fila de cobrança."""
    from app.core.db_local import local_query_one
    r = local_query_one("SELECT valor FROM cob_config WHERE chave='fila_degrau'", ())
    return r["valor"] if r else "120"

def set_degrau_liberado(degrau: str):
    """Define o degrau liberado manualmente (override admin)."""
    from app.core.db_local import local_execute as _le
    _le("""
        INSERT OR REPLACE INTO cob_config (chave, valor, atualizado_em)
        VALUES ('fila_degrau', ?, datetime('now','-3 hours'))
    """, (degrau,))

def avancar_degrau_se_vazio():
    """
    Verifica se o degrau atual está vazio (sem faturas não cobradas).
    Se estiver, avança automaticamente pro próximo degrau.
    Retorna o novo degrau se avançou, ou None se não avançou.
    """
    degrau_atual = get_degrau_liberado()
    if degrau_atual not in DEGRAUS:
        return None
    idx_atual = DEGRAUS.index(degrau_atual)
    if idx_atual == len(DEGRAUS) - 1:
        return None  # já no último degrau (1-30d), não avança mais

    # Conta quantas faturas ainda existem na faixa atual não cobradas
    filtros_check = FiltrosGlobais(faixa=degrau_atual, ocultar_cancelados=True)
    total_atual = count_fila(filtros_check)

    if total_atual == 0:
        proximo = DEGRAUS[idx_atual + 1]
        set_degrau_liberado(proximo)
        return proximo
    return None

def faixa_esta_liberada(faixa: str) -> bool:
    """
    Retorna True se a faixa solicitada está liberada pro operador.
    Admin (nivel 99) sempre tem acesso a tudo.
    Regra: a faixa está liberada se for >= ao degrau atual liberado
    (ex: se degrau=90, libera 90 e 120, bloqueia 60 e 30).
    """
    degrau = get_degrau_liberado()
    if degrau not in DEGRAUS:
        return True
    idx_degrau = DEGRAUS.index(degrau)
    # 'all' só fica disponível quando tudo estiver zerado (não implementado agora)
    if faixa == "all":
        return False  # bloqueia "Todas" pra forçar uso dos degraus
    if faixa not in DEGRAUS:
        return True
    idx_faixa = DEGRAUS.index(faixa)
    return idx_faixa <= idx_degrau  # quanto menor o índice, mais antigo = liberado

def _faixa_sql(faixa):
    return {"30":"BETWEEN 1 AND 30","60":"BETWEEN 31 AND 60","90":"BETWEEN 61 AND 90","120":"> 90","all":">= 1"}.get(faixa,">= 1")

def _ids_ja_cobrados():
    rows = local_query("SELECT DISTINCT fn_areceber_id FROM cob_interacoes WHERE resolvido=0")
    return tuple(r["fn_areceber_id"] for r in rows) if rows else (0,)

def _ids_cobrados_hoje():
    rows = local_query("SELECT DISTINCT fn_areceber_id FROM cob_interacoes WHERE date(criado_em)=date('now','localtime') AND fn_areceber_id IS NOT NULL")
    return set(r["fn_areceber_id"] for r in rows) if rows else set()

def _ids_cobrados_hoje():
    rows = local_query("SELECT DISTINCT fn_areceber_id FROM cob_interacoes WHERE date(criado_em)=date('now','localtime') AND fn_areceber_id IS NOT NULL")
    return set(r["fn_areceber_id"] for r in rows) if rows else set()

def _ids_cobrados_hoje():
    rows = local_query("SELECT DISTINCT fn_areceber_id FROM cob_interacoes WHERE date(criado_em)=date('now','localtime') AND fn_areceber_id IS NOT NULL")
    return set(r["fn_areceber_id"] for r in rows) if rows else set()

# ─── KPIs ────────────────────────────────────────────────────────────────────


def _sem_cancelados(filtros):
    return "AND (cc.status IS NULL OR cc.status = 'A')" if filtros.ocultar_cancelados else ""

def get_kpis():
    return query_one("""
        SELECT COUNT(*) AS total_faturas, SUM(f.valor_aberto) AS total_valor,
            SUM(CASE WHEN DATEDIFF(CURDATE(),f.data_vencimento) BETWEEN 1  AND 30  THEN f.valor_aberto ELSE 0 END) AS faixa_30,
            SUM(CASE WHEN DATEDIFF(CURDATE(),f.data_vencimento) BETWEEN 31 AND 60  THEN f.valor_aberto ELSE 0 END) AS faixa_60,
            SUM(CASE WHEN DATEDIFF(CURDATE(),f.data_vencimento) BETWEEN 61 AND 90  THEN f.valor_aberto ELSE 0 END) AS faixa_90,
            SUM(CASE WHEN DATEDIFF(CURDATE(),f.data_vencimento) >  90              THEN f.valor_aberto ELSE 0 END) AS faixa_120,
            COUNT(DISTINCT f.id_cliente) AS total_clientes
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
        LEFT  JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
        WHERE f.status = 'A' AND f.data_vencimento < CURDATE()
          AND c.ativo = 'S' AND (cc.status IS NULL OR cc.status = 'A')
    """)

# ─── INADIMPLÊNCIA ───────────────────────────────────────────────────────────


def get_top10_devedores():
    """Top 10 clientes com maior valor em aberto."""
    return query("""
        SELECT c.id AS id_cliente, c.razao, c.cnpj_cpf, c.fone,
               COUNT(f.id) AS qtd_faturas,
               SUM(f.valor_aberto) AS total_aberto,
               MAX(DATEDIFF(CURDATE(), f.data_vencimento)) AS maior_atraso,
               cid.nome AS cidade
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
        LEFT  JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
        LEFT  JOIN ixcprovedor.cidade cid ON cid.id = c.cidade
        WHERE f.status = 'A' AND f.data_vencimento < CURDATE()
          AND c.ativo = 'S' AND (cc.status IS NULL OR cc.status = 'A')
        GROUP BY c.id, c.razao, c.cnpj_cpf, c.fone, cid.nome
        ORDER BY total_aberto DESC LIMIT 10
    """, ())

def get_inadimplencia_por_cidade():
    """Inadimplência agrupada por cidade."""
    return query("""
        SELECT cid.nome AS cidade, cid.id AS id_cidade,
               COUNT(DISTINCT c.id) AS qtd_clientes,
               SUM(f.valor_aberto) AS total_aberto
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
        LEFT  JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
        LEFT  JOIN ixcprovedor.cidade cid ON cid.id = c.cidade
        WHERE f.status = 'A' AND f.data_vencimento < CURDATE()
          AND c.ativo = 'S' AND (cc.status IS NULL OR cc.status = 'A')
          AND cid.nome IS NOT NULL
        GROUP BY cid.id, cid.nome
        ORDER BY total_aberto DESC LIMIT 15
    """, ())

def get_clientes_por_cidade(id_cidade: int):
    """Lista clientes inadimplentes de uma cidade."""
    return query("""
        SELECT c.id AS id_cliente, c.razao, c.cnpj_cpf,
               COALESCE(c.whatsapp, c.telefone_celular, c.fone, '') AS telefone,
               COUNT(f.id) AS qtd_faturas,
               SUM(f.valor_aberto) AS total_aberto,
               MAX(DATEDIFF(CURDATE(), f.data_vencimento)) AS maior_atraso
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
        LEFT  JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
        WHERE f.status = 'A' AND f.data_vencimento < CURDATE()
          AND c.ativo = 'S' AND (cc.status IS NULL OR cc.status = 'A')
          AND c.cidade = %s
        GROUP BY c.id, c.razao, c.cnpj_cpf, c.whatsapp, c.telefone_celular, c.fone
        ORDER BY total_aberto DESC LIMIT 50
    """, (id_cidade,))

def get_inadimplentes(filtros: FiltrosGlobais):
    faixa = _faixa_sql(filtros.faixa)
    limit = int(filtros.por_pagina)
    off   = int((filtros.pagina - 1) * filtros.por_pagina)
    params = []
    busca_sql = ""
    if filtros.busca:
        busca_sql = "AND (c.razao LIKE %s OR c.cnpj_cpf LIKE %s OR c.fone LIKE %s OR c.telefone_celular LIKE %s)"
        b = f"%{filtros.busca}%"
        params += [b, b, b, b]
    sql = f"""
        SELECT c.id AS id_cliente, c.razao, c.cnpj_cpf, c.fone, c.telefone_celular,
               c.whatsapp, c.email, c.cidade, cc.id AS id_contrato, cc.contrato,
               DATE_FORMAT(cc.data_ativacao,'%%d/%%m/%%Y') AS data_ativacao,
               f.id AS id_fatura, f.documento,
               DATE_FORMAT(f.data_vencimento,'%%d/%%m/%%Y') AS data_vencimento,
               f.valor_aberto, DATEDIFF(CURDATE(), f.data_vencimento) AS dias_atraso
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente c           ON c.id  = f.id_cliente
        LEFT  JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
        WHERE f.status = 'A' AND f.data_vencimento < CURDATE()
          AND c.ativo = 'S' AND (cc.status IS NULL OR cc.status = 'A')
          AND DATEDIFF(CURDATE(), f.data_vencimento) {faixa} {busca_sql}
        ORDER BY f.valor_aberto DESC LIMIT {limit} OFFSET {off}
    """
    return query(sql, params if params else None)

def count_inadimplentes(filtros: FiltrosGlobais):
    faixa = _faixa_sql(filtros.faixa)
    params = []
    busca_sql = ""
    if filtros.busca:
        busca_sql = "AND (c.razao LIKE %s OR c.cnpj_cpf LIKE %s OR c.fone LIKE %s OR c.telefone_celular LIKE %s)"
        b = f"%{filtros.busca}%"
        params += [b, b, b, b]
    sql = f"""
        SELECT COUNT(*) AS total FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
        LEFT  JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
        WHERE f.status = 'A' AND f.data_vencimento < CURDATE()
          AND c.ativo = 'S' AND (cc.status IS NULL OR cc.status = 'A')
          AND DATEDIFF(CURDATE(), f.data_vencimento) {faixa} {busca_sql}
    """
    r = query_one(sql, params if params else None)
    return r["total"] if r else 0

# ─── FILA DE COBRANÇA ────────────────────────────────────────────────────────

def _sem_negativados():
    """Retorna cláusula SQL para excluir clientes com OS 63 (negativação) aberta."""
    return """AND f.id_cliente NOT IN (
        SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
        WHERE id_assunto=63 AND status NOT IN ('F','AN')
    )"""

def get_fila(filtros: FiltrosGlobais):
    faixa    = _faixa_sql(filtros.faixa)
    limit    = int(filtros.por_pagina)
    off      = int((filtros.pagina - 1) * filtros.por_pagina)
    excluir  = _ids_ja_cobrados()
    ph       = ",".join(["%s"] * len(excluir))
    params   = list(excluir)
    busca_sql = ""
    if filtros.busca:
        busca_sql = "AND (c.razao LIKE %s OR c.cnpj_cpf LIKE %s OR c.fone LIKE %s OR c.telefone_celular LIKE %s)"
        b = f"%{filtros.busca}%"
        params += [b, b, b, b]
    sql = f"""
        SELECT f.id AS id_fatura, f.documento, f.valor_aberto,
               DATE_FORMAT(f.data_vencimento,'%%d/%%m/%%Y') AS data_vencimento,
               DATEDIFF(CURDATE(), f.data_vencimento) AS dias_atraso,
               c.id AS id_cliente, c.razao, c.cnpj_cpf,
               COALESCE(c.whatsapp, c.telefone_celular, c.fone, '') AS telefone,
               c.email, cc.id AS id_contrato, cc.contrato
        FROM (
            SELECT f3.id_cliente, MIN(f3.id) AS id_fatura_antiga
            FROM ixcprovedor.fn_areceber f3
            INNER JOIN (
                SELECT id_cliente, MIN(data_vencimento) AS venc_min
                FROM ixcprovedor.fn_areceber
                WHERE status = 'A' AND data_vencimento < CURDATE()
                GROUP BY id_cliente
            ) m ON m.id_cliente = f3.id_cliente AND f3.data_vencimento = m.venc_min
            WHERE f3.status = 'A'
            GROUP BY f3.id_cliente
        ) fa
        INNER JOIN ixcprovedor.fn_areceber f       ON f.id  = fa.id_fatura_antiga
        INNER JOIN ixcprovedor.cliente c           ON c.id  = f.id_cliente
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
        WHERE c.ativo = 'S' AND cc.status = 'A'
          AND DATEDIFF(CURDATE(), f.data_vencimento) {faixa}
          AND f.id NOT IN ({{ph}}) {{busca_sql}} {{filtro_cc}}
        ORDER BY dias_atraso DESC LIMIT {{limit}} OFFSET {{off}}
    """.format(faixa=faixa,ph=ph,busca_sql=busca_sql,limit=limit,off=off,filtro_cc=_sem_cancelados(filtros))
    rows = query(sql, params)
    cobrados_hoje = _ids_cobrados_hoje()

    # Busca recorrentes em batch (OS 246 finalizada)
    id_clientes = list({row["id_cliente"] for row in rows})
    recorrentes_map = {}
    if id_clientes:
        ph2 = ",".join(["%s"] * len(id_clientes))
        rec = query(f"""
            SELECT id_cliente,
                   DATE_FORMAT(MAX(data_fechamento),'%%m/%%Y') AS ultima_cobranca
            FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto = 246 AND status = 'F'
              AND id_cliente IN ({ph2})
            GROUP BY id_cliente
        """, tuple(id_clientes))
        for r in rec:
            recorrentes_map[r["id_cliente"]] = r["ultima_cobranca"]

    # Busca clientes que pagaram outras faturas nos últimos 60 dias em batch
    id_clientes_fila = list({row["id_cliente"] for row in rows})
    clientes_paga_em_dia = set()
    if id_clientes_fila:
        ph4 = ",".join(["%s"] * len(id_clientes_fila))
        pagantes = query(f"""
            SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber
            WHERE status = 'R' AND baixa_data >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
              AND id_cliente IN ({ph4})
        """, tuple(id_clientes_fila))
        clientes_paga_em_dia = {r["id_cliente"] for r in pagantes}

    for row in rows:
        row["os_aberta"] = check_os_aberta(row["id_cliente"])
        row["cobrado_hoje"] = row["id_fatura"] in cobrados_hoje
        ult = recorrentes_map.get(row["id_cliente"])
        row["recorrente"] = ult is not None
        row["ultima_cobranca"] = str(ult)[:7] if ult else None
        row["paga_em_dia"] = row["id_cliente"] in clientes_paga_em_dia
    return rows

def count_fila(filtros: FiltrosGlobais):
    faixa   = _faixa_sql(filtros.faixa)
    excluir = _ids_ja_cobrados()
    ph      = ",".join(["%s"] * len(excluir))
    params  = list(excluir)
    busca_sql = ""
    if filtros.busca:
        busca_sql = "AND (c.razao LIKE %s OR c.cnpj_cpf LIKE %s OR c.fone LIKE %s OR c.telefone_celular LIKE %s)"
        b = f"%{filtros.busca}%"
        params += [b, b, b, b]
    sql = f"""
        SELECT COUNT(*) AS total
        FROM (
            SELECT f3.id_cliente, MIN(f3.id) AS id_fatura_antiga
            FROM ixcprovedor.fn_areceber f3
            INNER JOIN (
                SELECT id_cliente, MIN(data_vencimento) AS venc_min
                FROM ixcprovedor.fn_areceber
                WHERE status = 'A' AND data_vencimento < CURDATE()
                GROUP BY id_cliente
            ) m ON m.id_cliente = f3.id_cliente AND f3.data_vencimento = m.venc_min
            WHERE f3.status = 'A'
            GROUP BY f3.id_cliente
        ) fa
        INNER JOIN ixcprovedor.fn_areceber f       ON f.id  = fa.id_fatura_antiga
        INNER JOIN ixcprovedor.cliente c           ON c.id  = f.id_cliente
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
        WHERE c.ativo = 'S' AND cc.status = 'A'
          AND DATEDIFF(CURDATE(), f.data_vencimento) {faixa}
          AND f.id NOT IN ({ph}) {busca_sql}
    """
    r = query_one(sql, params)
    return r["total"] if r else 0

# ─── OS DE RETIRADA ──────────────────────────────────────────────────────────

def check_os_aberta(id_cliente: int):
    r = query_one("""
        SELECT id FROM ixcprovedor.su_oss_chamado
        WHERE id_cliente = %s AND id_assunto IN (34) AND status = 'A' LIMIT 1
    """, (id_cliente,))
    return r["id"] if r else None

def abrir_os_retirada(id_cliente: int) -> int:
    return execute("""
        INSERT INTO ixcprovedor.su_oss_chamado
            (id_cliente, id_assunto, mensagem, data_abertura, status, setor)
        VALUES (%s, 39, 'OS de retirada de equipamento — sistema de cobrança Cliquedf', NOW(), 'a', 8)
    """, (id_cliente,))

# ─── ANDAMENTO ───────────────────────────────────────────────────────────────

def get_andamento(filtros: FiltrosGlobais, usuario_id: int = None, data_inicio: str = None, data_fim: str = None):
    limit  = int(filtros.por_pagina)
    off    = int((filtros.pagina - 1) * filtros.por_pagina)
    wheres = ["i.pago = 0", "(i.resolvido IS NULL OR i.resolvido = 0)", "(i.segunda_cobranca IS NULL OR i.segunda_cobranca = 0)"]
    if usuario_id:
        wheres.append(f"i.usuario_id = {usuario_id}")
    if data_inicio:
        wheres.append(f"date(i.criado_em) >= '{data_inicio}'")
    if data_fim:
        wheres.append(f"date(i.criado_em) <= '{data_fim}'")
    where_str = " AND ".join(wheres)

    sql = f"""
        SELECT i.id, i.fn_areceber_id, i.acao, i.obs, i.pago,
               i.data_promessa,
               strftime('%d/%m/%Y %H:%M', i.criado_em) AS criado_em,
               u.nome AS operador, u.id AS usuario_id
        FROM cob_interacoes i
        LEFT JOIN cob_usuarios u ON u.id = i.usuario_id
        WHERE {where_str}
        ORDER BY i.criado_em ASC
    """
    rows = local_query(sql, ())

    fn_ids = [int(r["fn_areceber_id"]) for r in rows if r["fn_areceber_id"]]
    faturas_map = {}
    if fn_ids:
        ph = ",".join(["%s"]*len(fn_ids))
        faturas = query(f"""
            SELECT f.id, f.valor_aberto, f.documento, f.status AS fatura_status,
                   c.id AS id_cliente, c.razao, c.cnpj_cpf,
                   COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone,
                   cc.status AS contrato_status
            FROM ixcprovedor.fn_areceber f
            INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
            LEFT  JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
            WHERE f.id IN ({ph})
        """, tuple(fn_ids))
        faturas_map = {str(f["id"]): dict(f) for f in faturas}
        for fn_id, fat in faturas_map.items():
            if fat.get("fatura_status") != "A" or fat.get("contrato_status") not in ("A", None):
                local_execute("UPDATE cob_interacoes SET resolvido=1 WHERE fn_areceber_id=? AND resolvido=0", (int(fn_id),))
    # Busca clientes com OS de retirada ou cobrança (246) aberta em batch
    id_clientes_fatura = list({fat["id_cliente"] for fat in faturas_map.values() if fat.get("id_cliente")})
    clientes_com_retirada = set()
    clientes_com_os246 = set()
    if id_clientes_fatura:
        ph3 = ",".join(["%s"] * len(id_clientes_fatura))
        os_retiradas = query(f"""
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto = 39 AND status IN ('A','EN','AG','REG','RAG')
              AND id_cliente IN ({ph3})
        """, tuple(id_clientes_fatura))
        clientes_com_retirada = {r["id_cliente"] for r in os_retiradas}
        os_246 = query(f"""
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto = 246 AND status = 'A'
              AND id_cliente IN ({ph3})
        """, tuple(id_clientes_fatura))
        clientes_com_os246 = {r["id_cliente"] for r in os_246}

    # Busca clientes que pagaram outras faturas nos últimos 60 dias
    id_clientes_and = list({fat["id_cliente"] for fat in faturas_map.values() if fat.get("id_cliente")})
    clientes_paga_em_dia = set()
    if id_clientes_and:
        ph_pd = ",".join(["%s"] * len(id_clientes_and))
        pagantes_and = query(f"""
            SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber
            WHERE status = 'R' AND baixa_data >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
              AND id_cliente IN ({ph_pd})
        """, tuple(id_clientes_and))
        clientes_paga_em_dia = {r["id_cliente"] for r in pagantes_and}

    # Busca clientes recém-ativados (<=90 dias) sem 1ª parcela paga
    clientes_recem_ativados = set()
    if id_clientes_and:
        ph_ra = ",".join(["%s"] * len(id_clientes_and))
        recem = query(f"""
            SELECT DISTINCT cc.id_cliente
            FROM ixcprovedor.cliente_contrato cc
            WHERE cc.status='A'
              AND cc.id_cliente IN ({ph_ra})
              AND DATEDIFF(CURDATE(), cc.data_ativacao) <= 90
              AND cc.id_cliente NOT IN (
                SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber
                WHERE status='R'
              )
        """, tuple(id_clientes_and))
        clientes_recem_ativados = {r["id_cliente"] for r in recem}

    result = []
    for row in rows:
        row = dict(row)
        fn_id = str(row.get("fn_areceber_id") or "")
        fat = faturas_map.get(fn_id, {})
        row["fatura"] = fat
        row["paga_em_dia"]      = fat.get("id_cliente") in clientes_paga_em_dia if fat else False
        row["recem_ativado"]    = fat.get("id_cliente") in clientes_recem_ativados if fat else False
        result.append(row)
    return result


def get_operadores():
    return local_query("""
        SELECT DISTINCT u.id, u.nome
        FROM cob_interacoes i
        LEFT JOIN cob_usuarios u ON u.id = i.usuario_id
        WHERE i.pago = 0 AND (i.resolvido IS NULL OR i.resolvido = 0)
          AND u.id IS NOT NULL
        ORDER BY u.nome
    """, ())

def count_andamento(usuario_id: int = None, data_inicio: str = None, data_fim: str = None):
    wheres = ["pago=0", "(resolvido IS NULL OR resolvido=0)", "(segunda_cobranca IS NULL OR segunda_cobranca=0)"]
    if usuario_id:
        wheres.append(f"usuario_id={usuario_id}")
    if data_inicio:
        wheres.append(f"date(criado_em) >= '{data_inicio}'")
    if data_fim:
        wheres.append(f"date(criado_em) <= '{data_fim}'")
    where_str = " AND ".join(wheres)
    r = local_query_one(f"SELECT COUNT(*) AS total FROM cob_interacoes WHERE {where_str}")
    return r["total"] if r else 0

def atualizar_interacao(interacao_id: int, acao: str, obs: str, pago: int, data_promessa: str = None):
    local_execute(
        "UPDATE cob_interacoes SET acao=?, obs=?, pago=?, data_promessa=? WHERE id=?",
        (acao, obs, pago, data_promessa, interacao_id)
    )

# ─── PROMESSAS QUEBRADAS ─────────────────────────────────────────────────────

def detectar_promessas_quebradas():
    """Varre interacoes com data_promessa vencida e status ainda aberto no IXC."""
    from datetime import date, datetime
    hoje = date.today().isoformat()
    ontem = (date.today() - __import__('datetime').timedelta(days=1)).isoformat()
    # Detecta promessas vencidas até ONTEM (não hoje — cliente ainda tem o dia todo)
    pendentes = local_query("""
        SELECT i.id, i.fn_areceber_id, i.usuario_id, i.data_promessa
        FROM cob_interacoes i
        WHERE i.data_promessa IS NOT NULL
          AND i.data_promessa <= ?
          AND i.pago = 0
          AND (i.resolvido IS NULL OR i.resolvido = 0)
          AND i.id NOT IN (SELECT interacao_id FROM cob_promessas_quebradas WHERE resolvido=0)
    """, (ontem,))
    inseridas = 0
    for p in pendentes:
        status = query_one("SELECT status FROM ixcprovedor.fn_areceber WHERE id=%s", (p["fn_areceber_id"],))
        if status and status["status"] == "A":
            local_execute("""
                INSERT INTO cob_promessas_quebradas (interacao_id, fn_areceber_id, usuario_id, data_promessa)
                VALUES (?,?,?,?)
            """, (p["id"], p["fn_areceber_id"], p["usuario_id"], p["data_promessa"]))
            inseridas += 1

            # Alerta Telegram: promessa quebrada
            try:
                import requests
                fat = query_one("""
                    SELECT c.razao, f.valor_aberto
                    FROM ixcprovedor.fn_areceber f
                    INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
                    WHERE f.id = %s
                """, (p["fn_areceber_id"],))
                oper = local_query_one("SELECT nome FROM cob_usuarios WHERE id=?", (p["usuario_id"],))
                if fat and oper:
                    try:
                        dprom_fmt = datetime.strptime(str(p["data_promessa"])[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
                    except Exception:
                        dprom_fmt = p["data_promessa"]
                    from datetime import date as _date
                    hoje_fmt = _date.today().strftime("%d/%m/%Y")
                    msg = (
                        "⚠️ <b>PROMESSA QUEBRADA ONTEM</b>\n"
                        f"👤 <b>{fat['razao']}</b>\n"
                        f"💰 R$ {float(fat['valor_aberto'] or 0):.2f} em aberto\n"
                        f"📅 Prometeu pagar até: {dprom_fmt} (quebrada ontem)\n"
                        f"🙋 Cobrado por: <b>{oper['nome']}</b>\n"
                        f"📞 Por favor, <b>{oper['nome']}</b>, entre em contato com o cliente hoje ({hoje_fmt})."
                    )
                    requests.post(
                        "https://api.telegram.org/bot8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY/sendMessage",
                        data={"chat_id": "-4989557189", "text": msg, "parse_mode": "HTML"},
                        timeout=10,
                    )
            except Exception:
                pass
    return inseridas

def get_promessas_quebradas(usuario_id: int = None, filtros: FiltrosGlobais = None, data_ini: str = None, data_fim: str = None):
    limit = int(filtros.por_pagina) if filtros else 50
    off   = int((filtros.pagina - 1) * filtros.por_pagina) if filtros else 0
    extra = "AND pq.usuario_id = ?" if usuario_id else ""
    params = [usuario_id] if usuario_id else []
    if data_ini:
        extra += " AND date(pq.detectado_em) >= ?"
        params.append(data_ini)
    if data_fim:
        extra += " AND date(pq.detectado_em) <= ?"
        params.append(data_fim)
    rows = local_query(f"""
        SELECT pq.id, pq.fn_areceber_id, pq.data_promessa,
               strftime('%d/%m/%Y', pq.detectado_em) AS detectado_em,
               pq.resolvido, pq.interacao_id,
               i.acao AS acao_original, i.obs AS obs_original,
               u.nome AS operador, u.id AS usuario_id
        FROM cob_promessas_quebradas pq
        LEFT JOIN cob_interacoes i ON i.id = pq.interacao_id
        LEFT JOIN cob_usuarios u   ON u.id = pq.usuario_id
        WHERE pq.resolvido = 0 {extra}
        ORDER BY pq.detectado_em DESC
        LIMIT {limit} OFFSET {off}
    """, tuple(params))
    for row in rows:
        fatura = query_one("""
            SELECT f.id, f.documento, f.valor_aberto,
                   DATE_FORMAT(f.data_vencimento,'%%d/%%m/%%Y') AS data_vencimento,
                   c.id AS id_cliente, c.razao,
                   COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone
            FROM ixcprovedor.fn_areceber f
            INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
            WHERE f.id = %s
        """, (row["fn_areceber_id"],))
        row["fatura"] = fatura or {}
    return rows

def count_promessas_quebradas(usuario_id: int = None):
    if usuario_id:
        r = local_query_one("SELECT COUNT(*) AS total FROM cob_promessas_quebradas WHERE resolvido=0 AND usuario_id=?", (usuario_id,))
    else:
        r = local_query_one("SELECT COUNT(*) AS total FROM cob_promessas_quebradas WHERE resolvido=0")
    return r["total"] if r else 0

def resolver_promessa_quebrada(pq_id: int):
    from datetime import datetime, timezone, timedelta as _td
    _tz_br = timezone(_td(hours=-3))
    _agora = datetime.now(_tz_br).strftime('%Y-%m-%d %H:%M:%S')
    local_execute("UPDATE cob_promessas_quebradas SET resolvido=1, resolvido_em=? WHERE id=?", (_agora, pq_id))


def resolver_interacoes_pagas():
    """Marca como resolvidas interacoes cujas faturas foram pagas no IXC."""
    from datetime import datetime
    pendentes = local_query("""
        SELECT DISTINCT fn_areceber_id FROM cob_interacoes
        WHERE pago = 0 AND (resolvido IS NULL OR resolvido = 0)
        AND fn_areceber_id IS NOT NULL
    """, ())
    if not pendentes:
        return 0

    fn_ids = tuple(int(r["fn_areceber_id"]) for r in pendentes if r["fn_areceber_id"])
    if not fn_ids:
        return 0

    ph = ",".join(["%s"]*len(fn_ids))
    pagas = query(f"""
        SELECT id FROM ixcprovedor.fn_areceber
        WHERE id IN ({ph}) AND status = 'R'
    """, fn_ids)

    if not pagas:
        return 0

    resolvidos = 0
    for f in pagas:
        fn_id = f["id"]

        # Antes de marcar como resolvido, verifica se havia promessa de
        # pagamento em aberto para esta fatura (para alertar cumprimento)
        try:
            promessa = local_query_one("""
                SELECT id, usuario_id, data_promessa
                FROM cob_interacoes
                WHERE fn_areceber_id=? AND pago=0 AND data_promessa IS NOT NULL
                ORDER BY criado_em DESC LIMIT 1
            """, (fn_id,))
        except Exception:
            promessa = None

        local_execute("""
            UPDATE cob_interacoes
            SET pago=1, resolvido=1
            WHERE fn_areceber_id=? AND pago=0
        """, (fn_id,))
        # Resolve também em cob_promessas_quebradas se existir
        local_execute("""
            UPDATE cob_promessas_quebradas SET resolvido=1, resolvido_em=datetime('now','-3 hours')
            WHERE fn_areceber_id=? AND resolvido=0
        """, (fn_id,))
        resolvidos += 1

        # Fecha a OS 246 (cobrança) do cliente, identificando qual fatura foi paga
        try:
            fat_cli = query_one("SELECT id_cliente FROM ixcprovedor.fn_areceber WHERE id=%s", (fn_id,))
            if fat_cli:
                os_aberta_pg = query_one("""
                    SELECT id, mensagem FROM ixcprovedor.su_oss_chamado
                    WHERE id_cliente=%s AND id_assunto=190 AND status='A' LIMIT 1
                """, (fat_cli["id_cliente"],))
                if os_aberta_pg:
                    msg_atual_pg = os_aberta_pg["mensagem"] or ""
                    nova_msg_pg = msg_atual_pg + f"\n{'='*35}\n✅ FATURA #{fn_id} PAGA — cobrança encerrada.\n{'='*35}"
                    execute("""
                        UPDATE ixcprovedor.su_oss_chamado
                        SET status='F', data_fechamento=NOW(), mensagem=%s
                        WHERE id=%s
                    """, (nova_msg_pg, os_aberta_pg["id"]))
        except Exception as ex:
            print(f"Erro ao fechar OS 246 (fatura {fn_id} paga): {ex}")

        if promessa:
            try:
                import requests
                fat = query_one("""
                    SELECT c.razao, f.valor
                    FROM ixcprovedor.fn_areceber f
                    INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
                    WHERE f.id = %s
                """, (fn_id,))
                oper = local_query_one("SELECT nome FROM cob_usuarios WHERE id=?", (promessa["usuario_id"],))

                try:
                    local_execute("""
                        INSERT INTO cob_promessas_cumpridas
                            (interacao_id, fn_areceber_id, usuario_id, data_promessa, valor_pago)
                        VALUES (?,?,?,?,?)
                    """, (
                        promessa["id"], fn_id, promessa["usuario_id"], promessa["data_promessa"],
                        float(fat["valor"]) if fat and fat.get("valor") is not None else None,
                    ))
                except Exception:
                    pass
                if fat and oper:
                    try:
                        dprom_fmt = datetime.strptime(str(promessa["data_promessa"])[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
                    except Exception:
                        dprom_fmt = promessa["data_promessa"]
                    msg = (
                        "✅ <b>PROMESSA CUMPRIDA</b>\n"
                        f"🙋 Cobrado por: <b>{oper['nome']}</b>\n"
                        f"👤 {fat['razao']} prometeu pagar até {dprom_fmt}\n"
                        "💵 Pagamento da fatura confirmado."
                    )
                    requests.post(
                        "https://api.telegram.org/bot8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY/sendMessage",
                        data={"chat_id": "-4989557189", "text": msg, "parse_mode": "HTML"},
                        timeout=10,
                    )
            except Exception:
                pass

    return resolvidos


def get_promessas_realizadas(usuario_id: int = None, filtros: FiltrosGlobais = None, data_ini: str = None, data_fim: str = None):
    """Promessas registradas, aguardando o prazo — ainda nao quebraram nem foram pagas."""
    limit = int(filtros.por_pagina) if filtros else 50
    off   = int((filtros.pagina - 1) * filtros.por_pagina) if filtros else 0
    wheres, params = [], []
    if usuario_id:
        wheres.append("i.usuario_id = ?"); params.append(usuario_id)
    if data_ini:
        wheres.append("substr(i.criado_em,1,10) >= ?"); params.append(data_ini)
    if data_fim:
        wheres.append("substr(i.criado_em,1,10) <= ?"); params.append(data_fim)
    extra = (" AND " + " AND ".join(wheres)) if wheres else ""
    rows = local_query(f"""
        SELECT i.id, i.fn_areceber_id, i.data_promessa,
               strftime('%d/%m/%Y %H:%M', i.criado_em) AS criado_em,
               u.nome AS operador, u.id AS usuario_id
        FROM cob_interacoes i
        LEFT JOIN cob_usuarios u ON u.id = i.usuario_id
        WHERE i.data_promessa IS NOT NULL
          AND i.pago = 0
          AND (i.resolvido IS NULL OR i.resolvido = 0)
          AND i.id NOT IN (SELECT interacao_id FROM cob_promessas_quebradas)
          {extra}
        ORDER BY i.data_promessa ASC
        LIMIT {limit} OFFSET {off}
    """, tuple(params))
    for row in rows:
        fatura = query_one("""
            SELECT f.id, f.documento, f.valor_aberto,
                   DATE_FORMAT(f.data_vencimento,'%%d/%%m/%%Y') AS data_vencimento,
                   c.id AS id_cliente, c.razao,
                   COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone
            FROM ixcprovedor.fn_areceber f
            INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
            WHERE f.id = %s
        """, (row["fn_areceber_id"],))
        row["fatura"] = fatura or {}
    return rows

def count_promessas_realizadas(usuario_id: int = None, data_ini: str = None, data_fim: str = None):
    wheres, params = [], []
    if usuario_id:
        wheres.append("i.usuario_id = ?"); params.append(usuario_id)
    if data_ini:
        wheres.append("substr(i.criado_em,1,10) >= ?"); params.append(data_ini)
    if data_fim:
        wheres.append("substr(i.criado_em,1,10) <= ?"); params.append(data_fim)
    extra = (" AND " + " AND ".join(wheres)) if wheres else ""
    r = local_query_one(f"""
        SELECT COUNT(*) AS total
        FROM cob_interacoes i
        WHERE i.data_promessa IS NOT NULL
          AND i.pago = 0
          AND (i.resolvido IS NULL OR i.resolvido = 0)
          AND i.id NOT IN (SELECT interacao_id FROM cob_promessas_quebradas)
          {extra}
    """, tuple(params))
    return r["total"] if r else 0

def get_promessas_cumpridas(usuario_id: int = None, filtros: FiltrosGlobais = None):
    limit = int(filtros.por_pagina) if filtros else 50
    off   = int((filtros.pagina - 1) * filtros.por_pagina) if filtros else 0
    extra = "AND pc.usuario_id = ?" if usuario_id else ""
    params = (usuario_id,) if usuario_id else ()
    rows = local_query(f"""
        SELECT pc.id, pc.fn_areceber_id, pc.data_promessa, pc.valor_pago,
               strftime('%d/%m/%Y %H:%M', pc.cumprido_em) AS cumprido_em,
               u.nome AS operador, u.id AS usuario_id
        FROM cob_promessas_cumpridas pc
        LEFT JOIN cob_usuarios u ON u.id = pc.usuario_id
        WHERE 1=1 {extra}
        ORDER BY pc.cumprido_em DESC
        LIMIT {limit} OFFSET {off}
    """, params if params else ())
    for row in rows:
        fatura = query_one("""
            SELECT f.id, f.documento,
                   DATE_FORMAT(f.data_vencimento,'%%d/%%m/%%Y') AS data_vencimento,
                   c.id AS id_cliente, c.razao,
                   COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone
            FROM ixcprovedor.fn_areceber f
            INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
            WHERE f.id = %s
        """, (row["fn_areceber_id"],))
        row["fatura"] = fatura or {}
    return rows

def count_promessas_cumpridas(usuario_id: int = None):
    if usuario_id:
        r = local_query_one("SELECT COUNT(*) AS total FROM cob_promessas_cumpridas WHERE usuario_id=?", (usuario_id,))
    else:
        r = local_query_one("SELECT COUNT(*) AS total FROM cob_promessas_cumpridas")
    return r["total"] if r else 0

# ─── PAGOS ───────────────────────────────────────────────────────────────────

def get_pagos(filtros: FiltrosGlobais, usuario_id: int = None):
    limit = int(filtros.por_pagina)
    off   = int((filtros.pagina - 1) * filtros.por_pagina)
    uid_filter = f"AND usuario_id = {usuario_id}" if usuario_id else ""
    interagidos = local_query(f"SELECT DISTINCT fn_areceber_id FROM cob_interacoes WHERE fn_areceber_id IS NOT NULL {uid_filter}", ())
    if not interagidos:
        return []
    fn_ids = tuple(int(r["fn_areceber_id"]) for r in interagidos if r["fn_areceber_id"])
    if not fn_ids:
        return []
    ph = ",".join(["%s"]*len(fn_ids))
    params = fn_ids + (limit, off)
    rows = query(f"""
        SELECT f.id AS id_fatura, f.documento,
               DATE_FORMAT(f.data_vencimento,'%%d/%%m/%%Y') AS data_vencimento,
               DATE_FORMAT(f.baixa_data,'%%d/%%m/%%Y')      AS data_pagamento,
               f.valor_recebido, c.id AS id_cliente, c.razao, c.cnpj_cpf
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
        WHERE f.status = 'R' AND f.id IN ({ph})
        ORDER BY f.baixa_data DESC LIMIT %s OFFSET %s
    """, params)
    for row in rows:
        inter = local_query_one("""
            SELECT i.acao, u.nome AS operador FROM cob_interacoes i
            LEFT JOIN cob_usuarios u ON u.id = i.usuario_id
            WHERE i.fn_areceber_id=? ORDER BY i.criado_em DESC LIMIT 1
        """, (row["id_fatura"],))
        row["operador"] = inter["operador"] if inter else "—"
        row["acao"]     = inter["acao"] if inter else "—"
    return rows


def get_ixc_login(usuario_id: int) -> int:
    """Retorna o id_login do IXC para o usuário do sistema."""
    r = local_query_one("SELECT ixc_login_id FROM cob_ixc_usuarios WHERE usuario_id=?", (usuario_id,))
    return r["ixc_login_id"] if r else 0

def get_id_cidade_cliente(id_cliente: int) -> int:
    """Retorna o id da cidade do cliente no IXC."""
    r = query_one("SELECT cidade FROM ixcprovedor.cliente WHERE id=%s", (id_cliente,))
    return int(r["cidade"]) if r and r["cidade"] else 0

def get_operadores_pagos():
    """Retorna operadores que têm registros pagos."""
    return local_query("""
        SELECT DISTINCT u.id, u.nome
        FROM cob_interacoes i
        LEFT JOIN cob_usuarios u ON u.id = i.usuario_id
        WHERE i.fn_areceber_id IS NOT NULL AND u.id IS NOT NULL
        ORDER BY u.nome
    """, ())

def count_pagos(usuario_id: int = None):
    uid_filter = f"AND usuario_id = {usuario_id}" if usuario_id else ""
    interagidos = local_query(f"SELECT DISTINCT fn_areceber_id FROM cob_interacoes WHERE fn_areceber_id IS NOT NULL {uid_filter}", ())
    if not interagidos:
        return 0
    fn_ids = tuple(int(r["fn_areceber_id"]) for r in interagidos if r["fn_areceber_id"])
    if not fn_ids:
        return 0
    ph = ",".join(["%s"]*len(fn_ids))
    r = query_one(f"SELECT COUNT(*) AS total FROM ixcprovedor.fn_areceber WHERE status='R' AND id IN ({ph})", fn_ids)
    return r["total"] if r else 0


def get_cliente(id_cliente: int):
    return query_one(
        """SELECT c.id, c.razao, c.cnpj_cpf, c.fone, c.telefone_comercial, c.telefone_celular, c.whatsapp,
                  c.email, c.endereco, c.numero, c.bairro,
                  COALESCE(cid.nome, c.cidade) AS cidade,
                  COALESCE(u.sigla, c.uf) AS uf,
                  c.ativo, c.status_internet
           FROM ixcprovedor.cliente c
           LEFT JOIN ixcprovedor.cidade cid ON cid.id = c.cidade
           LEFT JOIN ixcprovedor.uf u ON u.id = c.uf
           WHERE c.id=%s""",
        (id_cliente,)
    )

def get_faturas_cliente(id_cliente: int):
    return query("""
        SELECT f.id, f.documento, f.id_contrato,
               DATE_FORMAT(f.data_vencimento,'%%d/%%m/%%Y') AS data_vencimento,
               f.valor_aberto, DATEDIFF(CURDATE(), f.data_vencimento) AS dias_atraso, f.status
        FROM ixcprovedor.fn_areceber f
        WHERE f.id_cliente = %s AND f.status = 'A' AND f.data_vencimento < CURDATE()
        ORDER BY f.data_vencimento ASC
    """, (id_cliente,))

OS_ASSUNTOS = {6:"RECOLHER ONU E PTO",22:"RECOLHIMENTO DE EQUIPAMENTO",23:"DEVOLUÇÃO DE EQUIPAMENTOS",28:"INSTALAR EQUIPAMENTO DE TESTE",29:"RECOLHER EQUIPAMENTO DE TESTE",31:"SOLICITAÇÃO DE CANCELAMENTO",32:"[FINANCEIRO]NEGOCIAÇÃO",33:"[COMERCIAL]DEVOLUÇÃO DE EQUIPAMENTO",37:"[COMERCIAL]RECEBER EQUIPAMENTO EM LOJA",38:"DEVOLUÇÃO DE EQUIPAMENTOS",39:"RETIRADA DE EQUIPAMENTO",40:"RETIRADA DA FIBRA NA CTO",63:"CANCELAR CONTRATO POR DESISTENCIA DE INSTALAÇÃO",73:"GERAR COBRANÇA",74:"ABRIR PROCESSO DE RECOLHIMENTO",75:"REATIVAÇÃO - NOVO CONTRATO",80:"COBRANÇA - PRIMEIRA TENTATIVA",81:"ACORDO REALIZADO",82:"ACORDO NÃO REALIZADO",83:"COBRANÇA - SEGUNDA TENTATIVA",84:"CANCELAMENTO DE CONTRATO POR INADIMPLENCIA",85:"CLIENTE RETIDO",86:"CLIENTE NÃO RETIDO",87:"DEVOLUÇÃO DE EQUIPAMENTO NA LOJA",89:"RETIRAR FIBRA",100:"ACORDO COM O TECNICO",109:"CANCELAMENTO DE CONTRATO E FINANCEIRO",112:"RECOLHER/DEVOLUÇÃO",126:"CANCELAMENTO ITTV",127:"RECOLHER EQUIPAMENTO (ITTV)",128:"DESATIVAR LOGIN E REFAZER FINANCEIRO (ITTV)",129:"AUDITORIA (ITTV)",139:"SPC",205:"SOLICITAÇÃO DE SUSPENSÃO TEMPORÁRIA",206:"REALIZAR SUSPENSÃO TEMPORÁRIA",224:"CANCELAR CONTRATO POR DESISTENCIA DE REATIVAÇÃO",246:"COBRANÇA EM ANDAMENTO"}

def get_os_cliente(id_cliente: int):
    rows = query("""
        SELECT o.id, o.protocolo, o.id_assunto,
               DATE_FORMAT(o.data_abertura,'%%d/%%m/%%Y') AS data_abertura,
               DATE_FORMAT(o.data_fechamento,'%%d/%%m/%%Y') AS data_fechamento,
               o.status, o.mensagem
        FROM ixcprovedor.su_oss_chamado o
        WHERE o.id_cliente = %s AND o.id_assunto IN (6,22,23,28,29,31,32,33,37,38,39,40,63,73,74,75,80,81,82,83,84,85,86,87,89,100,109,112,126,127,128,129,139,205,206,224,246)
        ORDER BY o.data_abertura DESC LIMIT 20
    """, (id_cliente,))
    result = []
    for r in rows:
        d = dict(r)
        d['assunto'] = OS_ASSUNTOS.get(d.get('id_assunto'), f"OS #{d.get('id_assunto')}")
        result.append(d)
    return result

def get_interacoes_cliente(id_cliente: int):
    faturas = query("SELECT id FROM ixcprovedor.fn_areceber WHERE id_cliente = %s", (id_cliente,))
    if not faturas:
        return []
    ids = tuple(f["id"] for f in faturas)
    ph  = ",".join("?" * len(ids))
    return local_query(f"""
        SELECT i.id, i.acao, i.obs, i.pago, i.data_promessa,
               strftime('%d/%m/%Y %H:%M', i.criado_em) AS criado_em,
               u.nome AS operador
        FROM cob_interacoes i
        LEFT JOIN cob_usuarios u ON u.id = i.usuario_id
        WHERE i.fn_areceber_id IN ({ph})
        ORDER BY i.criado_em ASC
    """, ids)

def registrar_interacao(fn_areceber_id: int, usuario_id: int, acao: str, obs: str, pago: int, data_promessa: str = None, segunda_cobranca: int = 0):
    from datetime import datetime, timezone, timedelta
    tz_br = timezone(timedelta(hours=-3))
    agora = datetime.now(tz_br).strftime('%Y-%m-%d %H:%M:%S')
    # Se ja vem marcado como pago, fecha a interacao na hora (evita
    # registros presos com pago=1 e resolvido=0 para sempre)
    resolvido = 1 if pago == 1 else 0
    return local_execute(
        "INSERT INTO cob_interacoes (fn_areceber_id, usuario_id, acao, obs, pago, data_promessa, criado_em, segunda_cobranca, resolvido) VALUES (?,?,?,?,?,?,?,?,?)",
        (fn_areceber_id, usuario_id, acao, obs, pago, data_promessa, agora, segunda_cobranca, resolvido)
    )

# ─── DESEMPENHO OPERADOR ─────────────────────────────────────────────────────

def get_desempenho_operador(usuario_id: int, data_ini: str = None, data_fim: str = None):
    filtro_data = ""
    params = [usuario_id]
    if data_ini:
        filtro_data += " AND date(i.criado_em) >= ?"
        params.append(data_ini)
    if data_fim:
        filtro_data += " AND date(i.criado_em) <= ?"
        params.append(data_fim)

    total = local_query_one(f"""
        SELECT COUNT(*) AS cobrancas,
               SUM(CASE WHEN data_promessa IS NOT NULL THEN 1 ELSE 0 END) AS promessas
        FROM cob_interacoes i
        WHERE i.usuario_id=? {filtro_data}
    """, tuple(params))

    promessas_quebradas = local_query_one(f"""
        SELECT COUNT(*) AS total FROM cob_promessas_quebradas pq
        JOIN cob_interacoes i ON i.id = pq.interacao_id
        WHERE pq.usuario_id=? {filtro_data}
    """, tuple(params))

    # Faturas cobradas pelo operador no periodo
    ids_interagidos = local_query(f"""
        SELECT DISTINCT fn_areceber_id FROM cob_interacoes i
        WHERE i.usuario_id=? {filtro_data}
    """, tuple(params))

    valor_recuperado = 0.0
    pagos_reais = 0
    if ids_interagidos:
        fn_ids = tuple(r["fn_areceber_id"] for r in ids_interagidos if r["fn_areceber_id"])
        if fn_ids:
            ph = ",".join(["%s"] * len(fn_ids))
            vr = query_one(f"""
                SELECT SUM(valor_recebido) AS total, COUNT(*) AS qtd
                FROM ixcprovedor.fn_areceber
                WHERE id IN ({ph}) AND status='R'
            """, fn_ids)
            valor_recuperado = float(vr["total"] or 0) if vr else 0.0
            pagos_reais = int(vr["qtd"] or 0) if vr else 0

    cobrancas  = total["cobrancas"] or 0 if total else 0
    pagos      = pagos_reais
    eficiencia = round((pagos / cobrancas * 100), 1) if cobrancas > 0 else 0

    return {
        "cobrancas":            cobrancas,
        "pagos_diretos":        pagos,
        "promessas":            total["promessas"] or 0 if total else 0,
        "promessas_quebradas":  promessas_quebradas["total"] if promessas_quebradas else 0,
        "valor_recuperado":     valor_recuperado,
        "eficiencia":           eficiencia,
    }


def get_historico_operador(usuario_id: int, data_ini: str = None, data_fim: str = None, limit: int = 100):
    filtro_data = ""
    params = [usuario_id]
    if data_ini:
        filtro_data += " AND date(i.criado_em) >= ?"
        params.append(data_ini)
    if data_fim:
        filtro_data += " AND date(i.criado_em) <= ?"
        params.append(data_fim)
    rows = local_query(f"""
        SELECT i.id, i.fn_areceber_id, i.acao, i.obs, i.pago, i.data_promessa,
               strftime('%d/%m/%Y %H:%M', i.criado_em) AS criado_em
        FROM cob_interacoes i
        WHERE i.usuario_id=? {filtro_data}
        ORDER BY i.criado_em DESC
        LIMIT 100
    """, tuple(params))
    if not rows:
        return []
    # Busca todas as faturas de uma vez (evita N+1)
    fn_ids = [r["fn_areceber_id"] for r in rows if r["fn_areceber_id"]]
    faturas_map = {}
    if fn_ids:
        ph = ",".join(["%s"]*len(fn_ids))
        faturas = query(f"""
            SELECT f.id, c.razao, f.documento, f.valor_aberto, f.valor_recebido, f.status,
                   DATE_FORMAT(f.data_vencimento,'%%d/%%m/%%Y') AS data_vencimento
            FROM ixcprovedor.fn_areceber f
            JOIN ixcprovedor.cliente c ON c.id=f.id_cliente
            WHERE f.id IN ({ph})
        """, tuple(fn_ids))
        faturas_map = {str(f["id"]): dict(f) for f in faturas}
    for row in rows:
        row["fatura"] = faturas_map.get(str(row["fn_areceber_id"]), {})
    return rows

def get_desempenho_equipe(data_ini: str = None, data_fim: str = None):
    operadores = local_query("SELECT id, nome, setor, nivel FROM cob_usuarios WHERE ativo=1 AND aprovado=1 AND nivel < 99")
    resultado = []
    for op in operadores:
        d = get_desempenho_operador(op["id"], data_ini, data_fim)
        d["id"]    = op["id"]
        d["nome"]  = op["nome"]
        d["setor"] = op["setor"]
        d["nivel"] = op["nivel"]
        resultado.append(d)
    resultado = [d for d in resultado if d["cobrancas"] > 0]
    resultado.sort(key=lambda x: x["valor_recuperado"], reverse=True)
    return resultado

# ─── GRÁFICO ─────────────────────────────────────────────────────────────────

def get_evolucao_diaria():
    return query("""
        SELECT DATE_FORMAT(f.data_vencimento,'%%d/%%m') AS dia,
               COUNT(*) AS qtd, SUM(f.valor_aberto) AS valor
        FROM ixcprovedor.fn_areceber f
        WHERE f.status='A'
          AND f.data_vencimento BETWEEN DATE_SUB(CURDATE(),INTERVAL 30 DAY) AND CURDATE()
        GROUP BY f.data_vencimento ORDER BY f.data_vencimento ASC
    """)


# ── SEGUNDA COBRANÇA ─────────────────────────────────────────────────────────
def get_segunda_cobranca(usuario_id: int = None, data_inicio: str = None, data_fim: str = None, pagina: int = 1, por_pagina: int = 30):
    limit = int(por_pagina)
    off   = int((pagina - 1) * por_pagina)
    wheres = ["i.segunda_cobranca = 1", "i.pago = 0", "(i.resolvido IS NULL OR i.resolvido = 0)"]
    if usuario_id:
        wheres.append(f"i.usuario_id = {usuario_id}")
    if data_inicio:
        wheres.append(f"date(i.criado_em) >= '{data_inicio}'")
    if data_fim:
        wheres.append(f"date(i.criado_em) <= '{data_fim}'")
    where_str = " AND ".join(wheres)
    # Busca apenas a última interação por fn_areceber_id (evita duplicatas)
    sql = f"""
        SELECT i.id, i.fn_areceber_id, i.acao, i.obs, i.pago,
               i.data_promessa,
               strftime('%d/%m/%Y %H:%M', i.criado_em) AS criado_em,
               u.nome AS operador, u.id AS usuario_id
        FROM cob_interacoes i
        LEFT JOIN cob_usuarios u ON u.id = i.usuario_id
        WHERE {where_str}
          AND i.id = (
            SELECT MAX(i2.id) FROM cob_interacoes i2
            WHERE i2.fn_areceber_id = i.fn_areceber_id
              AND i2.segunda_cobranca = 1
              AND i2.pago = 0
              AND (i2.resolvido IS NULL OR i2.resolvido = 0)
          )
        ORDER BY i.criado_em DESC
    """
    rows = local_query(sql, ())
    fn_ids = [int(r["fn_areceber_id"]) for r in rows if r["fn_areceber_id"]]
    faturas_map = {}
    if fn_ids:
        ph = ",".join(["%s"]*len(fn_ids))
        faturas = query(f"""
            SELECT f.id, f.valor_aberto, f.documento, f.status AS fatura_status,
                   c.id AS id_cliente, c.razao, c.cnpj_cpf,
                   COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone,
                   cc.status AS contrato_status
            FROM ixcprovedor.fn_areceber f
            INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
            LEFT  JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
            WHERE f.id IN ({ph})
        """, tuple(fn_ids))
        faturas_map = {str(f["id"]): dict(f) for f in faturas}

    # Agrupa por id_cliente — mantém apenas a última interação por cliente
    clientes_vistos = {}
    rows_filtrados = []
    for r in rows:
        fat = faturas_map.get(str(r["fn_areceber_id"]), {})
        id_cli = fat.get("id_cliente")
        if id_cli and id_cli in clientes_vistos:
            continue
        if id_cli:
            clientes_vistos[id_cli] = True
        rows_filtrados.append(r)
    rows = rows_filtrados
    # Paginação após agrupamento
    rows = rows[off:off+limit]


    # Busca maior atraso por cliente em batch
    id_clis = list({f["id_cliente"] for f in faturas_map.values() if f.get("id_cliente")})
    if id_clis:
        ph2 = ",".join(["%s"]*len(id_clis))
        atrasos = query(f"""SELECT id_cliente, MAX(DATEDIFF(CURDATE(), data_vencimento)) AS maior_atraso FROM ixcprovedor.fn_areceber WHERE status='A' AND data_vencimento < CURDATE() AND id_cliente IN ({ph2}) GROUP BY id_cliente""", tuple(id_clis))
        atraso_map = {r["id_cliente"]: int(r["maior_atraso"] or 0) for r in atrasos}
        for fat in faturas_map.values():
            fat["maior_atraso"] = atraso_map.get(fat.get("id_cliente"), 0)

        # NOTA: marcacao de resolvido movida para job separado (nao roda mais durante o GET da tela)
        # Ver: scripts/cron_marcar_resolvidos_segunda.py

    # Busca clientes que ja tem OS de retirada em andamento (nao finalizada)
    id_clientes_check = list({fat.get("id_cliente") for fat in faturas_map.values() if fat.get("id_cliente")})
    clientes_com_os39 = set()
    if id_clientes_check:
        ph3 = ",".join(["%s"]*len(id_clientes_check))
        os39 = query(f"""
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto = 39 AND status != 'F' AND id_cliente IN ({ph3})
        """, tuple(id_clientes_check))
        clientes_com_os39 = {r["id_cliente"] for r in os39}

    result = []
    for row in rows:
        row = dict(row)
        fn_id = str(row.get("fn_areceber_id") or "")
        fat = faturas_map.get(fn_id, {})
        # Pula interações de faturas inválidas
        if fn_id and fat and (fat.get("fatura_status") != "A" or fat.get("contrato_status") not in ("A", None)):
            continue
        if fat and fat.get("id_cliente") in clientes_com_os39:
            continue
        atraso = int(fat.get("maior_atraso") or 0) if fat else 0
        faltam = max(0, 45 - atraso)
        row["dias_atraso"] = atraso
        row["faltam_retirada"] = faltam
        row["retirada_iminente"] = faltam <= 10
        row["fatura"] = fat
        result.append(row)

    # Ordena por urgencia de retirada: quem tem menos dias sobrando ate os 60d fica no topo
    result.sort(key=lambda r: r["faltam_retirada"])
    return result

def count_segunda_cobranca(usuario_id: int = None, data_inicio: str = None, data_fim: str = None):
    wheres = ["segunda_cobranca=1", "pago=0", "(resolvido IS NULL OR resolvido=0)"]
    if usuario_id:
        wheres.append(f"usuario_id={usuario_id}")
    if data_inicio:
        wheres.append(f"date(criado_em) >= '{data_inicio}'")
    if data_fim:
        wheres.append(f"date(criado_em) <= '{data_fim}'")
    where_str = " AND ".join(wheres)
    linhas = local_query(f"SELECT fn_areceber_id FROM cob_interacoes WHERE {where_str}")
    fn_ids = [int(r["fn_areceber_id"]) for r in linhas if r["fn_areceber_id"]]
    if not fn_ids:
        return 0
    ph = ",".join(["%s"]*len(fn_ids))
    faturas = query(f"""
        SELECT f.id, f.status AS fatura_status, f.id_cliente,
               cc.status AS contrato_status
        FROM ixcprovedor.fn_areceber f
        LEFT JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
        WHERE f.id IN ({ph})
    """, tuple(fn_ids))
    fat_map = {f["id"]: f for f in faturas}

    id_clientes_check = list({f["id_cliente"] for f in faturas if f.get("id_cliente")})
    clientes_com_os39 = set()
    if id_clientes_check:
        ph2 = ",".join(["%s"]*len(id_clientes_check))
        os39 = query(f"""
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto = 39 AND status != 'F' AND id_cliente IN ({ph2})
        """, tuple(id_clientes_check))
        clientes_com_os39 = {r["id_cliente"] for r in os39}

    clientes_vistos = set()
    total = 0
    for fn_id in fn_ids:
        fat = fat_map.get(fn_id, {})
        if fat and (fat.get("fatura_status") != "A" or fat.get("contrato_status") not in ("A", None)):
            continue
        if fat and fat.get("id_cliente") in clientes_com_os39:
            continue
        id_cli = fat.get("id_cliente") if fat else None
        if id_cli and id_cli in clientes_vistos:
            continue
        if id_cli:
            clientes_vistos.add(id_cli)
        total += 1
    return total

def mover_para_segunda_cobranca(interacao_id: int, acao: str, obs: str, data_promessa: str = None):
    """Marca interação atual como resolvida, cria nova na segunda cobrança e acumula na OS 246."""
    from datetime import datetime, timezone, timedelta
    from app.core.ixc_api import IXC_API_URL, _auth
    import requests as _req

    tz_br = timezone(timedelta(hours=-3))
    agora = datetime.now(tz_br)
    agora_str = agora.strftime('%Y-%m-%d %H:%M:%S')
    agora_fmt = agora.strftime('%d/%m/%Y %H:%M')

    # Busca interação original
    orig = local_query_one("SELECT * FROM cob_interacoes WHERE id=?", (interacao_id,))
    if not orig:
        return False

    # Busca operador
    op = local_query_one("SELECT nome FROM cob_usuarios WHERE id=?", (orig["usuario_id"],))
    nome_op = op["nome"] if op else "Operador"

    # Marca original como resolvida
    local_execute("UPDATE cob_interacoes SET resolvido=1, acao=?, obs=?, data_promessa=? WHERE id=?",
                  (acao, obs, data_promessa, interacao_id))

    # Cria nova interação na segunda cobrança
    local_execute("""
        INSERT INTO cob_interacoes
        (fn_areceber_id, usuario_id, acao, obs, pago, criado_em, data_promessa, resolvido, segunda_cobranca)
        VALUES (?,?,?,?,0,?,?,0,1)
    """, (orig["fn_areceber_id"], orig["usuario_id"], acao, obs, agora_str, data_promessa))

    # Busca id_cliente via fn_areceber
    cli = query_one("SELECT id_cliente FROM ixcprovedor.fn_areceber WHERE id=%s", (orig["fn_areceber_id"],))
    if not cli:
        return True
    id_cliente = cli["id_cliente"]

    # Nova mensagem de interação
    nova_msg = f"\n{'='*35}\n2ª COBRANÇA — {agora_fmt}\nFatura: #{orig['fn_areceber_id']}\nOperador: {nome_op}\nAção: {acao}"
    if obs:
        nova_msg += f"\nObs: {obs}"
    if data_promessa:
        nova_msg += f"\nPromessa de pagamento: {data_promessa}"
    nova_msg += f"\n{'='*35}"

    # Verifica se existe OS 246 aberta
    os_aberta = query_one("""
        SELECT id, mensagem FROM ixcprovedor.su_oss_chamado
        WHERE id_cliente=%s AND id_assunto=190 AND status='A' LIMIT 1
    """, (id_cliente,))

    if os_aberta:
        # Acumula mensagem na OS existente
        msg_atual = os_aberta["mensagem"] or ""
        nova_mensagem = msg_atual + nova_msg
        try:
            execute("""
                UPDATE ixcprovedor.su_oss_chamado
                SET mensagem=%s WHERE id=%s
            """, (nova_mensagem, os_aberta["id"]))
        except: pass
    else:
        # Abre nova OS 246
        id_cidade_row = query_one("SELECT cidade FROM ixcprovedor.cliente WHERE id=%s", (id_cliente,))
        id_cidade = str(id_cidade_row["cidade"]) if id_cidade_row and id_cidade_row["cidade"] else ""
        url  = f"{IXC_API_URL}/webservice/v1/su_oss_chamado"
        data = {
            "tipo": "C", "id_assunto": "246", "id_cliente": str(id_cliente),
            "id_filial": "1", "setor": "13", "mensagem": nova_msg.strip(),
            "status": "A", "prioridade": "B", "origem_cadastro": "P",
            "origem_endereco": "C", "id_cidade": id_cidade,
            "liberado": "1", "impresso": "N", "gera_comissao": "N",
            "melhor_horario_agenda": "Q", "status_pesquisa_satisfacao": "0",
        }
        try:
            hdrs = {"Authorization": _auth(), "ixcsoft": ""}
            _req.post(url, data=data, headers=hdrs, timeout=10)
        except: pass

    return True


# ── SEGUNDA COBRANÇA ─────────────────────────────────────────────────────────
def count_segunda_cobranca(usuario_id: int = None, data_inicio: str = None, data_fim: str = None):
    wheres = ["segunda_cobranca=1", "pago=0", "(resolvido IS NULL OR resolvido=0)"]
    if usuario_id:
        wheres.append(f"usuario_id={usuario_id}")
    if data_inicio:
        wheres.append(f"date(criado_em) >= '{data_inicio}'")
    if data_fim:
        wheres.append(f"date(criado_em) <= '{data_fim}'")
    where_str = " AND ".join(wheres)
    linhas = local_query(f"SELECT fn_areceber_id FROM cob_interacoes WHERE {where_str}")
    fn_ids = [int(r["fn_areceber_id"]) for r in linhas if r["fn_areceber_id"]]
    if not fn_ids:
        return 0
    ph = ",".join(["%s"]*len(fn_ids))
    faturas = query(f"""
        SELECT f.id, f.status AS fatura_status, f.id_cliente,
               cc.status AS contrato_status
        FROM ixcprovedor.fn_areceber f
        LEFT JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
        WHERE f.id IN ({ph})
    """, tuple(fn_ids))
    fat_map = {f["id"]: f for f in faturas}

    id_clientes_check = list({f["id_cliente"] for f in faturas if f.get("id_cliente")})
    clientes_com_os39 = set()
    if id_clientes_check:
        ph2 = ",".join(["%s"]*len(id_clientes_check))
        os39 = query(f"""
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto = 39 AND status != 'F' AND id_cliente IN ({ph2})
        """, tuple(id_clientes_check))
        clientes_com_os39 = {r["id_cliente"] for r in os39}

    total = 0
    for fn_id in fn_ids:
        fat = fat_map.get(fn_id, {})
        # Mesma logica da lista: fat vazio (fatura nao encontrada) conta como valido por padrao
        if fat and (fat.get("fatura_status") != "A" or fat.get("contrato_status") not in ("A", None)):
            continue
        if fat and fat.get("id_cliente") in clientes_com_os39:
            continue
        total += 1
    return total

def mover_para_segunda_cobranca(interacao_id: int, acao: str, obs: str, data_promessa: str = None):
    """Marca interação atual como resolvida, cria nova na segunda cobrança e acumula na OS 246."""
    from datetime import datetime, timezone, timedelta
    from app.core.ixc_api import IXC_API_URL, _auth
    import requests as _req

    tz_br = timezone(timedelta(hours=-3))
    agora = datetime.now(tz_br)
    agora_str = agora.strftime('%Y-%m-%d %H:%M:%S')
    agora_fmt = agora.strftime('%d/%m/%Y %H:%M')

    # Busca interação original
    orig = local_query_one("SELECT * FROM cob_interacoes WHERE id=?", (interacao_id,))
    if not orig:
        return False

    # Busca operador
    op = local_query_one("SELECT nome FROM cob_usuarios WHERE id=?", (orig["usuario_id"],))
    nome_op = op["nome"] if op else "Operador"

    # Marca original como resolvida
    local_execute("UPDATE cob_interacoes SET resolvido=1, acao=?, obs=?, data_promessa=? WHERE id=?",
                  (acao, obs, data_promessa, interacao_id))

    # Cria nova interação na segunda cobrança
    local_execute("""
        INSERT INTO cob_interacoes
        (fn_areceber_id, usuario_id, acao, obs, pago, criado_em, data_promessa, resolvido, segunda_cobranca)
        VALUES (?,?,?,?,0,?,?,0,1)
    """, (orig["fn_areceber_id"], orig["usuario_id"], acao, obs, agora_str, data_promessa))

    # Busca id_cliente via fn_areceber
    cli = query_one("SELECT id_cliente FROM ixcprovedor.fn_areceber WHERE id=%s", (orig["fn_areceber_id"],))
    if not cli:
        return True
    id_cliente = cli["id_cliente"]

    # Nova mensagem de interação
    nova_msg = f"\n{'='*35}\n2ª COBRANÇA — {agora_fmt}\nFatura: #{orig['fn_areceber_id']}\nOperador: {nome_op}\nAção: {acao}"
    if obs:
        nova_msg += f"\nObs: {obs}"
    if data_promessa:
        nova_msg += f"\nPromessa de pagamento: {data_promessa}"
    nova_msg += f"\n{'='*35}"

    # Verifica se existe OS 246 aberta
    os_aberta = query_one("""
        SELECT id, mensagem FROM ixcprovedor.su_oss_chamado
        WHERE id_cliente=%s AND id_assunto=190 AND status='A' LIMIT 1
    """, (id_cliente,))

    if os_aberta:
        # Acumula mensagem na OS existente
        msg_atual = os_aberta["mensagem"] or ""
        nova_mensagem = msg_atual + nova_msg
        try:
            execute("""
                UPDATE ixcprovedor.su_oss_chamado
                SET mensagem=%s WHERE id=%s
            """, (nova_mensagem, os_aberta["id"]))
        except: pass
    else:
        # Abre nova OS 246
        id_cidade_row = query_one("SELECT cidade FROM ixcprovedor.cliente WHERE id=%s", (id_cliente,))
        id_cidade = str(id_cidade_row["cidade"]) if id_cidade_row and id_cidade_row["cidade"] else ""
        url  = f"{IXC_API_URL}/webservice/v1/su_oss_chamado"
        data = {
            "tipo": "C", "id_assunto": "246", "id_cliente": str(id_cliente),
            "id_filial": "1", "setor": "13", "mensagem": nova_msg.strip(),
            "status": "A", "prioridade": "B", "origem_cadastro": "P",
            "origem_endereco": "C", "id_cidade": id_cidade,
            "liberado": "1", "impresso": "N", "gera_comissao": "N",
            "melhor_horario_agenda": "Q", "status_pesquisa_satisfacao": "0",
        }
        try:
            hdrs = {"Authorization": _auth(), "ixcsoft": ""}
            _req.post(url, data=data, headers=hdrs, timeout=10)
        except: pass

    return True
