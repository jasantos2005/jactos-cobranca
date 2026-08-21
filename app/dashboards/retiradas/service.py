from app.core.db import query, query_one, execute
from app.core.db_local import local_query, local_query_one, local_execute
from decimal import Decimal

# ─── KPIs ─────────────────────────────────────────────────────────────────────
def get_kpis_retiradas():
    abertas    = query_one("SELECT COUNT(*) AS total FROM ixcprovedor.su_oss_chamado WHERE id_assunto=34 AND status='A'", ())
    agendadas  = query_one("SELECT COUNT(*) AS total FROM ixcprovedor.su_oss_chamado WHERE id_assunto=34 AND status IN ('AG','RAG')", ())
    concluidas = query_one("SELECT COUNT(*) AS total FROM ixcprovedor.su_oss_chamado WHERE id_assunto=34 AND status='F' AND DATE(data_fechamento)=CURDATE()", ())
    sem_agenda = (abertas["total"] if abertas else 0) - (agendadas["total"] if agendadas else 0)
    return {
        "abertas":    abertas["total"] if abertas else 0,
        "agendadas":  agendadas["total"] if agendadas else 0,
        "concluidas": concluidas["total"] if concluidas else 0,
        "sem_agenda": max(0, sem_agenda),
    }

# ─── OS SEM AGENDAMENTO ───────────────────────────────────────────────────────
def get_os_sem_agendamento(busca="", cidade=0, pagina=1, por_pagina=30):
    limit = int(por_pagina)
    off   = int((pagina - 1) * por_pagina)
    # IDs já agendados
    agendados = [r["id_os"] for r in local_query("SELECT id_os FROM cob_retiradas_agendamentos WHERE status='agendado'", ())]
    where = "WHERE o.id_assunto=34 AND o.status NOT IN ('F')"
    if agendados:
        ids = ",".join(str(i) for i in agendados)
        where += f" AND o.id NOT IN ({ids})"
    params = []
    if busca:
        where += " AND (c.razao LIKE %s OR c.cnpj_cpf LIKE %s)"
        b = f"%{busca}%"
        params += [b, b]
    if cidade:
        where += " AND c.cidade=%s"
        params.append(cidade)
    params += [limit, off]
    rows = query(f"""
        SELECT o.id AS id_os, o.id_cliente,
               DATE_FORMAT(o.data_abertura,'%%d/%%m/%%Y') AS data_abertura,
               c.razao, c.cnpj_cpf, c.endereco, c.numero, c.bairro,
               COALESCE(cid.nome, c.cidade) AS cidade_nome, c.cidade AS id_cidade,
               COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.cliente c ON c.id=o.id_cliente
        LEFT  JOIN ixcprovedor.cidade cid ON cid.id=c.cidade
        {where}
        ORDER BY o.data_abertura ASC
        LIMIT %s OFFSET %s
    """, params)
    for row in rows:
        row["equipamentos"] = get_equipamentos_cliente(row["id_cliente"])
    return rows

def count_os_sem_agendamento(busca="", cidade=0):
    agendados = [r["id_os"] for r in local_query("SELECT id_os FROM cob_retiradas_agendamentos WHERE status='agendado'", ())]
    where = "WHERE o.id_assunto=34 AND o.status NOT IN ('F')"
    if agendados:
        ids = ",".join(str(i) for i in agendados)
        where += f" AND o.id NOT IN ({ids})"
    params = []
    if busca:
        where += " AND (c.razao LIKE %s OR c.cnpj_cpf LIKE %s)"
        b = f"%{busca}%"
        params += [b, b]
    if cidade:
        where += " AND c.cidade=%s"
        params.append(cidade)
    r = query_one(f"""
        SELECT COUNT(*) AS total FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.cliente c ON c.id=o.id_cliente
        {where}
    """, params)
    return r["total"] if r else 0

# ─── OS AGENDADAS ─────────────────────────────────────────────────────────────
def get_os_agendadas(busca="", cidade=0, tecnico=0, pagina=1, por_pagina=30):
    limit = int(por_pagina)
    off   = int((pagina - 1) * por_pagina)
    ags   = local_query("SELECT * FROM cob_retiradas_agendamentos WHERE status='agendado' ORDER BY agendado_em DESC", ())
    if not ags:
        return []
    ids_map = {a["id_os"]: dict(a) for a in ags}
    ids_str = ",".join(str(i) for i in ids_map.keys())
    where   = f"WHERE o.id IN ({ids_str})"
    params  = []
    if busca:
        where += " AND (c.razao LIKE %s OR c.cnpj_cpf LIKE %s)"
        b = f"%{busca}%"
        params += [b, b]
    if cidade:
        where += " AND c.cidade=%s"
        params.append(cidade)
    if tecnico:
        ids_tec = [str(a["id_os"]) for a in ags if a["id_tecnico_ixc"] == tecnico]
        if ids_tec:
            where += f" AND o.id IN ({','.join(ids_tec)})"
        else:
            return []
    params += [limit, off]
    rows = query(f"""
        SELECT o.id AS id_os, o.id_cliente,
               DATE_FORMAT(o.data_abertura,'%%d/%%m/%%Y') AS data_abertura,
               c.razao, c.endereco, c.numero, c.bairro,
               COALESCE(cid.nome, c.cidade) AS cidade_nome, c.cidade AS id_cidade,
               COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.cliente c ON c.id=o.id_cliente
        LEFT  JOIN ixcprovedor.cidade cid ON cid.id=c.cidade
        {where}
        ORDER BY o.data_abertura ASC
        LIMIT %s OFFSET %s
    """, params)
    for row in rows:
        row["equipamentos"] = get_equipamentos_cliente(row["id_cliente"])
        row["agendamento"]  = ids_map.get(row["id_os"], {})
    return rows

def count_os_agendadas(busca="", cidade=0, tecnico=0):
    r = local_query_one("SELECT COUNT(*) AS total FROM cob_retiradas_agendamentos WHERE status='agendado'")
    return r["total"] if r else 0

# ─── EQUIPAMENTOS ─────────────────────────────────────────────────────────────
def get_equipamentos_cliente(id_cliente: int):
    return query("""
        SELECT mp.descricao, mp.numero_serie, mp.mac
        FROM ixcprovedor.movimento_produtos mp
        LEFT JOIN ixcprovedor.cliente_contrato cc ON cc.id=mp.id_contrato
        WHERE cc.id_cliente=%s AND mp.status_comodato='E'
        ORDER BY mp.descricao
    """, (id_cliente,))

# ─── TÉCNICOS (tabela local) ───────────────────────────────────────────────────
def get_tecnicos():
    return local_query("SELECT id, nome, ixc_login_id, telefone FROM cob_tecnicos_retirada WHERE ativo=1 ORDER BY nome", ())

def get_tecnicos_todos():
    return local_query("SELECT id, nome, ixc_login_id, telefone, ativo FROM cob_tecnicos_retirada ORDER BY nome", ())

def inserir_tecnico(nome, ixc_login_id, telefone, criado_em):
    local_execute("INSERT INTO cob_tecnicos_retirada (nome, ixc_login_id, telefone, ativo, criado_em) VALUES (?,?,?,1,?)",
                  (nome, ixc_login_id, telefone, criado_em))

def atualizar_tecnico(id_tec, nome, ixc_login_id, telefone):
    local_execute("UPDATE cob_tecnicos_retirada SET nome=?, ixc_login_id=?, telefone=? WHERE id=?",
                  (nome, ixc_login_id, telefone, id_tec))

def desativar_tecnico(id_tec):
    local_execute("UPDATE cob_tecnicos_retirada SET ativo=0 WHERE id=?", (id_tec,))

def ativar_tecnico(id_tec):
    local_execute("UPDATE cob_tecnicos_retirada SET ativo=1 WHERE id=?", (id_tec,))

# ─── CIDADES ──────────────────────────────────────────────────────────────────
def get_cidades_retiradas():
    return query("""
        SELECT c.cidade AS id_cidade,
               COALESCE(cid.nome, c.cidade) AS cidade_nome,
               COUNT(o.id) AS total
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.cliente c ON c.id=o.id_cliente
        LEFT  JOIN ixcprovedor.cidade cid ON cid.id=c.cidade
        WHERE o.id_assunto=34 AND o.status NOT IN ('F')
        GROUP BY c.cidade, cidade_nome
        ORDER BY total DESC
    """, ())

# ─── AGENDAMENTO ──────────────────────────────────────────────────────────────
def agendar_os(id_os, id_cliente, id_tecnico_local, agendado_por, data_agenda="", obs=""):
    from datetime import datetime, timezone, timedelta
    tz_br = timezone(timedelta(hours=-3))
    agora = datetime.now(tz_br).strftime('%Y-%m-%d %H:%M:%S')
    # Busca técnico local
    tec = local_query_one("SELECT nome, ixc_login_id FROM cob_tecnicos_retirada WHERE id=? AND ativo=1", (id_tecnico_local,))
    if not tec:
        return False, "Técnico não encontrado"
    nome_tecnico = tec["nome"]
    ixc_login_id = tec["ixc_login_id"]
    # Cancela agendamento anterior
    local_execute("UPDATE cob_retiradas_agendamentos SET status='cancelado' WHERE id_os=? AND status='agendado'", (id_os,))
    # Atualiza técnico na OS do IXC
    try:
        execute("UPDATE ixcprovedor.su_oss_chamado SET id_tecnico=%s WHERE id=%s", (ixc_login_id, id_os))
    except: pass
    # Registra agendamento local
    local_execute("""
        INSERT INTO cob_retiradas_agendamentos
        (id_os, id_cliente, id_tecnico_ixc, nome_tecnico, agendado_por, agendado_em, data_agenda, obs)
        VALUES (?,?,?,?,?,?,?,?)
    """, (id_os, id_cliente, ixc_login_id, nome_tecnico, agendado_por, agora, data_agenda, obs))
    return True, f"OS agendada para {nome_tecnico}"

def cancelar_agendamento(id_os):
    local_execute("UPDATE cob_retiradas_agendamentos SET status='cancelado' WHERE id_os=? AND status='agendado'", (id_os,))
    try:
        execute("UPDATE ixcprovedor.su_oss_chamado SET id_tecnico=0 WHERE id=%s", (id_os,))
    except: pass
    return True

# ─── HISTÓRICO MONITORAMENTO ──────────────────────────────────────────────────
def get_historico_monitoramento(limit=7):
    return local_query("SELECT executado_em, pagaram, retiradas, erros, obs FROM cob_monitoramento_execucoes ORDER BY id DESC LIMIT ?", (limit,))
