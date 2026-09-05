#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.6

OBJETIVO
--------
Auditar o campo cliente.bairro do IXC para clientes de Goiânia,
identificando famílias semanticamente equivalentes e separando
casos que exigem revisão humana.

IMPORTANTE
----------
ESTE SCRIPT É 100% SOMENTE LEITURA.

Não executa:
    UPDATE
    INSERT
    DELETE

Não altera nenhuma informação no IXC.

A V3.6 melhora a V3.5 nos seguintes pontos:

1. Universo restrito a Goiânia.
2. Normalização de acentos, caixa e espaços.
3. Tratamento controlado de prefixos:
       SETOR
       BAIRRO
       RESIDENCIAL
       LOTEAMENTO
4. Pequenos erros de grafia podem ser agrupados.
5. Numerais/etapas continuam sendo preservados.
6. Famílias estruturalmente diferentes não são misturadas.
7. Resultado final é produzido cliente por cliente.
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

OUT_TSV = OUT_DIR / "auditoria_padronizacao_bairros_v3_6_CLIENTE.tsv"
OUT_TXT = OUT_DIR / "auditoria_padronizacao_bairros_v3_6_CLIENTE.txt"


PREFIXOS_EQUIVALENTES = (
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

    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(
        c for c in valor
        if unicodedata.category(c) != "Mn"
    )

    valor = re.sub(r"\s+", " ", valor)

    return valor.strip()


def normalizar_cep(valor):
    digits = "".join(
        c for c in str(valor or "")
        if c.isdigit()
    )

    return digits if len(digits) == 8 else ""


def remover_prefixo_equivalente(texto):
    texto = normalizar_texto(texto)

    for prefixo in PREFIXOS_EQUIVALENTES:
        if texto.startswith(prefixo + " "):
            return texto[len(prefixo):].strip()

    return texto


def preservar_identificadores(texto):
    """
    Não remove números de etapas/identificadores.

    Exemplos:
        VILA MUTIRAO
        VILA MUTIRAO I
        VILA MUTIRAO II

    permanecem diferentes.
    """
    return texto


def distancia_levenshtein(a, b):
    if a == b:
        return 0

    if not a:
        return len(b)

    if not b:
        return len(a)

    anterior = list(range(len(b) + 1))

    for i, ca in enumerate(a, 1):
        atual = [i]

        for j, cb in enumerate(b, 1):
            atual.append(
                min(
                    atual[-1] + 1,
                    anterior[j] + 1,
                    anterior[j - 1] + (ca != cb),
                )
            )

        anterior = atual

    return anterior[-1]


def similaridade(a, b):
    a = normalizar_texto(a)
    b = normalizar_texto(b)

    if not a and not b:
        return 1.0

    distancia = distancia_levenshtein(a, b)
    tamanho = max(len(a), len(b))

    if tamanho == 0:
        return 1.0

    return 1.0 - (distancia / tamanho)


def chave_familia(bairro):
    """
    Produz uma chave semântica conservadora.

    Primeiro remove apenas prefixos administrativos conhecidos.

    Não remove:
        I
        II
        III
        IV
        1ª ETAPA
        2ª ETAPA
        números de identificação

    Isso evita juntar bairros diferentes.
    """
    texto = normalizar_texto(bairro)
    texto = remover_prefixo_equivalente(texto)
    texto = preservar_identificadores(texto)
    return texto


def parecem_mesma_familia(a, b):
    ka = chave_familia(a)
    kb = chave_familia(b)

    if ka == kb:
        return True

    # Evita comparar nomes muito pequenos.
    if len(ka) < 7 or len(kb) < 7:
        return False

    sim = similaridade(ka, kb)

    # Erros pequenos de digitação.
    if sim >= 0.94:
        return True

    # Para nomes maiores, admite diferença ligeiramente maior.
    if len(ka) >= 16 and sim >= 0.90:
        return True

    return False


def construir_familias(registros):
    """
    Agrupa variantes de bairro por similaridade semântica.

    O algoritmo é conservador:
    uma variante somente entra numa família quando é suficientemente
    semelhante a uma das variantes já pertencentes à família.
    """

    familias = []

    for registro in registros:
        bairro = str(registro.get("bairro") or "").strip()

        if not bairro:
            continue

        colocado = False

        for familia in familias:
            if any(
                parecem_mesma_familia(
                    bairro,
                    existente["bairro"]
                )
                for existente in familia
            ):
                familia.append({
                    "bairro": bairro,
                    "cliente_id": registro.get("id"),
                })
                colocado = True
                break

        if not colocado:
            familias.append([
                {
                    "bairro": bairro,
                    "cliente_id": registro.get("id"),
                }
            ])

    return familias


def resumir_familia(familia):
    contagem = Counter(
        item["bairro"]
        for item in familia
    )

    partes = []

    for bairro, quantidade in sorted(
        contagem.items(),
        key=lambda x: (-x[1], normalizar_texto(x[0]))
    ):
        partes.append(
            f"{bairro} [{quantidade}]"
        )

    return " | ".join(partes)


def escolher_padrao(familia):
    """
    Mantém como padrão a grafia real mais frequente no IXC.

    Não inventa um nome novo.
    """
    contagem = Counter(
        item["bairro"]
        for item in familia
    )

    return sorted(
        contagem.items(),
        key=lambda x: (
            -x[1],
            len(x[0]),
            normalizar_texto(x[0]),
        )
    )[0][0]


def analisar_cep(registros):
    familias = construir_familias(registros)

    familias = sorted(
        familias,
        key=lambda f: -len(f)
    )

    if not familias:
        return {
            "status": "BLOQUEADO",
            "padrao": "",
            "motivo": "Nenhum bairro válido encontrado.",
            "familias": [],
        }

    total = len(registros)
    principal = len(familias[0])

    percentual = (
        principal / total * 100
        if total
        else 0
    )

    resumo_familias = [
        {
            "quantidade": len(f),
            "padrao": escolher_padrao(f),
            "detalhes": resumir_familia(f),
        }
        for f in familias
    ]

    if len(familias) == 1:
        status = "SEGURO"
        motivo = (
            "Todas as variantes do CEP pertencem à mesma "
            "família semântica."
        )

    elif percentual >= 95:
        status = "REVISAR"
        motivo = (
            f"A família dominante possui {percentual:.2f}% "
            "dos clientes, mas existem outras famílias."
        )

    else:
        status = "BLOQUEADO"
        motivo = (
            "CEP possui famílias de bairros estruturalmente "
            "distintas."
        )

    return {
        "status": status,
        "padrao": escolher_padrao(familias[0]),
        "motivo": motivo,
        "familias": resumo_familias,
    }


def carregar_clientes_goiania():
    """
    Restrição de universo:

    Goiânia possui cidade = 5412 no IXC utilizado neste projeto.

    A UF é mantida no resultado para auditoria.
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


def main():
    OUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 110)
    print("AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.6")
    print("=" * 110)
    print(
        "MODO: SOMENTE LEITURA — "
        "NENHUMA ALTERAÇÃO NO IXC"
    )
    print("UNIVERSO: GOIÂNIA — cidade=5412")
    print()

    clientes = carregar_clientes_goiania()

    grupos = {}

    for cliente in clientes:
        cep = normalizar_cep(cliente.get("cep"))

        if not cep:
            continue

        grupos.setdefault(cep, []).append(cliente)

    analises = {}

    for cep, registros in grupos.items():
        analises[cep] = analisar_cep(registros)

    distribuicao = Counter(
        resultado["status"]
        for resultado in analises.values()
    )

    print(
        f"Clientes retornados de Goiânia: {len(clientes)}"
    )
    print(
        f"Clientes exportados: "
        f"{sum(len(v) for v in grupos.values())}"
    )
    print(f"CEPs analisados: {len(grupos)}")
    print()

    print("DISTRIBUIÇÃO V3.6:")
    for status in (
        "SEGURO",
        "REVISAR",
        "BLOQUEADO",
    ):
        print(
            f"  {status}: "
            f"{distribuicao.get(status, 0)}"
        )

    # ---------------------------------------------------------
    # TSV
    # ---------------------------------------------------------

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

            familia = (
                chave_familia(
                    resultado["padrao"]
                )
            )

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
                    normalizar_texto(bairro),
                    familia,
                    resultado["status"],
                    resultado["padrao"],
                    resultado["motivo"],
                ])

                total_exportado += 1

    # ---------------------------------------------------------
    # TXT COMPLETO
    # ---------------------------------------------------------

    with OUT_TXT.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write("=" * 120 + "\n")
        f.write(
            "AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.6\n"
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
            f"Clientes retornados: {len(clientes)}\n"
        )
        f.write(
            f"Clientes exportados: {total_exportado}\n"
        )
        f.write(
            f"CEPs analisados: {len(grupos)}\n\n"
        )

        f.write("DISTRIBUIÇÃO V3.6:\n")

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
                f"STATUS: {resultado['status']}\n"
            )
            f.write(
                f"PADRÃO SUGERIDO: "
                f"{resultado['padrao']}\n"
            )
            f.write(
                f"MOTIVO: {resultado['motivo']}\n"
            )

            f.write("\nFAMÍLIAS IDENTIFICADAS:\n")

            for familia in resultado["familias"]:
                f.write(
                    f"  {familia['quantidade']} clientes | "
                    f"{familia['padrao']} | "
                    f"{familia['detalhes']}\n"
                )

            f.write("\nCLIENTES:\n")
            f.write("-" * 120 + "\n")

            for cliente in registros:

                bairro = str(
                    cliente.get("bairro") or ""
                ).strip()

                f.write(
                    f"CLIENTE #{cliente.get('id')}\n"
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
                    f"BAIRRO ATUAL: {bairro}\n"
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

        f.write("=" * 120 + "\n")
        f.write("FIM DA AUDITORIA V3.6\n")
        f.write("=" * 120 + "\n")
        f.write("IXC UPDATE: NÃO\n")
        f.write("IXC INSERT: NÃO\n")
        f.write("IXC DELETE: NÃO\n")
        f.write("CLIENTES ALTERADOS: 0\n")

    print()
    print("=" * 110)
    print("ARQUIVOS V3.6 GERADOS")
    print("=" * 110)
    print(f"TSV: {OUT_TSV}")
    print(f"TXT: {OUT_TXT}")
    print()
    print(
        f"Clientes no TSV: {total_exportado}"
    )
    print(
        f"Tamanho TSV: {OUT_TSV.stat().st_size:,} bytes"
    )
    print(
        f"Tamanho TXT: {OUT_TXT.stat().st_size:,} bytes"
    )
    print()
    print("IXC UPDATE: NÃO")
    print("IXC INSERT: NÃO")
    print("IXC DELETE: NÃO")
    print("CLIENTES ALTERADOS: 0")
    print("=" * 110)


if __name__ == "__main__":
    main()
