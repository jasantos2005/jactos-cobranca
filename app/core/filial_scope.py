from app.core.db import query_one


def resolver_filial_contrato(id_contrato: int) -> int:
    """
    Resolve a filial operacional a partir do contrato.

    Regra:
    - A filial oficial da OS vem de cliente_contrato.id_filial.
    - Nunca utiliza cliente.filial_id como fallback.
    - Nunca utiliza filial 1 como fallback.
    - Contrato inexistente ou sem filial válida gera erro.

    Esta função somente consulta dados.
    Nenhuma alteração é realizada no banco.
    """

    try:
        id_contrato = int(id_contrato or 0)
    except (TypeError, ValueError):
        id_contrato = 0

    if id_contrato <= 0:
        raise ValueError(
            "ID do contrato inválido para resolução da filial."
        )

    contrato = query_one("""
        SELECT
            id,
            id_cliente,
            id_filial
        FROM ixcprovedor.cliente_contrato
        WHERE id = %s
        LIMIT 1
    """, (id_contrato,))

    if not contrato:
        raise ValueError(
            f"Contrato #{id_contrato} não encontrado."
        )

    id_filial = contrato.get("id_filial")

    try:
        id_filial = int(id_filial or 0)
    except (TypeError, ValueError):
        id_filial = 0

    if id_filial <= 0:
        raise ValueError(
            f"Contrato #{id_contrato} não possui filial válida."
        )

    return id_filial
