"""
Resolução de bairro pela Matriz de Bairros do HubCobrança JACTOS.

A matriz é local ao HubCobrança e utiliza o CEP como chave de referência.
O cadastro original do IXC nunca é alterado por este módulo.
"""

import re
import sqlite3
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parents[2]
SQLITE_DB = BASE_DIR / "cobranca_local.db"


def normalizar_cep(cep) -> str:
    """
    Normaliza CEP removendo pontuação e espaços.

    Exemplos:
        74474-101 -> 74474101
        74474101  -> 74474101
    """
    if cep is None:
        return ""

    return re.sub(r"[^0-9]", "", str(cep))


def resolver_bairro_por_cep(
    cep,
    *,
    somente_aprovado: bool = True,
) -> Optional[str]:
    """
    Resolve o bairro padrão através da matriz local.

    Por padrão, somente registros APROVADOS são retornados.

    REVISAR/AMBIGUO:
        retornam None quando somente_aprovado=True.

    Isso evita que o sistema utilize automaticamente um
    bairro ainda não validado pela matriz.
    """

    cep_normalizado = normalizar_cep(cep)

    if len(cep_normalizado) != 8:
        return None

    if not SQLITE_DB.exists():
        raise RuntimeError(
            f"Banco local não encontrado: {SQLITE_DB}"
        )

    conn = sqlite3.connect(SQLITE_DB)

    try:
        row = conn.execute(
            """
            SELECT
                bairro_padrao,
                status
            FROM cob_matriz_bairros
            WHERE cep = ?
            LIMIT 1
            """,
            (cep_normalizado,),
        ).fetchone()

    finally:
        conn.close()

    if not row:
        return None

    bairro_padrao, status = row

    if somente_aprovado and status != "APROVADO":
        return None

    return bairro_padrao


def consultar_matriz_bairro(cep) -> Optional[dict]:
    """
    Retorna o registro completo da matriz para auditoria.

    Não aplica filtro de status.
    """

    cep_normalizado = normalizar_cep(cep)

    if len(cep_normalizado) != 8:
        return None

    if not SQLITE_DB.exists():
        raise RuntimeError(
            f"Banco local não encontrado: {SQLITE_DB}"
        )

    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row

    try:
        row = conn.execute(
            """
            SELECT
                id,
                cep,
                bairro_padrao,
                status,
                origem,
                observacao
            FROM cob_matriz_bairros
            WHERE cep = ?
            LIMIT 1
            """,
            (cep_normalizado,),
        ).fetchone()

        if not row:
            return None

        return dict(row)

    finally:
        conn.close()
