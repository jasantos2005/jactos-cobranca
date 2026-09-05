#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.6.1

VERSÃO OTIMIZADA DA V3.6

Objetivo:
    Auditar cliente.bairro somente para Goiânia.

Características:
    - SOMENTE LEITURA.
    - Nenhum UPDATE.
    - Nenhum INSERT.
    - Nenhum DELETE.
    - Não altera o IXC.
    - Resultado cliente por cliente.
    - Agrupamento semântico conservador.
    - Não executa Levenshtein contra milhares de clientes.
"""

from pathlib import Path
import csv
import re
import sys
import unicodedata
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.db import get_connection


OUT_DIR = ROOT / "backups"

OUT_TSV = (
    OUT_DIR /
    "auditoria_padronizacao_bairros_v361_CLIENTE.tsv"
)

OUT_TXT = (
    OUT_DIR /
    "auditoria_padronizacao_bairros_v361_CLIENTE.txt"
)


PREFIXOS = (
    "SETOR",
    "BAIRRO",
    "RESIDENCIAL",
    "LOTEAMENTO",
)


def query_all(sql, params=None):
    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.fetchall()
    finally:
        conn.close()


def normalizar_texto(valor):
    valor = str(valor or "").strip().upper()

    valor = unicodedata.normalize(
        "NFD",
        valor
    )

    valor = "".join(
        c
        for c in valor
        if unicodedata.category(c) != "Mn"
    )

    valor = re.sub(
        r"\s+",
        " ",
        valor
    )

    return valor.strip()


def normalizar_cep(valor):
    valor = "".join(
        c
        for c in str(valor or "")
        if c.isdigit()
    )

    return valor if len(valor) == 8 else ""


def remover_prefixo(texto):
    texto = normalizar_texto(texto)

    for prefixo in PREFIXOS:
        if texto.startswith(prefixo + " "):
            return texto[len(prefixo):].strip()

    return texto


def chave_familia(bairro):
    """
    Chave semântica principal.

    Mantém números e identificadores:
        VILA MUTIRAO
        VILA MUTIRAO I
        VILA MUTIRAO II

    são diferentes.
    """
    return remover_prefixo(bairro)


def distancia_limitada(a, b, limite=2):
    """
    Levenshtein limitado.

    Só calcula até o limite necessário.
    Evita custo elevado em nomes muito diferentes.
    """

    if a == b:
        return 0

    if abs(len(a) - len(b)) > limite:
        return limite + 1

    anterior = list(range(len(b) + 1))

    for i, ca in enumerate(a, 1):

        inicio = max(1, i - limite)
        fim = min(len(b), i + limite)

        atual = [i] * (len(b) + 1)

        for j in range(inicio, fim + 1):

            custo = 0 if ca == b[j - 1] else 1

            atual[j] = min(
                atual[j - 1] + 1,
                anterior[j] + 1,
                anterior[j - 1] + custo,
            )

        if min(atual[inicio:fim + 1]) > limite:
            return limite + 1

        anterior = atual

    return anterior[-1]


def parecem_mesma_familia(a, b):
    """
    Comparação somente entre chaves de bairro distintas.

    Nunca é chamada cliente contra cliente.
    """

    if a == b:
        return True

    # Não juntar nomes com identificadores diferentes.
    tokens_a = a.split()
    tokens_b = b.split()

    numeros_a = [
        t for t in tokens_a
        if re.search(r"\d|^(I|II|III|IV|V|VI|VII|VIII|IX|X)$", t)
    ]

    numeros_b = [
        t for t in tokens_b
        if re.search(r"\d|^(I|II|III|IV|V|VI|VII|VIII|IX|X)$", t)
    ]

    if numeros_a != numeros_b:
        return False

    # Somente erros pequenos.
    limite = 1

    if max(len(a), len(b)) >= 18:
        limite = 2

    return distancia_limitada(
        a,
        b,
        limite=limite
    ) <= limite


def carregar_clientes():
    """
    Universo exclusivo de Goiânia.

    cidade=5412 foi confirmado no diagnóstico do projeto.
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
        WHERE cidade = 5412
          AND bairro IS NOT NULL
          AND TRIM(bairro) <> ''
        ORDER BY cep, id
    """

    return query_all(sql)


def agrupar_por_cep(clientes):

    grupos = {}

    for cliente in clientes:

        cep = normalizar_cep(
            cliente.get("cep")
        )

        if not cep:
            continue

        grupos.setdefault(
            cep,
            []
        ).append(cliente)

    return grupos


def construir_familias(registros):
    """
    Primeiro agrupa por chave exata.

    Somente depois compara as CHAVES DISTINTAS.

    Isso elimina o problema de comparar milhares
    de clientes entre si.
    """

    por_chave = {}

    for registro in registros:

        bairro = str(
            registro.get("bairro") or ""
        ).strip()

        if not bairro:
            continue

        chave = chave_familia(
            bairro
        )

        por_chave.setdefault(
            chave,
            []
        ).append(registro)

    chaves = list(por_chave)

    # Na grande maioria dos CEPs haverá apenas uma
    # ou poucas chaves. Portanto o custo fica pequeno.
    familias = []

    usadas = set()

    for chave in chaves:

        if chave in usadas:
            continue

        grupo = []

        for outra in chaves:

            if outra in usadas:
                continue

            if parecem_mesma_familia(
                chave,
                outra
            ):
                grupo.extend(
                    por_chave[outra]
                )
                usadas.add(outra)

        familias.append(
            {
                "chave": chave,
                "registros": grupo,
            }
        )

    return familias


def escolher_padrao(registros):
    """
    Escolhe a grafia real mais frequente no IXC.
    """

    contagem = Counter(
        str(
            r.get("bairro") or ""
        ).strip()
        for r in registros
    )

    if not contagem:
        return ""

    return sorted(
        contagem.items(),
        key=lambda x: (
            -x[1],
            len(x[0]),
            normalizar_texto(x[0]),
        )
    )[0][0]


def detalhes_familia(registros):

    contagem = Counter(
        str(
            r.get("bairro") or ""
        ).strip()
        for r in registros
    )

    partes = []

    for bairro, quantidade in sorted(
        contagem.items(),
        key=lambda x: (
            -x[1],
            normalizar_texto(x[0])
        )
    ):
        partes.append(
            f"{bairro} [{quantidade}]"
        )

    return " | ".join(partes)


def analisar_cep(registros):

    familias = construir_familias(
        registros
    )

    familias.sort(
        key=lambda f: -len(
            f["registros"]
        )
    )

    if not familias:

        return {
            "status": "BLOQUEADO",
            "padrao": "",
            "motivo": (
                "Nenhum bairro válido."
            ),
            "familias": [],
        }

    total = len(registros)

    principal = len(
        familias[0]["registros"]
    )

    percentual = (
        principal / total * 100
        if total
        else 0
    )

    saida_familias = []

    for familia in familias:

        registros_familia = (
            familia["registros"]
        )

        saida_familias.append(
            {
                "quantidade":
                    len(registros_familia),

                "padrao":
                    escolher_padrao(
                        registros_familia
                    ),

                "detalhes":
                    detalhes_familia(
                        registros_familia
                    ),
            }
        )

    if len(familias) == 1:

        status = "SEGURO"

        motivo = (
            "Todas as variantes do CEP "
            "pertencem à mesma família "
            "semântica."
        )

    elif percentual >= 95:

        status = "REVISAR"

        motivo = (
            f"A família dominante possui "
            f"{percentual:.2f}% dos clientes, "
            "mas existem outras famílias."
        )

    else:

        status = "BLOQUEADO"

        motivo = (
            "CEP possui famílias de bairros "
            "estruturalmente distintas."
        )

    return {
        "status": status,
        "padrao":
            escolher_padrao(
                familias[0]["registros"]
            ),
        "motivo": motivo,
        "familias": saida_familias,
    }


def main():

    OUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 110)
    print(
        "AUDITORIA DE PADRONIZAÇÃO DE BAIRROS "
        "— V3.6.1"
    )
    print("=" * 110)
    print(
        "MODO: SOMENTE LEITURA — "
        "NENHUMA ALTERAÇÃO NO IXC"
    )
    print(
        "UNIVERSO: GOIÂNIA — cidade=5412"
    )
    print()

    clientes = carregar_clientes()

    grupos = agrupar_por_cep(
        clientes
    )

    print(
        f"Clientes retornados: "
        f"{len(clientes)}"
    )

    print(
        f"Clientes com CEP válido: "
        f"{sum(len(v) for v in grupos.values())}"
    )

    print(
        f"CEPs analisados: "
        f"{len(grupos)}"
    )

    print()
    print(
        "Processando CEPs de forma otimizada..."
    )

    analises = {}

    for numero, (cep, registros) in enumerate(
        sorted(grupos.items()),
        1
    ):

        analises[cep] = analisar_cep(
            registros
        )

        if numero % 250 == 0:
            print(
                f"  {numero}/{len(grupos)} CEPs..."
            )

    distribuicao = Counter(
        resultado["status"]
        for resultado in analises.values()
    )

    print()
    print("DISTRIBUIÇÃO V3.6.1:")

    for status in (
        "SEGURO",
        "REVISAR",
        "BLOQUEADO",
    ):

        print(
            f"  {status}: "
            f"{distribuicao.get(status, 0)}"
        )

    # =========================================================
    # TSV
    # =========================================================

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
            "familia_normalizada",
            "status_cep",
            "bairro_padrao_sugerido",
            "motivo",
        ])

        total_exportado = 0

        for cep in sorted(grupos):

            resultado = analises[cep]

            for cliente in grupos[cep]:

                bairro = str(
                    cliente.get("bairro") or ""
                ).strip()

                writer.writerow([
                    cliente.get("id"),
                    cliente.get("razao") or "",
                    cliente.get("fantasia") or "",
                    cep,
                    cliente.get("cidade") or "",
                    cliente.get("uf") or "",
                    bairro,
                    normalizar_texto(
                        bairro
                    ),
                    chave_familia(
                        bairro
                    ),
                    resultado["status"],
                    resultado["padrao"],
                    resultado["motivo"],
                ])

                total_exportado += 1

    # =========================================================
    # TXT COMPLETO
    # =========================================================

    with OUT_TXT.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write("=" * 120 + "\n")
        f.write(
            "AUDITORIA DE PADRONIZAÇÃO DE BAIRROS "
            "— V3.6.1\n"
        )
        f.write("=" * 120 + "\n")

        f.write(
            "MODO: SOMENTE LEITURA — "
            "NENHUMA ALTERAÇÃO NO IXC\n"
        )

        f.write(
            "UNIVERSO: GOIÂNIA — cidade=5412\n\n"
        )

        f.write(
            f"Clientes retornados: "
            f"{len(clientes)}\n"
        )

        f.write(
            f"Clientes exportados: "
            f"{total_exportado}\n"
        )

        f.write(
            f"CEPs analisados: "
            f"{len(grupos)}\n\n"
        )

        f.write(
            "DISTRIBUIÇÃO V3.6.1:\n"
        )

        for status in (
            "SEGURO",
            "REVISAR",
            "BLOQUEADO",
        ):

            f.write(
                f"  {status}: "
                f"{distribuicao.get(status, 0)}\n"
            )

        f.write("\n")

        for cep in sorted(grupos):

            resultado = analises[cep]

            registros = grupos[cep]

            f.write("=" * 120 + "\n")

            f.write(
                f"CEP: {cep}\n"
            )

            f.write(
                f"STATUS: "
                f"{resultado['status']}\n"
            )

            f.write(
                f"PADRÃO SUGERIDO: "
                f"{resultado['padrao']}\n"
            )

            f.write(
                f"MOTIVO: "
                f"{resultado['motivo']}\n"
            )

            f.write(
                "\nFAMÍLIAS IDENTIFICADAS:\n"
            )

            for familia in resultado[
                "familias"
            ]:

                f.write(
                    f"  "
                    f"{familia['quantidade']} "
                    f"clientes | "
                    f"{familia['padrao']} | "
                    f"{familia['detalhes']}\n"
                )

            f.write(
                "\nCLIENTES:\n"
            )

            f.write(
                "-" * 120 + "\n"
            )

            for cliente in registros:

                bairro = str(
                    cliente.get("bairro") or ""
                ).strip()

                f.write(
                    f"CLIENTE "
                    f"#{cliente.get('id')}\n"
                )

                f.write(
                    f"RAZÃO: "
                    f"{cliente.get('razao') or ''}\n"
                )

                f.write(
                    f"FANTASIA: "
                    f"{cliente.get('fantasia') or ''}\n"
                )

                f.write(
                    f"CEP: {cep}\n"
                )

                f.write(
                    f"BAIRRO ATUAL: "
                    f"{bairro}\n"
                )

                f.write(
                    f"BAIRRO NORMALIZADO: "
                    f"{normalizar_texto(bairro)}\n"
                )

                f.write(
                    f"FAMÍLIA: "
                    f"{chave_familia(bairro)}\n"
                )

                f.write(
                    f"PADRÃO SUGERIDO: "
                    f"{resultado['padrao']}\n"
                )

                f.write(
                    f"STATUS: "
                    f"{resultado['status']}\n\n"
                )

    print()
    print("=" * 110)
    print("ARQUIVOS V3.6.1 GERADOS")
    print("=" * 110)

    print(
        f"TSV: {OUT_TSV}"
    )

    print(
        f"TXT: {OUT_TXT}"
    )

    print()

    print(
        f"Clientes no TSV: "
        f"{total_exportado}"
    )

    print(
        f"Tamanho TSV: "
        f"{OUT_TSV.stat().st_size:,} bytes"
    )

    print(
        f"Tamanho TXT: "
        f"{OUT_TXT.stat().st_size:,} bytes"
    )

    print()
    print("IXC UPDATE: NÃO")
    print("IXC INSERT: NÃO")
    print("IXC DELETE: NÃO")
    print("CLIENTES ALTERADOS: 0")
    print("=" * 110)


if __name__ == "__main__":
    main()
