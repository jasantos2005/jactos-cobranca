#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.5

Objetivo:
    Gerar uma análise CLIENTE POR CLIENTE para padronização do campo
    cliente.bairro no IXC.

REGRAS:
    - SOMENTE LEITURA.
    - Nenhum UPDATE.
    - Nenhum INSERT.
    - Nenhum DELETE.
    - Nenhuma alteração estrutural no banco.
    - A classificação da V3.4 continua sendo a referência inicial.
    - Cada cliente recebe o CEP, bairro atual, padrão sugerido,
      classificação e justificativa.

A V3.5 NÃO executa nenhuma correção.
"""

from pathlib import Path
import csv
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.db import get_connection


def query_all(sql, params=None):
    """Executa SELECT e retorna todas as linhas como dicionários."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.fetchall()
    finally:
        conn.close()



OUT_DIR = ROOT / "backups"

OUT_TSV = OUT_DIR / "auditoria_padronizacao_bairros_v3_5_CLIENTE.tsv"
OUT_TXT = OUT_DIR / "auditoria_padronizacao_bairros_v3_5_CLIENTE.txt"


def normalizar_texto(valor):
    valor = str(valor or "").strip().upper()
    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(
        c for c in valor
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(valor.split())


def normalizar_cep(valor):
    digits = "".join(c for c in str(valor or "") if c.isdigit())
    if len(digits) == 8:
        return digits
    return digits


def carregar_clientes():
    """
    Busca somente os campos necessários no IXC.

    Nenhuma operação de escrita é realizada.
    """
    sql = """
        SELECT
            id,
            razao,
            fantasia,
            bairro,
            cep,
            cidade,
            uf
        FROM ixcprovedor.cliente
        WHERE bairro IS NOT NULL
          AND TRIM(bairro) <> ''
        ORDER BY cep, id
    """

    return query_all(sql)


def agrupar_por_cep(clientes):
    grupos = {}

    for cliente in clientes:
        cep = normalizar_cep(cliente.get("cep"))

        if not cep:
            continue

        grupos.setdefault(cep, []).append(cliente)

    return grupos


def familias_bairro(registros):
    """
    Agrupa nomes iguais após normalização básica.

    Isto NÃO declara que bairros semanticamente diferentes são iguais.
    Apenas permite identificar variações de escrita.
    """
    familias = {}

    for registro in registros:
        bairro = str(registro.get("bairro") or "").strip()
        chave = normalizar_texto(bairro)

        familias.setdefault(chave, []).append(bairro)

    return familias


def analisar_grupo(registros):
    """
    Classificação conservadora:

    SEGURO:
        uma única família normalizada.

    REVISAR:
        existe uma família dominante, mas há outras.

    BLOQUEADO:
        múltiplas famílias relevantes.

    A V3.5 é deliberadamente conservadora.
    """
    familias = familias_bairro(registros)

    contagem = sorted(
        familias.items(),
        key=lambda item: (-len(item[1]), item[0])
    )

    if not contagem:
        return {
            "status": "BLOQUEADO",
            "padrao": "",
            "motivo": "Nenhum bairro válido encontrado.",
            "familias": [],
        }

    principal_chave, principal_variantes = contagem[0]

    padrao = principal_variantes[0]

    detalhes = []

    for chave, variantes in contagem:
        unicos = sorted(set(variantes), key=lambda x: normalizar_texto(x))
        detalhes.append(
            f"{chave} [{len(variantes)}] => "
            + " | ".join(unicos)
        )

    if len(contagem) == 1:
        status = "SEGURO"
        motivo = (
            "Todas as variantes possuem a mesma normalização textual."
        )
    else:
        total = len(registros)
        principal = len(principal_variantes)
        percentual = (principal / total) * 100 if total else 0

        if percentual >= 95:
            status = "REVISAR"
            motivo = (
                f"Família dominante representa {percentual:.2f}% "
                f"dos clientes, mas existem outras variantes/famílias."
            )
        else:
            status = "BLOQUEADO"
            motivo = (
                "Existem múltiplas famílias de bairros no mesmo CEP."
            )

    return {
        "status": status,
        "padrao": padrao,
        "motivo": motivo,
        "familias": detalhes,
    }


def gerar():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 110)
    print("AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.5")
    print("=" * 110)
    print("MODO: SOMENTE LEITURA — NENHUMA ALTERAÇÃO NO IXC")
    print()

    clientes = carregar_clientes()
    grupos = agrupar_por_cep(clientes)

    print(f"Clientes analisados: {len(clientes)}")
    print(f"CEPs analisados: {len(grupos)}")
    print()

    analises = {}

    for cep, registros in grupos.items():
        analises[cep] = analisar_grupo(registros)

    contagem_status = {
        "SEGURO": 0,
        "REVISAR": 0,
        "BLOQUEADO": 0,
    }

    for resultado in analises.values():
        contagem_status[resultado["status"]] += 1

    print("DISTRIBUIÇÃO V3.5:")
    for status, quantidade in contagem_status.items():
        print(f"  {status}: {quantidade}")

    print()
    print("Gerando arquivo cliente por cliente...")

    with OUT_TSV.open(
        "w",
        encoding="utf-8",
        newline=""
    ) as f:
        writer = csv.writer(
            f,
            delimiter="\t",
            lineterminator="\n"
        )

        writer.writerow([
            "cliente_id",
            "razao",
            "fantasia",
            "cep",
            "cidade",
            "uf",
            "bairro_atual",
            "bairro_normalizado",
            "status_cep",
            "bairro_padrao_sugerido",
            "motivo",
        ])

        total_linhas = 0

        for cep in sorted(grupos):
            resultado = analises[cep]

            for cliente in grupos[cep]:
                bairro_atual = str(
                    cliente.get("bairro") or ""
                ).strip()

                writer.writerow([
                    cliente.get("id"),
                    cliente.get("razao") or "",
                    cliente.get("fantasia") or "",
                    cep,
                    cliente.get("cidade") or "",
                    cliente.get("uf") or "",
                    bairro_atual,
                    normalizar_texto(bairro_atual),
                    resultado["status"],
                    resultado["padrao"],
                    resultado["motivo"],
                ])

                total_linhas += 1

    with OUT_TXT.open("w", encoding="utf-8") as f:
        f.write("=" * 120 + "\n")
        f.write("AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.5\n")
        f.write("=" * 120 + "\n")
        f.write("MODO: SOMENTE LEITURA — NENHUMA ALTERAÇÃO NO IXC\n\n")

        f.write(f"Clientes analisados: {len(clientes)}\n")
        f.write(f"CEPs analisados: {len(grupos)}\n\n")

        f.write("DISTRIBUIÇÃO V3.5:\n")
        for status, quantidade in contagem_status.items():
            f.write(f"  {status}: {quantidade}\n")

        f.write("\n")
        f.write("=" * 120 + "\n")
        f.write("CLIENTES — UM POR LINHA\n")
        f.write("=" * 120 + "\n\n")

        for cep in sorted(grupos):
            resultado = analises[cep]

            f.write(
                f"CEP: {cep} | "
                f"STATUS: {resultado['status']} | "
                f"PADRÃO SUGERIDO: {resultado['padrao']}\n"
            )

            f.write(
                f"MOTIVO: {resultado['motivo']}\n"
            )

            f.write("-" * 120 + "\n")

            for cliente in grupos[cep]:
                bairro_atual = str(
                    cliente.get("bairro") or ""
                ).strip()

                f.write(
                    f"CLIENTE #{cliente.get('id')} | "
                    f"RAZÃO: {cliente.get('razao') or ''} | "
                    f"FANTASIA: {cliente.get('fantasia') or ''}\n"
                )

                f.write(
                    f"BAIRRO ATUAL: {bairro_atual} | "
                    f"NORMALIZADO: {normalizar_texto(bairro_atual)}\n"
                )

                f.write(
                    f"CEP: {cep} | "
                    f"CIDADE: {cliente.get('cidade') or ''} | "
                    f"UF: {cliente.get('uf') or ''}\n"
                )

                f.write(
                    f"PADRÃO SUGERIDO: {resultado['padrao']}\n"
                )

                f.write("\n")

            f.write("\n")

        f.write("=" * 120 + "\n")
        f.write("FIM DA AUDITORIA V3.5\n")
        f.write("=" * 120 + "\n")
        f.write("IXC UPDATE: NÃO\n")
        f.write("IXC INSERT: NÃO\n")
        f.write("IXC DELETE: NÃO\n")
        f.write("CLIENTES ALTERADOS: 0\n")

    print()
    print("=" * 110)
    print("ARQUIVOS GERADOS")
    print("=" * 110)
    print(f"TSV: {OUT_TSV}")
    print(f"TXT: {OUT_TXT}")
    print()
    print(f"Linhas cliente TSV: {total_linhas}")
    print(f"Tamanho TSV: {OUT_TSV.stat().st_size:,} bytes")
    print(f"Tamanho TXT: {OUT_TXT.stat().st_size:,} bytes")
    print()
    print("IXC UPDATE: NÃO")
    print("IXC INSERT: NÃO")
    print("IXC DELETE: NÃO")
    print("CLIENTES ALTERADOS: 0")
    print("=" * 110)


if __name__ == "__main__":
    gerar()
