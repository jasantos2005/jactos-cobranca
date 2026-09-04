from app.core.db import query, query_one
from app.core.db_local import local_query
from app.core.historico_os import preparar_historico_os


def montar_contexto_os(
    id_contrato: int,
    fn_areceber_id: int = 0
) -> dict:
    """
    Monta todo o contexto necessário para uma OS de cobrança/retirada.

    IMPORTANTE:
    - O contrato é a referência da filial.
    - Não existe fallback para filial 1.
    - A fatura precisa pertencer ao contrato informado.
    - Equipamentos são identificados pelo vínculo patrimonial
      com o contrato.
    - O almoxarifado é apenas informação complementar.
    - O histórico bruto é preservado.
    - O histórico preparado é disponibilizado para o gerador da OS.
    - Esta função somente consulta dados.
    - Nenhuma OS é criada ou alterada.
    """

    if not id_contrato:
        raise ValueError(
            "ID do contrato não informado."
        )

    # ============================================================
    # 1. CONTRATO + CLIENTE + FILIAL
    # ============================================================

    contrato = query_one("""
        SELECT
            cc.id AS id_contrato,
            cc.id_cliente,
            cc.id_filial,
            cc.status AS contrato_status,
            c.razao AS cliente,
            c.cnpj_cpf,
            COALESCE(
                c.whatsapp,
                c.telefone_celular,
                c.fone,
                ''
            ) AS telefone
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.cliente c
            ON c.id = cc.id_cliente
        WHERE cc.id = %s
        LIMIT 1
    """, (id_contrato,))

    if not contrato:
        raise ValueError(
            f"Contrato #{id_contrato} não encontrado."
        )

    contrato = dict(contrato)

    id_cliente = contrato["id_cliente"]
    id_filial = contrato.get("id_filial")

    if not id_filial or int(id_filial) <= 0:
        raise ValueError(
            f"Contrato #{id_contrato} não possui filial válida."
        )

    # ============================================================
    # 2. FATURA
    # ============================================================

    fatura = None

    if fn_areceber_id:
        fatura = query_one("""
            SELECT
                f.id,
                f.id_cliente,
                f.id_contrato,
                f.documento,
                f.valor,
                f.valor_aberto,
                f.valor_recebido,
                f.status,
                f.data_vencimento,

                DATEDIFF(
                    CURDATE(),
                    f.data_vencimento
                ) AS dias_atraso

            FROM ixcprovedor.fn_areceber f

            WHERE f.id = %s

            LIMIT 1
        """, (fn_areceber_id,))

        if not fatura:
            raise ValueError(
                f"Fatura #{fn_areceber_id} não encontrada."
            )

        fatura = dict(fatura)

        if int(fatura.get("id_contrato") or 0) != int(id_contrato):
            raise ValueError(
                f"Fatura #{fn_areceber_id} não pertence "
                f"ao contrato #{id_contrato}."
            )

        if int(fatura.get("id_cliente") or 0) != int(id_cliente):
            raise ValueError(
                f"Fatura #{fn_areceber_id} não pertence "
                f"ao cliente #{id_cliente}."
            )

    # ============================================================
    # 3. HISTÓRICO BRUTO DA COBRANÇA
    # ============================================================

    historico = []

    if fn_areceber_id:
        historico = local_query("""
            SELECT
                i.id,
                i.fn_areceber_id,
                i.usuario_id,
                i.acao,
                i.obs,
                i.pago,
                i.data_promessa,
                i.criado_em,
                i.resolvido,
                i.segunda_cobranca
            FROM cob_interacoes i
            WHERE i.fn_areceber_id = ?
            ORDER BY
                i.criado_em ASC,
                i.id ASC
        """, (fn_areceber_id,))

        historico = [
            dict(row)
            for row in historico
        ]

        # ========================================================
        # 3.1. USUÁRIOS DO HISTÓRICO
        # ========================================================

        usuarios = {}

        usuario_ids = {
            int(item["usuario_id"])
            for item in historico
            if item.get("usuario_id")
        }

        if usuario_ids:
            placeholders = ",".join(
                "?" for _ in usuario_ids
            )

            usuarios_rows = local_query(
                f"""
                    SELECT
                        id,
                        nome
                    FROM cob_usuarios
                    WHERE id IN ({placeholders})
                """,
                tuple(usuario_ids)
            )

            usuarios = {
                int(row["id"]): row["nome"]
                for row in usuarios_rows
            }

        # ========================================================
        # 3.2. ENRIQUECIMENTO DO HISTÓRICO BRUTO
        # ========================================================

        for item in historico:
            usuario_id = item.get("usuario_id")

            item["usuario_nome"] = (
                usuarios.get(
                    int(usuario_id),
                    "Sistema"
                )
                if usuario_id
                else "Sistema"
            )

            acao = (
                item.get("acao") or ""
            ).strip()

            item["eh_pagamento"] = (
                acao.lower()
                == "pagamento realizado"
            )

            item["eh_promessa"] = (
                bool(item.get("data_promessa"))
                or "promessa" in acao.lower()
            )

            item["eh_segunda_cobranca"] = bool(
                item.get("segunda_cobranca")
            )

    # ============================================================
    # 3.3. HISTÓRICO PREPARADO PARA A OS
    # ============================================================

    historico_os = preparar_historico_os(
        historico
    )

    # ============================================================
    # 4. EQUIPAMENTOS / PATRIMÔNIOS DO CONTRATO
    # ============================================================

    equipamentos = query("""
        SELECT
            pm.id,
            pm.id_contrato,
            pm.id_patrimonio,
            pm.cliente_destino,
            pm.data_movimentacao,

            cc.id_cliente,
            cc.id_filial,

            pat.descricao AS equipamento,
            pat.serial,
            pat.id_mac,
            pat.valor_bem,
            pat.id_almoxarifado,

            alm.descricao AS almox_nome

        FROM ixcprovedor.patrimonio_movimentacao pm

        INNER JOIN ixcprovedor.cliente_contrato cc
            ON cc.id = pm.id_contrato
           AND cc.id_cliente = pm.cliente_destino

        INNER JOIN ixcprovedor.patrimonio pat
            ON pat.id = pm.id_patrimonio

        LEFT JOIN ixcprovedor.almox alm
            ON alm.id = pat.id_almoxarifado

        WHERE pm.id_contrato = %s

        ORDER BY
            pm.id_patrimonio,
            pm.data_movimentacao DESC,
            pm.id DESC
    """, (id_contrato,))

    # ============================================================
    # 4.1. ÚLTIMO MOVIMENTO DE CADA PATRIMÔNIO
    # ============================================================

    equipamentos_map = {}

    for equipamento in equipamentos:
        equipamento = dict(equipamento)

        patrimonio_id = equipamento.get(
            "id_patrimonio"
        )

        if patrimonio_id is None:
            continue

        if patrimonio_id not in equipamentos_map:
            equipamentos_map[
                patrimonio_id
            ] = equipamento

    equipamentos = list(
        equipamentos_map.values()
    )

    # ============================================================
    # 5. RESUMO GERAL
    # ============================================================

    resumo = {
        "tem_fatura": bool(fatura),
        "tem_historico": bool(historico),
        "tem_equipamentos": bool(equipamentos),
        "quantidade_interacoes": len(historico),
        "quantidade_equipamentos": len(equipamentos),
    }

    # ============================================================
    # 5.1. INFORMAÇÕES DA FATURA NO RESUMO
    # ============================================================

    if fatura:
        resumo["dias_atraso"] = int(
            fatura.get("dias_atraso") or 0
        )

        resumo["valor_aberto"] = (
            fatura.get("valor_aberto")
            or 0
        )

        resumo["fatura_paga"] = (
            fatura.get("status") == "R"
            or float(
                fatura.get("valor_aberto") or 0
            ) <= 0
        )

    # ============================================================
    # 6. RETORNO
    # ============================================================

    return {
        "cliente": {
            "id": id_cliente,
            "nome": contrato.get("cliente"),
            "documento": contrato.get("cnpj_cpf"),
            "telefone": contrato.get("telefone"),
        },

        "contrato": contrato,

        "filial": {
            "id": int(id_filial),
        },

        "fatura": fatura,

        # Histórico bruto, preservado para compatibilidade.
        "historico": historico,

        # Histórico normalizado/preparado para o gerador.
        "historico_os": historico_os,

        "equipamentos": equipamentos,

        "resumo": resumo,
    }
