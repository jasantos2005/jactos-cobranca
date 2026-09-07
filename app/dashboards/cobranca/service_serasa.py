from app.core.db import query, query_one


ALMOX_PERDIDO = 29
ALMOX_AVARIA = 16


def _status_equipamento(id_patrimonio, id_cliente):
    """
    Determina o estado atual do patrimônio usando a mesma regra
    já utilizada pelo módulo de equipamentos do HubCobrança.
    """
    if not id_patrimonio:
        return None

    mov = query_one("""
        SELECT
            pm.id_patrimonio,
            pm.id_contrato,
            pm.cliente_destino,
            pm.data_movimentacao,
            pat.id_almoxarifado,
            pat.descricao,
            pat.serial,
            pat.id_mac,
            pat.valor_bem
        FROM ixcprovedor.patrimonio_movimentacao pm
        INNER JOIN ixcprovedor.patrimonio pat
                ON pat.id = pm.id_patrimonio
        WHERE pm.id_patrimonio = %s
        ORDER BY pm.data_movimentacao DESC, pm.id DESC
        LIMIT 1
    """, (id_patrimonio,))

    if not mov:
        return None

    almox = int(mov.get("id_almoxarifado") or 0)
    cliente_destino = int(mov.get("cliente_destino") or 0)
    cliente = int(id_cliente or 0)

    # A última movimentação prevalece sobre patrimonio.id_almoxarifado.
    # Se o patrimônio continua vinculado a contrato/cliente, ele está
    # fisicamente com o cliente, mesmo que o cadastro do patrimônio
    # ainda mantenha o último almoxarifado utilizado.
    if cliente_destino > 0:
        if cliente_destino != cliente:
            status = "novo_cliente"
            label = "Vinculado a outro cliente"
            pendente = False
        else:
            status = "comodato"
            label = "Em comodato / com cliente"
            pendente = True
    elif almox == ALMOX_PERDIDO:
        status = "perdido"
        label = "Perdido"
        pendente = True
    elif almox == ALMOX_AVARIA:
        status = "avaria"
        label = "Avaria"
        pendente = True
    elif almox > 0:
        status = "estoque"
        label = "No estoque"
        pendente = False
    else:
        status = "indefinido"
        label = "Indefinido"
        pendente = False

    return {
        "id_patrimonio": id_patrimonio,
        "id_contrato": mov.get("id_contrato"),
        "equipamento": mov.get("descricao"),
        "serial": mov.get("serial"),
        "mac": mov.get("id_mac"),
        "valor_bem": float(mov.get("valor_bem") or 0),
        "cliente_destino": cliente_destino,
        "id_almoxarifado": almox,
        "data_movimentacao": mov.get("data_movimentacao"),
        "status": status,
        "status_label": label,
        "pendente": pendente,
    }


def _equipamentos_contrato(id_contrato, id_cliente):
    if not id_contrato:
        return []

    rows = query("""
        SELECT
            pm.id_patrimonio
        FROM ixcprovedor.patrimonio_movimentacao pm
        WHERE pm.id_contrato = %s
          AND pm.id_patrimonio IS NOT NULL
          AND pm.id_patrimonio > 0
        GROUP BY pm.id_patrimonio
    """, (id_contrato,))

    result = []

    for r in rows:
        equip = _status_equipamento(
            r["id_patrimonio"],
            id_cliente
        )
        if equip:
            result.append(equip)

    return result


def _financeiro_cliente(id_cliente):
    rows = query("""
        SELECT
            n.id AS id_negativacao,
            n.data_negativacao,
            n.id_finan,
            f.id_contrato,
            f.documento,
            f.data_vencimento,
            f.valor,
            f.valor_aberto,
            n.status
        FROM ixcprovedor.negativacao_spc_serasa n
        LEFT JOIN ixcprovedor.fn_areceber f
               ON f.id = n.id_finan
        WHERE n.id_cliente = %s
        ORDER BY n.data_negativacao DESC, n.id DESC
    """, (id_cliente,))

    return [dict(r) for r in rows]


def _classificar(financeiro, equipamentos):
    valor_financeiro = sum(
        float(r.get("valor_aberto") or r.get("valor") or 0)
        for r in financeiro
        if int(r.get("status") or 0) == 1
    )

    equipamentos_pendentes = [
        e for e in equipamentos
        if e.get("pendente")
    ]

    tem_financeiro = valor_financeiro > 0
    tem_equipamento = bool(equipamentos_pendentes)

    if tem_financeiro and tem_equipamento:
        categoria = "ambos"
        categoria_label = "Financeiro + Equipamento"
    elif tem_financeiro:
        categoria = "financeiro"
        categoria_label = "Somente financeiro"
    elif tem_equipamento:
        categoria = "equipamento"
        categoria_label = "Somente equipamento"
    else:
        categoria = "financeiro"
        categoria_label = "Financeiro"

    return {
        "categoria": categoria,
        "categoria_label": categoria_label,
        "valor_financeiro": valor_financeiro,
        "valor_equipamento": sum(float(e.get("valor_bem") or 0) for e in equipamentos),
        "equipamentos_pendentes": equipamentos_pendentes,
    }


def get_clientes_serasa(cpf=None, limite=30):
    """
    Retorna clientes atualmente negativados.

    Fonte da situação atual:
      cliente.ativo_serasa = 2

    Todo o carregamento é feito em lote:
      1. clientes;
      2. contratos vinculados às negativações;
      3. patrimônios;
      4. última movimentação dos patrimônios;
      5. dados financeiros.

    Nenhuma consulta individual é executada dentro do loop de clientes.
    """
    clientes = query("""
        SELECT
            c.id AS id_cliente,
            c.razao,
            c.cnpj_cpf,
            c.whatsapp,
            c.telefone_celular
        FROM ixcprovedor.cliente c
        INNER JOIN ixcprovedor.negativacao_spc_serasa n
                ON n.id_cliente = c.id
        LEFT JOIN ixcprovedor.remocao_spc_serasa r
               ON r.id_negativacao = n.id
        WHERE r.id IS NULL
          AND n.status = 1
        GROUP BY c.id
        ORDER BY MAX(n.data_negativacao) DESC, c.id
    """)

    if not clientes:
        return []

    clientes = [dict(r) for r in clientes]
    ids_clientes = [int(r["id_cliente"]) for r in clientes]

    ph_clientes = ",".join(["%s"] * len(ids_clientes))

    # ---------------------------------------------------------------
    # 1. Negativações e contratos
    # ---------------------------------------------------------------
    negativacoes = query(
        f"""
        SELECT
            n.id AS id_negativacao,
            n.id_cliente,
            n.data_negativacao,
            n.id_finan,
            n.status,
            f.id_contrato,
            f.documento,
            f.data_vencimento,
            f.valor,
            f.valor_aberto
        FROM ixcprovedor.negativacao_spc_serasa n
        LEFT JOIN ixcprovedor.fn_areceber f
               ON f.id = n.id_finan
        WHERE n.id_cliente IN ({ph_clientes})
        ORDER BY n.data_negativacao DESC, n.id DESC
        """,
        tuple(ids_clientes),
    )

    negativacoes = [dict(r) for r in negativacoes]

    financeiro_map = {}
    contratos_por_cliente = {}

    for r in negativacoes:
        cid = int(r["id_cliente"])

        financeiro_map.setdefault(cid, []).append(r)

        contrato = r.get("id_contrato")
        if contrato:
            try:
                contrato = int(contrato)
            except (TypeError, ValueError):
                contrato = 0

            if contrato > 0:
                contratos_por_cliente.setdefault(cid, set()).add(contrato)

    contrato_ids = sorted({
        contrato
        for contratos in contratos_por_cliente.values()
        for contrato in contratos
    })

    # ---------------------------------------------------------------
    # 2. Patrimônios por contrato
    # ---------------------------------------------------------------
    patrimonios_por_contrato = {}

    if contrato_ids:
        ph_contratos = ",".join(["%s"] * len(contrato_ids))

        patrimonio_rows = query(
            f"""
            SELECT DISTINCT
                pm.id_contrato,
                pm.id_patrimonio
            FROM ixcprovedor.patrimonio_movimentacao pm
            WHERE pm.id_contrato IN ({ph_contratos})
              AND pm.id_patrimonio IS NOT NULL
              AND pm.id_patrimonio > 0
            """,
            tuple(contrato_ids),
        )

        for r in patrimonio_rows:
            contrato = int(r["id_contrato"])
            patrimonio = int(r["id_patrimonio"])

            patrimonios_por_contrato.setdefault(
                contrato, set()
            ).add(patrimonio)

    patrimonio_ids = sorted({
        patrimonio
        for patrimonios in patrimonios_por_contrato.values()
        for patrimonio in patrimonios
    })

    # ---------------------------------------------------------------
    # 3. Última movimentação + patrimônio
    # ---------------------------------------------------------------
    equipamentos_por_patrimonio = {}

    if patrimonio_ids:
        ph_patrimonios = ",".join(["%s"] * len(patrimonio_ids))

        movimentos = query(
            f"""
            SELECT
                pm.id_patrimonio,
                pm.id_contrato,
                pm.cliente_destino,
                pm.data_movimentacao,
                pat.id_almoxarifado,
                pat.descricao,
                pat.serial,
                pat.id_mac,
                pr.valor AS valor_produto
            FROM ixcprovedor.patrimonio_movimentacao pm
            INNER JOIN (
                SELECT
                    id_patrimonio,
                    MAX(id) AS ultimo_id
                FROM ixcprovedor.patrimonio_movimentacao
                WHERE id_patrimonio IN ({ph_patrimonios})
                GROUP BY id_patrimonio
            ) ult
              ON ult.id_patrimonio = pm.id_patrimonio
             AND ult.ultimo_id = pm.id
            INNER JOIN ixcprovedor.patrimonio pat
                    ON pat.id = pm.id_patrimonio
            LEFT JOIN ixcprovedor.produtos pr
                    ON pr.id = pat.id_produto
            """,
            tuple(patrimonio_ids),
        )

        for r in movimentos:
            r = dict(r)

            patrimonio = int(r["id_patrimonio"])
            almox = int(r.get("id_almoxarifado") or 0)
            cliente_destino = int(r.get("cliente_destino") or 0)

            equipamento = {
                "id_patrimonio": patrimonio,
                "id_contrato": r.get("id_contrato"),
                "equipamento": r.get("descricao"),
                "serial": r.get("serial"),
                "mac": r.get("id_mac"),
                "valor_bem": float(r.get("valor_produto") or 0),
                "cliente_destino": cliente_destino,
                "id_almoxarifado": almox,
                "data_movimentacao": r.get("data_movimentacao"),
                "status": None,
                "status_label": None,
                "pendente": False,
            }

            if almox == ALMOX_PERDIDO:
                equipamento["status"] = "perdido"
                equipamento["status_label"] = "Perdido"
                equipamento["pendente"] = True

            elif almox == ALMOX_AVARIA:
                equipamento["status"] = "avaria"
                equipamento["status_label"] = "Avaria"
                equipamento["pendente"] = True

            elif almox > 0:
                equipamento["status"] = "estoque"
                equipamento["status_label"] = "No estoque"
                equipamento["pendente"] = False

            elif cliente_destino > 0:
                equipamento["status"] = "novo_cliente"
                equipamento["status_label"] = "Vinculado a outro cliente"
                equipamento["pendente"] = False

            else:
                equipamento["status"] = "indefinido"
                equipamento["status_label"] = "Indefinido"
                equipamento["pendente"] = False

            equipamentos_por_patrimonio[patrimonio] = equipamento

    # ---------------------------------------------------------------
    # 4. Montagem final em memória
    # ---------------------------------------------------------------
    result = []

    for cliente in clientes:
        cid = int(cliente["id_cliente"])

        financeiro = financeiro_map.get(cid, [])

        patrimonio_ids_cliente = set()

        for contrato in contratos_por_cliente.get(cid, set()):
            patrimonio_ids_cliente.update(
                patrimonios_por_contrato.get(contrato, set())
            )

        equipamentos = [
            equipamentos_por_patrimonio[pid]
            for pid in patrimonio_ids_cliente
            if pid in equipamentos_por_patrimonio
        ]

        equipamentos.sort(
            key=lambda e: (
                e.get("data_movimentacao") is not None,
                e.get("data_movimentacao") or "",
            ),
            reverse=True,
        )

        classificacao = _classificar(
            financeiro,
            equipamentos,
        )

        result.append({
            **cliente,
            "primeira_negativacao": min(
                (
                    r["data_negativacao"]
                    for r in financeiro
                    if r.get("data_negativacao")
                ),
                default=None,
            ),
            "ultima_negativacao": max(
                (
                    r["data_negativacao"]
                    for r in financeiro
                    if r.get("data_negativacao")
                ),
                default=None,
            ),
            "quantidade_negativacoes": len(financeiro),
            **classificacao,
            "equipamentos": equipamentos,
            "quantidade_equipamentos": len(equipamentos),
        })

    if cpf:
        documento_pesquisa = "".join(ch for ch in str(cpf) if ch.isdigit())
        if documento_pesquisa:
            result = [r for r in result if "".join(ch for ch in str(r.get("cnpj_cpf") or "") if ch.isdigit()) == documento_pesquisa]
        else:
            result = []
    else:
        result.sort(key=lambda r: (r.get("ultima_negativacao") is not None, r.get("ultima_negativacao") or ""), reverse=True)
        try:
            limite = int(limite)
        except (TypeError, ValueError):
            limite = 30
        if limite > 0:
            result = result[:limite]

    return result


def get_clientes_colocar_serasa(cpf=None, limite=30):
    """
    Retorna a fila "Colocar no Serasa" a partir do cache local.

    O IXC é atualizado pelo sincronizador periódico. A página não
    executa mais a montagem pesada da fila diretamente no IXC.
    """
    from app.core.db_local import local_query

    sql = """
        SELECT
            id,
            id_cliente,
            id_contrato,
            os63,
            razao,
            cnpj_cpf,
            data_abertura,
            status_os,
            mensagem,
            status_contrato,
            data_cancelamento,
            motivo_cancelamento,
            motivo_adicional,
            motivo_desistencia,
            origem_cancelamento,
            id_filial,
            valor_financeiro,
            valor_equipamento,
            quantidade_equipamentos,
            categoria,
            atualizado_em
        FROM cob_serasa_colocar
    """

    params = ()

    if cpf:
        documento = "".join(
            ch for ch in str(cpf) if ch.isdigit()
        )

        if documento:
            sql += """
                WHERE REPLACE(REPLACE(REPLACE(REPLACE(
                    COALESCE(cnpj_cpf, ''), '.', ''), '-', ''), '/', ''), ' ', '') = ?
            """
            params = (documento,)
        else:
            return []
    else:
        sql += """
            ORDER BY data_abertura DESC, os63 DESC
        """

    if not cpf:
        try:
            limite = int(limite)
        except (TypeError, ValueError):
            limite = 30

        if limite > 0:
            sql += " LIMIT ?"
            params = (limite,)

    rows = local_query(sql, params)

    equipamentos_por_chave = {}

    if rows:
        clientes = [
            (int(r["id_cliente"]), r.get("id_contrato"))
            for r in rows
        ]

        placeholders = ",".join(["?"] * len(clientes))
        where_parts = []
        eq_params = []

        for cliente, contrato in clientes:
            if contrato:
                where_parts.append(
                    "(id_cliente = ? AND id_contrato = ?)"
                )
                eq_params.extend([cliente, contrato])
            else:
                where_parts.append(
                    "(id_cliente = ? AND id_contrato IS NULL)"
                )
                eq_params.append(cliente)

        if where_parts:
            eq_rows = local_query(
                """
                SELECT
                    id_cliente,
                    id_contrato,
                    id_patrimonio,
                    equipamento,
                    valor,
                    serial,
                    mac,
                    status,
                    status_label,
                    pendente,
                    data_movimentacao
                FROM cob_serasa_colocar_equipamentos
                WHERE %s
                ORDER BY data_movimentacao DESC
                """ % " OR ".join(where_parts),
                tuple(eq_params),
            )

            for e in eq_rows:
                chave = (
                    int(e["id_cliente"]),
                    e.get("id_contrato"),
                )

                equipamentos_por_chave.setdefault(
                    chave, []
                ).append({
                    "id_patrimonio": e.get("id_patrimonio"),
                    "id_contrato": e.get("id_contrato"),
                    "equipamento": e.get("equipamento"),
                    "valor_bem": float(e.get("valor") or 0),
                    "serial": e.get("serial"),
                    "mac": e.get("mac"),
                    "status": e.get("status"),
                    "status_label": e.get("status_label"),
                    "pendente": bool(e.get("pendente")),
                    "data_movimentacao": e.get(
                        "data_movimentacao"
                    ),
                })

    result = []

    for row in rows:
        row = dict(row)

        chave = (
            int(row["id_cliente"]),
            row.get("id_contrato"),
        )

        equipamentos = equipamentos_por_chave.get(
            chave, []
        )

        row["valor_financeiro"] = float(
            row.get("valor_financeiro") or 0
        )
        row["valor_equipamento"] = float(
            row.get("valor_equipamento") or 0
        )
        row["quantidade_equipamentos"] = int(
            row.get("quantidade_equipamentos") or len(equipamentos)
        )
        row["equipamentos"] = equipamentos

        result.append(row)

    return result


def get_kpis_colocar_serasa():
    from app.core.db_local import local_query_one

    row = local_query_one("""
        SELECT
            COUNT(*) AS clientes,
            COALESCE(SUM(valor_financeiro), 0) AS valor_financeiro,
            COALESCE(SUM(valor_equipamento), 0) AS valor_equipamento,
            SUM(
                CASE
                    WHEN categoria = 'ambos' THEN 1
                    ELSE 0
                END
            ) AS ambos,
            SUM(
                CASE
                    WHEN categoria = 'financeiro' THEN 1
                    ELSE 0
                END
            ) AS financeiro,
            SUM(
                CASE
                    WHEN categoria = 'equipamento' THEN 1
                    ELSE 0
                END
            ) AS equipamento
        FROM cob_serasa_colocar
    """)

    row = row or {}

    return {
        "clientes": int(row.get("clientes") or 0),
        "valor_financeiro": round(
            float(row.get("valor_financeiro") or 0),
            2,
        ),
        "valor_equipamento": round(
            float(row.get("valor_equipamento") or 0),
            2,
        ),
        "ambos": int(row.get("ambos") or 0),
        "financeiro": int(row.get("financeiro") or 0),
        "equipamento": int(row.get("equipamento") or 0),
    }


def get_kpis_serasa():
    rows = get_clientes_serasa(limite=0)

    return {
        "clientes": len(rows),
        "valor_financeiro": round(
            sum(r["valor_financeiro"] for r in rows), 2
        ),
        "financeiro": sum(
            1 for r in rows if r["categoria"] == "financeiro"
        ),
        "equipamento": sum(
            1 for r in rows if r["categoria"] == "equipamento"
        ),
        "ambos": sum(
            1 for r in rows if r["categoria"] == "ambos"
        ),
        "equipamentos": sum(
            r["quantidade_equipamentos"] for r in rows
        ),
    }


def get_cliente_serasa(id_cliente):
    cliente = query_one("""
        SELECT
            c.id,
            c.razao,
            c.cnpj_cpf,
            c.whatsapp,
            c.telefone_celular,
            c.email,
            c.endereco,
            c.numero,
            c.bairro,
            c.cidade
        FROM ixcprovedor.cliente c
        WHERE c.id = %s
        LIMIT 1
    """, (id_cliente,))

    if not cliente:
        return None

    financeiro = _financeiro_cliente(id_cliente)

    contratos = query("""
        SELECT DISTINCT
            f.id_contrato
        FROM ixcprovedor.negativacao_spc_serasa n
        INNER JOIN ixcprovedor.fn_areceber f
                ON f.id = n.id_finan
        WHERE n.id_cliente = %s
          AND f.id_contrato IS NOT NULL
          AND f.id_contrato > 0
    """, (id_cliente,))

    equipamentos = []

    for contrato in contratos:
        equipamentos.extend(
            _equipamentos_contrato(
                contrato["id_contrato"],
                id_cliente
            )
        )

    vistos = set()
    equipamentos_unicos = []

    for equipamento in equipamentos:
        if equipamento["id_patrimonio"] in vistos:
            continue
        vistos.add(equipamento["id_patrimonio"])
        equipamentos_unicos.append(equipamento)

    classificacao = _classificar(
        financeiro,
        equipamentos_unicos
    )

    return {
        **dict(cliente),
        "financeiro": financeiro,
        "equipamentos": equipamentos_unicos,
        **classificacao,
    }


def get_kpis_saidas():
    """
    Retorna os KPIs da página de Saídas do Serasa.

    get_saidas_serasa() já entrega uma única saída por negativação,
    considerando somente a última baixa quando existem múltiplas baixas.
    """
    rows = get_saidas_serasa(limite=0)

    clientes = {
        int(r["id_cliente"])
        for r in rows
        if r.get("id_cliente") is not None
    }

    return {
        "clientes": len(clientes),
        "negativacoes": len(rows),
    }


def get_saidas_serasa(cpf=None, limite=30):
    """
    Retorna as negativações que tiveram saída do Serasa.

    Regra:
      - uma única linha por negativação;
      - quando existem várias baixas para a mesma negativação,
        considera somente a última baixa registrada;
      - a última baixa é determinada por data_baixa e, em caso
        de empate, pelo maior ID da remoção.

    Nenhuma consulta é feita individualmente por cliente.
    """
    rows = query("""
        SELECT
            n.id_cliente,
            c.razao,
            c.cnpj_cpf,
            n.id AS id_negativacao,
            n.data_negativacao,
            n.id_finan,
            n.forma_negativacao,
            n.forma_remocao,
            r.data_baixa,
            r.id_baixa,
            f.id_contrato,
            f.documento,
            f.data_vencimento,
            f.valor,
            f.valor_aberto
        FROM ixcprovedor.negativacao_spc_serasa n
        INNER JOIN ixcprovedor.cliente c
                ON c.id = n.id_cliente
        INNER JOIN ixcprovedor.remocao_spc_serasa r
                ON r.id_negativacao = n.id
        LEFT JOIN ixcprovedor.remocao_spc_serasa r2
               ON r2.id_negativacao = r.id_negativacao
              AND (
                    r2.data_baixa > r.data_baixa
                    OR (
                        r2.data_baixa = r.data_baixa
                        AND r2.id > r.id
                    )
              )
        LEFT JOIN ixcprovedor.fn_areceber f
               ON f.id = n.id_finan
        WHERE r2.id IS NULL
        ORDER BY r.data_baixa DESC, n.id DESC
    """)

    rows = [dict(r) for r in rows]

    # Calcula o valor oficial dos equipamentos por contrato.
    # Fonte: patrimonio -> produtos.valor.
    # Usa somente a última movimentação de cada patrimônio.
    contratos = sorted({
        int(r["id_contrato"])
        for r in rows
        if r.get("id_contrato")
    })

    valores_equipamentos = {}

    if contratos:
        placeholders = ",".join(["%s"] * len(contratos))

        equipamentos = query(f"""
            SELECT
                pm.id_contrato,
                pm.id_patrimonio,
                pr.valor AS valor_produto
            FROM ixcprovedor.patrimonio_movimentacao pm
            INNER JOIN (
                SELECT
                    id_contrato,
                    id_patrimonio,
                    MAX(id) AS ultimo_id
                FROM ixcprovedor.patrimonio_movimentacao
                WHERE id_contrato IN ({placeholders})
                GROUP BY id_contrato, id_patrimonio
            ) ult
                ON ult.id_contrato = pm.id_contrato
               AND ult.id_patrimonio = pm.id_patrimonio
               AND ult.ultimo_id = pm.id
            LEFT JOIN ixcprovedor.patrimonio p
                ON p.id = pm.id_patrimonio
            LEFT JOIN ixcprovedor.produtos pr
                ON pr.id = p.id_produto
        """, tuple(contratos))

        for equipamento in equipamentos:
            contrato = equipamento.get("id_contrato")
            valor = float(equipamento.get("valor_produto") or 0)
            valores_equipamentos[contrato] = (
                valores_equipamentos.get(contrato, 0) + valor
            )

    for row in rows:
        contrato = row.get("id_contrato")
        row["valor_equipamento"] = round(
            valores_equipamentos.get(contrato, 0),
            2
        )

    if cpf:
        documento_pesquisa = "".join(ch for ch in str(cpf) if ch.isdigit())
        if documento_pesquisa:
            rows = [r for r in rows if "".join(ch for ch in str(r.get("cnpj_cpf") or "") if ch.isdigit()) == documento_pesquisa]
        else:
            rows = []
    else:
        try:
            limite = int(limite)
        except (TypeError, ValueError):
            limite = 30
        if limite > 0:
            rows = rows[:limite]

    return rows


def get_historico_serasa(id_cliente):
    return {
        "cliente": get_cliente_serasa(id_cliente),
        "historico": query("""
            SELECT
                n.id,
                n.id_finan,
                n.data_negativacao,
                n.status,
                f.documento,
                f.data_vencimento,
                f.valor,
                f.valor_aberto,
                r.data_baixa,
                r.forma_remocao
            FROM ixcprovedor.negativacao_spc_serasa n
            LEFT JOIN ixcprovedor.fn_areceber f
                   ON f.id = n.id_finan
            LEFT JOIN ixcprovedor.remocao_spc_serasa r
                   ON r.id_negativacao = n.id
            WHERE n.id_cliente = %s
            ORDER BY n.data_negativacao DESC, n.id DESC
        """, (id_cliente,))
    }
