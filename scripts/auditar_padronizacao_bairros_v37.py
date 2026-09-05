#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.7

Transforma a auditoria V3.6.1 em decisão POR CLIENTE.

MODO:
    SOMENTE LEITURA.

NUNCA:
    UPDATE
    INSERT
    DELETE

REGRAS:

1. SEGURO:
   - se bairro atual já corresponde ao padrão -> SEM ALTERAÇÃO
   - se bairro atual diverge do padrão -> ALTERAR

2. REVISAR:
   - identifica a família dominante dentro do CEP;
   - clientes da família dominante -> ALTERAR;
   - clientes de famílias excepcionais -> PRESERVAR.

3. BLOQUEADO:
   - PRESERVAR.
   - nenhum cliente é alterado automaticamente.

4. A decisão é individual por cliente.
"""

from pathlib import Path
import csv
import re
import unicodedata
from collections import Counter, defaultdict

ROOT = Path("/opt/automacoes/jactos/cobranca")
SRC = ROOT / "backups/auditoria_padronizacao_bairros_v361_CLIENTE.txt"

OUT_TSV = ROOT / "backups/auditoria_padronizacao_bairros_v37_ACAO_CLIENTE.tsv"
OUT_TXT = ROOT / "backups/auditoria_padronizacao_bairros_v37_ACAO_CLIENTE.txt"


def normalizar(texto):
    texto = str(texto or "").strip().upper()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        c for c in texto
        if unicodedata.category(c) != "Mn"
    )
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def extrair_blocos(texto):
    """
    Extrai os blocos CLIENTE do relatório V3.6.1.
    """
    padrao = re.compile(
        r"CLIENTE\s+#(?P<id>\d+)\n"
        r"RAZÃO:\s*(?P<razao>[^\n]*)\n"
        r"FANTASIA:\s*(?P<fantasia>[^\n]*)\n"
        r"CEP:\s*(?P<cep>\d+)\n"
        r"BAIRRO ATUAL:\s*(?P<bairro>[^\n]*)\n"
        r"BAIRRO NORMALIZADO:\s*(?P<normalizado>[^\n]*)\n"
        r"FAMÍLIA:\s*(?P<familia>[^\n]*)\n"
        r"PADRÃO SUGERIDO:\s*(?P<padrao>[^\n]*)\n"
        r"STATUS:\s*(?P<status>[^\n]*)",
        re.MULTILINE,
    )

    return list(padrao.finditer(texto))


def decidir(registros):
    por_cep = defaultdict(list)

    for r in registros:
        por_cep[r["cep"]].append(r)

    decisoes = []

    for cep, itens in sorted(por_cep.items()):
        familias = Counter(
            normalizar(x["familia"])
            for x in itens
            if x["familia"].strip()
        )

        familia_dominante = (
            familias.most_common(1)[0][0]
            if familias
            else ""
        )

        for x in itens:
            status = x["status"].strip().upper()
            atual = x["bairro"].strip()
            padrao = x["padrao"].strip()

            atual_norm = normalizar(atual)
            padrao_norm = normalizar(padrao)
            familia = normalizar(x["familia"])

            if status == "SEGURO":
                if atual_norm == padrao_norm:
                    acao = "SEM ALTERACAO"
                    motivo = (
                        "Bairro atual já corresponde ao padrão sugerido."
                    )
                else:
                    acao = "ALTERAR"
                    motivo = (
                        "CEP classificado como SEGURO e bairro atual "
                        "difere do padrão sugerido."
                    )

            elif status == "REVISAR":
                if familia == familia_dominante:
                    if atual_norm == padrao_norm:
                        acao = "SEM ALTERACAO"
                        motivo = (
                            "Família dominante do CEP; bairro já "
                            "corresponde ao padrão."
                        )
                    else:
                        acao = "ALTERAR"
                        motivo = (
                            "Família dominante do CEP; alteração "
                            "individualmente aplicável."
                        )
                else:
                    acao = "PRESERVAR"
                    motivo = (
                        "Exceção de família dentro do CEP; "
                        "não alterar automaticamente."
                    )

            elif status == "BLOQUEADO":
                acao = "PRESERVAR"
                motivo = (
                    "CEP bloqueado na V3.6.1 por possuir "
                    "famílias estruturalmente distintas."
                )

            else:
                acao = "PRESERVAR"
                motivo = f"Status V3.6.1 não reconhecido: {status}"

            decisoes.append({
                "id_cliente": x["id_cliente"],
                "razao": x["razao"],
                "cep": cep,
                "bairro_atual": atual,
                "bairro_padrao": padrao,
                "familia": x["familia"],
                "familia_dominante": familia_dominante,
                "status_v361": status,
                "acao": acao,
                "motivo": motivo,
            })

    return decisoes


def main():
    if not SRC.exists():
        raise SystemExit(f"ERRO: fonte não encontrada: {SRC}")

    texto = SRC.read_text(encoding="utf-8")

    if "AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.6.1" not in texto:
        raise SystemExit(
            "ERRO: o arquivo de entrada não possui marcador V3.6.1."
        )

    matches = extrair_blocos(texto)

    if not matches:
        raise SystemExit(
            "ERRO: nenhum bloco CLIENTE foi encontrado no relatório V3.6.1."
        )

    registros = []

    for m in matches:
        registros.append({
            "id_cliente": m.group("id"),
            "razao": m.group("razao").strip(),
            "cep": m.group("cep").strip(),
            "bairro": m.group("bairro").strip(),
            "normalizado": m.group("normalizado").strip(),
            "familia": m.group("familia").strip(),
            "padrao": m.group("padrao").strip(),
            "status": m.group("status").strip(),
        })

    decisoes = decidir(registros)

    contagem = Counter(x["acao"] for x in decisoes)
    status = Counter(x["status_v361"] for x in decisoes)

    alteracoes = [
        x for x in decisoes
        if x["acao"] == "ALTERAR"
    ]

    preservar = [
        x for x in decisoes
        if x["acao"] == "PRESERVAR"
    ]

    sem_alteracao = [
        x for x in decisoes
        if x["acao"] == "SEM ALTERACAO"
    ]

    campos = [
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
    ]

    with OUT_TSV.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=campos,
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(decisoes)

    with OUT_TXT.open("w", encoding="utf-8") as f:
        f.write("=" * 120 + "\n")
        f.write("AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.7\n")
        f.write("=" * 120 + "\n")
        f.write("MODO: SOMENTE LEITURA — NENHUMA ALTERAÇÃO NO IXC\n")
        f.write("BASE: auditoria_padronizacao_bairros_v361_CLIENTE.txt\n\n")

        f.write(f"Clientes analisados: {len(decisoes)}\n")
        f.write(f"Clientes ALTERAR: {len(alteracoes)}\n")
        f.write(f"Clientes PRESERVAR: {len(preservar)}\n")
        f.write(f"Clientes SEM ALTERAÇÃO: {len(sem_alteracao)}\n\n")

        f.write("DISTRIBUIÇÃO POR AÇÃO\n")
        f.write("-" * 120 + "\n")
        for chave in [
            "ALTERAR",
            "PRESERVAR",
            "SEM ALTERACAO",
        ]:
            f.write(
                f"{chave}: {contagem.get(chave, 0)}\n"
            )

        f.write("\nDISTRIBUIÇÃO POR STATUS V3.6.1\n")
        f.write("-" * 120 + "\n")
        for chave in [
            "SEGURO",
            "REVISAR",
            "BLOQUEADO",
        ]:
            f.write(
                f"{chave}: {status.get(chave, 0)}\n"
            )

        f.write("\n")
        f.write("=" * 120 + "\n")
        f.write("CLIENTES PROPOSTOS PARA ALTERAÇÃO\n")
        f.write("=" * 120 + "\n\n")

        for x in alteracoes:
            f.write(
                f"CLIENTE #{x['id_cliente']} | "
                f"CEP {x['cep']} | "
                f"{x['bairro_atual']} -> {x['bairro_padrao']} | "
                f"STATUS {x['status_v361']}\n"
            )

        f.write("\n")
        f.write("=" * 120 + "\n")
        f.write("CLIENTES PRESERVADOS\n")
        f.write("=" * 120 + "\n\n")

        for x in preservar:
            f.write(
                f"CLIENTE #{x['id_cliente']} | "
                f"CEP {x['cep']} | "
                f"{x['bairro_atual']} | "
                f"PADRÃO {x['bairro_padrao']} | "
                f"STATUS {x['status_v361']} | "
                f"{x['motivo']}\n"
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
    print("AUDITORIA DE PADRONIZAÇÃO DE BAIRROS — V3.7")
    print("=" * 110)
    print("MODO: SOMENTE LEITURA — NENHUMA ALTERAÇÃO NO IXC")
    print()
    print(f"Clientes analisados: {len(decisoes)}")
    print()
    print("DISTRIBUIÇÃO POR AÇÃO:")
    print(f"  ALTERAR:         {contagem.get('ALTERAR', 0)}")
    print(f"  PRESERVAR:       {contagem.get('PRESERVAR', 0)}")
    print(f"  SEM ALTERAÇÃO:   {contagem.get('SEM ALTERACAO', 0)}")
    print()
    print("DISTRIBUIÇÃO POR STATUS V3.6.1:")
    print(f"  SEGURO:          {status.get('SEGURO', 0)}")
    print(f"  REVISAR:         {status.get('REVISAR', 0)}")
    print(f"  BLOQUEADO:       {status.get('BLOQUEADO', 0)}")
    print()
    print("ARQUIVOS V3.7:")
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
