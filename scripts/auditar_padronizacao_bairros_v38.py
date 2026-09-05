#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.8

Segunda camada de segurança sobre a V3.7.

IMPORTANTE:
    SOMENTE LEITURA.
    Nenhum UPDATE.
    Nenhum INSERT.
    Nenhum DELETE.

Objetivo:
    Separar correções ortográficas inequívocas de alterações
    meramente cadastrais/subjetivas.

Categorias:

    CORREÇÃO_SEGURA
        Erro ortográfico/formatação inequívoco.

    PADRONIZAÇÃO_REVISAR
        Mesma família semântica, mas existe decisão cadastral
        que não deve ser tomada automaticamente.

    PRESERVAR
        Diferença potencialmente real.

    SEM_ALTERAÇÃO
        Bairro já corresponde ao padrão.

Nunca decidir automaticamente:
    SETOR X <-> X
    BAIRRO X <-> X
    RESIDENCIAL X <-> X
    JARDIM X <-> X

quando ambas as formas são semanticamente válidas.
"""

from pathlib import Path
import csv
import re
import unicodedata
from collections import Counter

ROOT = Path("/opt/automacoes/jactos/cobranca")
SRC = ROOT / "backups/auditoria_padronizacao_bairros_v37_ACAO_CLIENTE.tsv"

OUT_TSV = ROOT / "backups/auditoria_padronizacao_bairros_v38_CLIENTE.tsv"
OUT_TXT = ROOT / "backups/auditoria_padronizacao_bairros_v38_CLIENTE.txt"


PREFIXOS = (
    "SETOR ",
    "BAIRRO ",
    "RESIDENCIAL ",
    "LOTEAMENTO ",
    "CONJUNTO ",
)


def sem_acento(texto):
    texto = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(
        c for c in texto
        if unicodedata.category(c) != "Mn"
    )


def normalizar(texto):
    texto = sem_acento(texto)
    texto = texto.upper()
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def remover_prefixo(texto):
    valor = normalizar(texto)

    mudou = True
    while mudou:
        mudou = False

        for prefixo in PREFIXOS:
            if valor.startswith(prefixo):
                valor = valor[len(prefixo):].strip()
                mudou = True
                break

    return valor


def tokens(texto):
    return [
        x for x in re.split(r"[^A-Z0-9]+", normalizar(texto))
        if x
    ]


def distancia(a, b):
    a = normalizar(a)
    b = normalizar(b)

    if a == b:
        return 0

    if abs(len(a) - len(b)) > 3:
        return 99

    anterior = list(range(len(b) + 1))

    for i, ca in enumerate(a, 1):
        atual = [i]

        for j, cb in enumerate(b, 1):
            custo = 0 if ca == cb else 1

            atual.append(
                min(
                    atual[-1] + 1,
                    anterior[j] + 1,
                    anterior[j - 1] + custo,
                )
            )

        anterior = atual

    return anterior[-1]


def mesma_base(a, b):
    return remover_prefixo(a) == remover_prefixo(b)


def erro_ortografico(a, b):
    """
    Detecta somente pequenas diferenças de escrita.

    Não considera prefixos como erro ortográfico.
    """

    na = normalizar(a)
    nb = normalizar(b)

    if na == nb:
        return False

    base_a = remover_prefixo(a)
    base_b = remover_prefixo(b)

    if base_a == base_b:
        return False

    d = distancia(base_a, base_b)

    ta = tokens(base_a)
    tb = tokens(base_b)

    if d <= 1:
        return True

    if d == 2 and len(base_a) >= 8 and len(base_b) >= 8:
        return True

    # Erros evidentes de palavra única.
    if len(ta) == len(tb) and len(ta) > 0:
        diferencas = 0

        for x, y in zip(ta, tb):
            if x != y:
                diferencas += 1

        if diferencas == 1:
            pares = [
                (x, y)
                for x, y in zip(ta, tb)
                if x != y
            ]

            if pares:
                px, py = pares[0]
                if distancia(px, py) <= 2 and len(px) >= 5:
                    return True

    return False


def decidir(row):
    atual = row["bairro_atual"].strip()
    padrao = row["bairro_padrao"].strip()
    status = row["status_v361"].strip().upper()

    if normalizar(atual) == normalizar(padrao):
        return (
            "SEM_ALTERACAO",
            "Bairro atual já corresponde ao padrão."
        )

    if status == "BLOQUEADO":
        return (
            "PRESERVAR",
            "CEP bloqueado pela V3.6.1."
        )

    if mesma_base(atual, padrao):
        return (
            "PADRONIZACAO_REVISAR",
            "Mesma base semântica, mas diferença de prefixo "
            "ou convenção cadastral. Não alterar automaticamente."
        )

    if erro_ortografico(atual, padrao):
        return (
            "CORRECAO_SEGURA",
            "Diferença ortográfica pequena e inequívoca."
        )

    return (
        "PRESERVAR",
        "Diferença não suficientemente segura para alteração automática."
    )


def main():
    if not SRC.exists():
        raise SystemExit(f"ERRO: fonte não encontrada: {SRC}")

    with SRC.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)

    if not rows:
        raise SystemExit("ERRO: V3.7 não possui registros.")

    required = {
        "id_cliente",
        "razao",
        "cep",
        "bairro_atual",
        "bairro_padrao",
        "familia",
        "familia_dominante",
        "status_v361",
        "acao",
        "motivo",
    }

    missing = required - set(rows[0].keys())

    if missing:
        raise SystemExit(
            f"ERRO: colunas ausentes na V3.7: {sorted(missing)}"
        )

    saida = []

    for row in rows:
        nova_acao, novo_motivo = decidir(row)

        saida.append({
            **row,
            "acao_v38": nova_acao,
            "motivo_v38": novo_motivo,
        })

    contador = Counter(x["acao_v38"] for x in saida)

    with OUT_TSV.open(
        "w",
        encoding="utf-8",
        newline=""
    ) as f:

        campos = list(saida[0].keys())

        writer = csv.DictWriter(
            f,
            fieldnames=campos,
            delimiter="\t"
        )

        writer.writeheader()
        writer.writerows(saida)

    grupos = Counter()

    for x in saida:
        if x["acao_v38"] == "CORRECAO_SEGURA":
            chave = (
                x["bairro_atual"].strip(),
                x["bairro_padrao"].strip(),
            )
            grupos[chave] += 1

    with OUT_TXT.open("w", encoding="utf-8") as f:
        f.write("=" * 120 + "\n")
        f.write("AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.8\n")
        f.write("=" * 120 + "\n")
        f.write("MODO: SOMENTE LEITURA — NENHUMA ALTERAÇÃO NO IXC\n\n")

        f.write(f"Clientes analisados: {len(saida)}\n\n")

        f.write("DISTRIBUIÇÃO POR AÇÃO V3.8\n")
        f.write("-" * 120 + "\n")

        for chave in [
            "CORRECAO_SEGURA",
            "PADRONIZACAO_REVISAR",
            "PRESERVAR",
            "SEM_ALTERACAO",
        ]:
            f.write(
                f"{chave}: {contador.get(chave, 0)}\n"
            )

        f.write("\n")
        f.write("=" * 120 + "\n")
        f.write("CORREÇÕES ORTOGRÁFICAS SEGURAS\n")
        f.write("=" * 120 + "\n\n")

        for (atual, padrao), quantidade in grupos.most_common():
            f.write(
                f"{quantidade:5d} | "
                f"{atual} -> {padrao}\n"
            )

        f.write("\n")
        f.write("=" * 120 + "\n")
        f.write("EXEMPLOS DE PADRONIZAÇÃO QUE NÃO SERÁ AUTOMATIZADA\n")
        f.write("=" * 120 + "\n\n")

        exemplos = [
            x for x in saida
            if x["acao_v38"] == "PADRONIZACAO_REVISAR"
        ][:100]

        for x in exemplos:
            f.write(
                f"CLIENTE #{x['id_cliente']} | "
                f"CEP {x['cep']} | "
                f"{x['bairro_atual']} -> {x['bairro_padrao']}\n"
            )

        f.write("\n")
        f.write("=" * 120 + "\n")
        f.write("VALIDAÇÃO DE SEGURANÇA\n")
        f.write("=" * 120 + "\n")
        f.write("IXC UPDATE: NÃO\n")
        f.write("IXC INSERT: NÃO\n")
        f.write("IXC DELETE: NÃO\n")
        f.write("CLIENTES ALTERADOS: 0\n")

    print("=" * 110)
    print("AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.8")
    print("=" * 110)
    print("MODO: SOMENTE LEITURA — NENHUMA ALTERAÇÃO NO IXC")
    print()
    print(f"Clientes analisados: {len(saida)}")
    print()
    print("DISTRIBUIÇÃO POR AÇÃO:")
    print(
        f"  CORRECAO_SEGURA:       "
        f"{contador.get('CORRECAO_SEGURA', 0)}"
    )
    print(
        f"  PADRONIZACAO_REVISAR:  "
        f"{contador.get('PADRONIZACAO_REVISAR', 0)}"
    )
    print(
        f"  PRESERVAR:             "
        f"{contador.get('PRESERVAR', 0)}"
    )
    print(
        f"  SEM ALTERACAO:         "
        f"{contador.get('SEM_ALTERACAO', 0)}"
    )
    print()
    print("ARQUIVOS:")
    print(f"TSV: {OUT_TSV}")
    print(f"TXT: {OUT_TXT}")
    print()
    print("IXC UPDATE: NÃO")
    print("IXC INSERT: NÃO")
    print("IXC DELETE: NÃO")
    print("CLIENTES ALTERADOS: 0")
    print("=" * 110)


if __name__ == "__main__":
    main()
