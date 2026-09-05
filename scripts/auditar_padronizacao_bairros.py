#!/usr/bin/env python3

"""
AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.4

OBJETIVO
--------
Identificar variantes de bairro no IXC que podem ser padronizadas
com segurança usando o próprio cadastro existente no IXC como fonte.

IMPORTANTE
----------
ESTE SCRIPT É SOMENTE LEITURA.

Não executa:
    UPDATE
    INSERT
    DELETE

A V3.4 trabalha com dois conceitos diferentes:

1. familia_comparacao
   Nome utilizado SOMENTE para comparar variantes semanticamente.

2. bairro_padrao_gravacao
   Valor REAL existente no IXC que poderia ser utilizado futuramente
   numa padronização.

A família de comparação pode remover prefixos estruturais como:

    JARDIM
    JD
    SETOR
    ST
    RESIDENCIAL
    BAIRRO

Mas NÃO remove números ou extensões.

Portanto:

    JARDIM COLORADO
    JARDIM COLORADO I

continuam sendo famílias diferentes.

Também:

    VILA MUTIRÃO
    VILA MUTIRÃO I
    VILA MUTIRÃO II

continuam diferentes.

Já:

    NOVO PLANALTO
    SETOR NOVO PLANALTO
    RESIDENCIAL NOVO PLANALTO

podem pertencer à mesma família.

A V3.4 também trata pequenas diferenças ortográficas e de acentuação
dentro da mesma família.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.db import get_connection


OUT = ROOT / "backups" / "auditoria_padronizacao_bairros_v3_4.tsv"


# ---------------------------------------------------------------------------
# TEXTO
# ---------------------------------------------------------------------------

PREFIXOS = (
    "JARDIM ",
    "JD ",
    "JD. ",
    "SETOR ",
    "ST ",
    "ST. ",
    "RESIDENCIAL ",
    "BAIRRO ",
)


def normalizar_texto(valor) -> str:
    if valor is None:
        return ""

    texto = str(valor).strip().upper()

    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        c for c in texto
        if not unicodedata.combining(c)
    )

    texto = re.sub(r"\s+", " ", texto)
    texto = texto.strip(" .,-_/")

    return texto


def familia_comparacao(bairro: str) -> str:
    """
    Cria a chave semântica utilizada para comparar bairros.

    Remove apenas prefixos estruturais.
    Não remove números, algarismos romanos ou extensões.
    """

    texto = normalizar_texto(bairro)

    alterou = True

    while alterou:
        alterou = False

        for prefixo in PREFIXOS:
            if texto.startswith(prefixo):
                texto = texto[len(prefixo):].strip()
                alterou = True
                break

    return texto


def forma_ortografica(bairro: str) -> str:
    """
    Forma utilizada para comparar diferenças pequenas de grafia.

    Mantém números e palavras relevantes.
    """

    texto = normalizar_texto(bairro)

    # Erros simples de espaçamento/pontuação.
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


def tokens(valor: str) -> set[str]:
    return set(forma_ortografica(valor).split())


def distancia_levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0

    if not a:
        return len(b)

    if not b:
        return len(a)

    if len(a) > len(b):
        a, b = b, a

    anterior = list(range(len(a) + 1))

    for j, cb in enumerate(b, 1):
        atual = [j]

        for i, ca in enumerate(a, 1):
            insercao = atual[i - 1] + 1
            remocao = anterior[i] + 1
            substituicao = anterior[i - 1] + (ca != cb)

            atual.append(
                min(insercao, remocao, substituicao)
            )

        anterior = atual

    return anterior[-1]


def similaridade(a: str, b: str) -> float:
    a = forma_ortografica(a)
    b = forma_ortografica(b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    maior = max(len(a), len(b))

    if maior == 0:
        return 1.0

    return 1.0 - (
        distancia_levenshtein(a, b) / maior
    )


# ---------------------------------------------------------------------------
# REGRAS DE FAMÍLIA
# ---------------------------------------------------------------------------

def mesma_familia(a: str, b: str) -> bool:
    """
    Decide se duas variantes podem ser tratadas como a mesma família.

    Regra principal:
        mesma familia_comparacao

    Regra adicional:
        pequena diferença ortográfica dentro da mesma base.

    IMPORTANTE:
        como familia_comparacao preserva números e extensões,
        não haverá fusão indevida de:

            COLORADO
            COLORADO I

        ou:

            MUTIRÃO
            MUTIRÃO I
    """

    fa = familia_comparacao(a)
    fb = familia_comparacao(b)

    if not fa or not fb:
        return False

    if fa == fb:
        return True

    # Diferença ortográfica pequena, mas somente dentro de
    # estruturas semanticamente próximas.
    sa = forma_ortografica(fa)
    sb = forma_ortografica(fb)

    if sa == sb:
        return True

    if not sa or not sb:
        return False

    # Não aproximar nomes com números/extensões diferentes.
    numeros_a = re.findall(r"\b\d+\b", sa)
    numeros_b = re.findall(r"\b\d+\b", sb)

    if numeros_a != numeros_b:
        return False

    # Algarismos romanos também representam extensões.
    romanos = r"\b(?:I|II|III|IV|V|VI|VII|VIII|IX|X)\b"

    rom_a = re.findall(romanos, sa)
    rom_b = re.findall(romanos, sb)

    if rom_a != rom_b:
        return False

    # Exemplo:
    # CANDIDA DE MORAES
    # CANDIDA DE MORAIS
    #
    # Deve poder ser analisado como mesma família.
    sim = similaridade(sa, sb)

    if sim >= 0.90:
        return True

    # Uma diferença simples de pluralização/acentuação já é
    # absorvida pela normalização; esta regra cobre apenas
    # diferenças ortográficas muito pequenas.
    ta = tokens(sa)
    tb = tokens(sb)

    if ta and tb:
        inter = len(ta & tb)
        uniao = len(ta | tb)

        if uniao and inter / uniao >= 0.75 and sim >= 0.86:
            return True

    return False


def construir_familias(variantes: Counter) -> list[dict]:
    """
    Agrupa variantes antes da classificação.

    O representante é sempre um valor ORIGINAL do IXC.
    """

    familias: list[dict] = []

    # Mais frequentes primeiro.
    ordenadas = sorted(
        variantes.items(),
        key=lambda item: (
            -item[1],
            normalizar_texto(item[0]),
        ),
    )

    for variante, quantidade in ordenadas:
        encontrada = None

        for familia in familias:
            if mesma_familia(
                variante,
                familia["familia_base"],
            ):
                encontrada = familia
                break

        if encontrada is None:
            encontrada = {
                "familia_base": familia_comparacao(variante),
                "representante": variante,
                "variantes": Counter(),
                "total": 0,
            }

            familias.append(encontrada)

        encontrada["variantes"][variante] += quantidade
        encontrada["total"] += quantidade

    familias.sort(
        key=lambda f: -f["total"]
    )

    # O representante permanece sempre sendo um nome real
    # existente no IXC, preferencialmente o mais frequente.
    for familia in familias:
        familia["representante"] = max(
            familia["variantes"],
            key=lambda nome: familia["variantes"][nome],
        )

    return familias


def formatar_familia(familia: dict) -> str:
    partes = []

    for nome, quantidade in sorted(
        familia["variantes"].items(),
        key=lambda item: -item[1],
    ):
        partes.append(
            f"{nome} ({quantidade})"
        )

    return (
        f"{familia['representante']} "
        f"[{familia['total']}]"
        + (
            " | " + " | ".join(partes)
            if partes
            else ""
        )
    )


# ---------------------------------------------------------------------------
# CLASSIFICAÇÃO
# ---------------------------------------------------------------------------

def analisar_cep(cep: str, registros: list[dict]) -> dict:
    variantes = Counter()

    for registro in registros:
        bairro = (
            registro.get("bairro")
            or ""
        ).strip()

        if bairro:
            variantes[bairro] += 1

    familias = construir_familias(variantes)

    clientes = sum(
        familia["total"]
        for familia in familias
    )

    if not familias:
        return {
            "cep": cep,
            "clientes": 0,
            "status": "BLOQUEADO",
            "bairro_padrao_gravacao": "",
            "familias": [],
            "motivo": "CEP sem bairro válido.",
        }

    principal = familias[0]
    segunda = familias[1] if len(familias) > 1 else None

    if len(familias) == 1:
        status = "SEGURO"
        motivo = (
            "Todas as variantes do CEP pertencem à mesma "
            "família semântica."
        )

    else:
        proporcao = (
            principal["total"] / clientes
            if clientes
            else 0
        )

        if (
            principal["total"] >= 10
            and proporcao >= 0.80
        ):
            status = "REVISAR"
            motivo = (
                "Existe uma família dominante, mas também "
                "há outras famílias no mesmo CEP."
            )
        else:
            status = "BLOQUEADO"
            motivo = (
                "CEP possui famílias de bairros "
                "estruturalmente distintas."
            )

    return {
        "cep": cep,
        "clientes": clientes,
        "status": status,
        "bairro_padrao_gravacao": principal["representante"],
        "familias": familias,
        "motivo": motivo,
    }


# ---------------------------------------------------------------------------
# BANCO
# ---------------------------------------------------------------------------

def carregar_clientes() -> list[dict]:
    sql = """
        SELECT
            id,
            bairro,
            cep
        FROM ixcprovedor.cliente
        WHERE cep IS NOT NULL
          AND TRIM(cep) <> ''
          AND bairro IS NOT NULL
          AND TRIM(bairro) <> ''
    """

    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            return list(cursor.fetchall())
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# EXECUÇÃO
# ---------------------------------------------------------------------------

def main():
    print("=" * 90)
    print("AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.4")
    print("MODO: SOMENTE LEITURA — NENHUMA ALTERAÇÃO NO IXC")
    print("=" * 90)

    rows = carregar_clientes()

    por_cep = defaultdict(list)

    for row in rows:
        cep = re.sub(
            r"\D",
            "",
            str(row.get("cep") or ""),
        )

        if len(cep) != 8:
            continue

        por_cep[cep].append(row)

    resultados = []

    for cep, registros in sorted(
        por_cep.items()
    ):
        resultados.append(
            analisar_cep(
                cep,
                registros,
            )
        )

    distribuicao = Counter(
        r["status"]
        for r in resultados
    )

    print()
    print(f"Clientes analisados: {len(rows)}")
    print(f"CEPs analisados: {len(resultados)}")
    print()
    print("DISTRIBUIÇÃO:")

    for status in (
        "SEGURO",
        "REVISAR",
        "BLOQUEADO",
    ):
        print(
            f"  {status}: "
            f"{distribuicao.get(status, 0)}"
        )

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUT.open(
        "w",
        encoding="utf-8",
    ) as f:
        f.write(
            "cep\tclientes\tstatus\t"
            "bairro_padrao_gravacao\t"
            "familias\tmotivo\n"
        )

        for resultado in resultados:
            familias = " || ".join(
                formatar_familia(f)
                for f in resultado["familias"]
            )

            f.write(
                "\t".join(
                    [
                        resultado["cep"],
                        str(resultado["clientes"]),
                        resultado["status"],
                        resultado[
                            "bairro_padrao_gravacao"
                        ],
                        familias,
                        resultado["motivo"],
                    ]
                )
                + "\n"
            )

    def imprimir_secao(
        titulo: str,
        status: str,
        limite: int = 40,
    ):
        print()
        print(titulo)

        itens = [
            r for r in resultados
            if r["status"] == status
        ]

        itens.sort(
            key=lambda r: -r["clientes"]
        )

        for r in itens[:limite]:
            print(
                f"  {r['cep']} | "
                f"{r['clientes']} | "
                f"sugerido={r['bairro_padrao_gravacao']}"
            )

            for familia in r["familias"]:
                print(
                    "      família: "
                    + formatar_familia(familia)
                )

    imprimir_secao(
        "PRINCIPAIS CASOS SEGUROS:",
        "SEGURO",
    )

    imprimir_secao(
        "PRINCIPAIS CASOS PARA REVISÃO:",
        "REVISAR",
    )

    imprimir_secao(
        "PRINCIPAIS CASOS BLOQUEADOS:",
        "BLOQUEADO",
    )

    print()
    print("=" * 90)
    print("VALIDAÇÃO DE SEGURANÇA")
    print("=" * 90)
    print("IXC UPDATE: NÃO")
    print("IXC INSERT: NÃO")
    print("IXC DELETE: NÃO")
    print("CLIENTES ALTERADOS: 0")
    print(f"RELATÓRIO: {OUT}")
    print("=" * 90)


if __name__ == "__main__":
    main()
