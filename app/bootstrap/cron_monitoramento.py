#!/usr/bin/env python3
"""
Cron de monitoramento OS — executa diariamente às 08h
Regras:
- OS 246 aberta + cliente pagou → fecha OS 246 + fecha OS 39 (qualquer status)
- OS 246 aberta + cliente deve < 60d → aguarda
- OS 246 aberta + cliente deve >= 60d → fecha OS 246 + abre OS 39
- OS 39 (qualquer status) + cliente pagou → fecha OS 39
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/cliquedf/cobranca')
os.chdir('/opt/automacoes/cliquedf/cobranca')

from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)

from app.core.db import query, query_one, execute
from app.core.db_local import local_execute
import requests
from app.core.ixc_api import IXC_API_URL, _auth

def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)

def fechar_os_ixc(id_os: int) -> bool:
    try:
        execute("""
            UPDATE ixcprovedor.su_oss_chamado
            SET status='F', data_fechamento=NOW()
            WHERE id=%s AND status<>'F'
        """, (id_os,))
        return True
    except Exception as e:
        log(f"  [ERRO fechar_os] id_os={id_os} erro={e}")
        return False

def abrir_os_retirada_ixc(id_cliente: int, mensagem: str) -> int:
    """Abre OS 39 diretamente no banco MySQL."""
    existente = query_one("""
        SELECT id FROM ixcprovedor.su_oss_chamado
        WHERE id_cliente=%s AND id_assunto=34 AND status<>'F' LIMIT 1
    """, (id_cliente,))
    if existente:
        log(f"  OS 39 já existe para cliente {id_cliente}: #{existente['id']}")
        return existente["id"]
    try:
        from app.core.db import execute as db_execute
        db_execute("""
            INSERT INTO ixcprovedor.su_oss_chamado
                (id_cliente, id_assunto, mensagem, data_abertura, status, setor)
            VALUES (%s, 39, %s, NOW(), 'A', 8)
        """, (id_cliente, mensagem))
        nova = query_one("""
            SELECT id FROM ixcprovedor.su_oss_chamado
            WHERE id_cliente=%s AND id_assunto=34 AND status='A'
            ORDER BY data_abertura DESC LIMIT 1
        """, (id_cliente,))
        return nova["id"] if nova else 1
    except Exception as e:
        log(f"  [ERRO abrir_os_39] cliente={id_cliente} erro={e}")
        return 0

def registrar_evento(tipo, id_cliente, id_os_246, id_os_39, razao, valor, dias_atraso, obs):
    agora = now_br().strftime('%Y-%m-%d %H:%M:%S')
    local_execute("""
        INSERT INTO cob_monitoramento_os
        (executado_em, tipo, id_cliente, id_os_246, id_os_39, razao, valor, dias_atraso, obs)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (agora, tipo, id_cliente, id_os_246, id_os_39, razao, valor, dias_atraso, obs))

def retirada_acelerada_nunca_pagou():
    """
    Clientes ativados há 30+ dias que NUNCA pagaram nenhuma parcela.
    Abre OS 39 independente de ter OS 246.
    """
    from app.core.db import query, query_one, execute
    log("=== RETIRADA ACELERADA — NUNCA PAGOU ===")

    candidatos = query("""
        SELECT cc.id_cliente, c.razao, cc.data_ativacao,
               DATEDIFF(CURDATE(), cc.data_ativacao) AS dias_ativado,
               SUM(f.valor_aberto) AS total_aberto
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.cliente c ON c.id=cc.id_cliente
        INNER JOIN ixcprovedor.fn_areceber f ON f.id_cliente=cc.id_cliente
            AND f.status='A' AND f.data_vencimento < CURDATE()
        WHERE cc.status='A'
          AND DATEDIFF(CURDATE(), cc.data_ativacao) >= 30
          AND cc.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber
            WHERE status='R'
          )
          AND cc.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto=34 AND status NOT IN ('F')
          )
        GROUP BY cc.id_cliente, c.razao, cc.data_ativacao
    """, ())

    log(f"Candidatos à retirada acelerada: {len(candidatos)}")
    abertas = 0
    for c in candidatos:
        try:
            fat = query_one("""
                SELECT id, documento FROM ixcprovedor.fn_areceber
                WHERE id_cliente=%s AND status='A' AND data_vencimento < CURDATE()
                ORDER BY data_vencimento ASC LIMIT 1
            """, (c["id_cliente"],))
            fat_info = f" | Fatura #{fat['id']} ({fat['documento']})" if fat else ""
            msg = (f"RETIRADA ACELERADA — {c['razao']} ativado há {c['dias_ativado']}d "
                   f"sem nenhum pagamento. Total: R$ {float(c['total_aberto']):.2f}{fat_info}")
            execute("""
                INSERT INTO ixcprovedor.su_oss_chamado
                    (id_cliente, id_assunto, mensagem, data_abertura, status, setor)
                VALUES (%s, 39, %s, NOW(), 'A', 8)
            """, (c["id_cliente"], msg))
            log(f"  ✅ OS 39 aberta — {c['razao']} ({c['dias_ativado']}d sem pagar)")
            abertas += 1
        except Exception as e:
            log(f"  ❌ ERRO — {c['razao']}: {e}")

    if abertas > 0:
        import requests
        requests.post(
            f"https://api.telegram.org/bot8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY/sendMessage",
            data={"chat_id": "-4989557189",
                  "text": f"🚨 <b>Retirada Acelerada</b>\n{abertas} OS 39 abertas para clientes que nunca pagaram (30+ dias)\n<i>IaTechHub · {now_br().strftime('%d/%m/%Y %H:%M')}</i>",
                  "parse_mode": "HTML"}, timeout=10)
    log(f"Retirada acelerada concluída — {abertas} OS abertas")
    return abertas

def main():
    log("=== INICIANDO CRON MONITORAMENTO ===")
    pagaram = retiradas = erros = 0

    # ── PASSO 1: Busca clientes inadimplentes com suas OS abertas ──────────────
    # Uma única query traz: cliente, OS 246, OS 39 e dias de atraso
    clientes = query("""
        SELECT
            c.id AS id_cliente,
            c.razao,
            MAX(CASE WHEN o.id_assunto=190 AND o.status='A' THEN o.id END) AS os246_id,
            MAX(CASE WHEN o.id_assunto=34  AND o.status<>'F' THEN o.id END) AS os39_id,
            MAX(DATEDIFF(CURDATE(), f.data_vencimento)) AS maior_atraso,
            SUM(f.valor_aberto) AS total_aberto,
            COUNT(f.id) AS qtd_faturas
        FROM ixcprovedor.cliente c
        INNER JOIN ixcprovedor.su_oss_chamado o ON o.id_cliente=c.id
            AND o.id_assunto IN (190,34) AND o.status<>'F'
        LEFT JOIN ixcprovedor.fn_areceber f ON f.id_cliente=c.id
            AND f.status='A' AND f.data_vencimento < CURDATE()
        LEFT JOIN ixcprovedor.cliente_contrato cc ON cc.id=f.id_contrato
            AND (cc.status IS NULL OR cc.status='A')
        WHERE c.ativo='S'
        GROUP BY c.id, c.razao
    """, ())
    # Inclui também clientes com só OS 39 aberta que podem ter pago
    clientes_os39_only = query("""
        SELECT
            c.id AS id_cliente,
            c.razao,
            NULL AS os246_id,
            MAX(o.id) AS os39_id,
            MAX(DATEDIFF(CURDATE(), f.data_vencimento)) AS maior_atraso,
            SUM(f.valor_aberto) AS total_aberto,
            COUNT(f.id) AS qtd_faturas
        FROM ixcprovedor.cliente c
        INNER JOIN ixcprovedor.su_oss_chamado o ON o.id_cliente=c.id
            AND o.id_assunto=34 AND o.status NOT IN ('F')
        LEFT JOIN ixcprovedor.fn_areceber f ON f.id_cliente=c.id
            AND f.status='A' AND f.data_vencimento < CURDATE()
        LEFT JOIN ixcprovedor.cliente_contrato cc ON cc.id=f.id_contrato
            AND (cc.status IS NULL OR cc.status='A')
        WHERE c.ativo='S'
        AND c.id NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto=190 AND status='A'
        )
        GROUP BY c.id, c.razao
    """, ())
    # Combina evitando duplicatas
    ids_ja = {c["id_cliente"] for c in clientes}
    clientes = list(clientes) + [c for c in clientes_os39_only if c["id_cliente"] not in ids_ja]

    log(f"Clientes com OS abertas: {len(clientes)}")

    for cli in clientes:
        id_cli      = cli["id_cliente"]
        razao       = cli["razao"] or "—"
        os246       = cli["os246_id"]
        os39        = cli["os39_id"]
        atraso      = int(cli["maior_atraso"] or 0)
        total       = float(cli["total_aberto"] or 0)
        tem_divida  = cli["qtd_faturas"] and int(cli["qtd_faturas"]) > 0

        # ── Cliente PAGOU ──────────────────────────────────────────────────────
        if not tem_divida:
            log(f"  ✅ PAGOU: {razao} (#{id_cli})")
            ok246 = ok39 = True
            if os246:
                ok246 = fechar_os_ixc(os246)
                if ok246: log(f"     OS 246 #{os246} fechada")
            if os39:
                ok39 = fechar_os_ixc(os39)
                if ok39: log(f"     OS 39 #{os39} fechada")
            if ok246 and ok39:
                registrar_evento('pagou', id_cli, os246, os39, razao, 0, 0, "Cliente quitou")
                pagaram += 1
            else:
                erros += 1
            continue

        # ── Cliente ainda DEVE ─────────────────────────────────────────────────
        if os246:
            if atraso >= 60:
                # +60 dias → fecha OS 246 e abre/mantém OS 39
                log(f"  🔴 RETIRADA: {razao} (#{id_cli}) — {atraso}d")
                ok = fechar_os_ixc(os246)
                if ok:
                    # Verifica se já tem OS 39 aberta OU finalizada nos últimos 30 dias
                    from app.core.db import query_one as qo
                    os39_recente = qo("""
                        SELECT id FROM ixcprovedor.su_oss_chamado
                        WHERE id_cliente=%s AND id_assunto=34
                        AND (status NOT IN ('F') OR DATE(data_fechamento) >= DATE_SUB(CURDATE(), INTERVAL 30 DAY))
                        ORDER BY data_abertura DESC LIMIT 1
                    """, (id_cli,))
                    if not os39_recente:
                        # Busca fatura em aberto para incluir na mensagem
                        fat = qo("""
                            SELECT id, documento, valor_aberto
                            FROM ixcprovedor.fn_areceber
                            WHERE id_cliente=%s AND status='A'
                            AND data_vencimento < CURDATE()
                            ORDER BY data_vencimento ASC LIMIT 1
                        """, (id_cli,))
                        fat_info = f" | Fatura #{fat['id']} ({fat['documento']}) R$ {float(fat['valor_aberto']):.2f}" if fat else ""
                        msg = f"Retirada automática — {razao} com {atraso}d inadimplente. Total: R$ {total:.2f}{fat_info}"
                        os39_novo = abrir_os_retirada_ixc(id_cli, msg)
                        registrar_evento('retirada', id_cli, os246, os39_novo or None, razao, total, atraso, f"{atraso}d")
                        retiradas += 1
                    else:
                        log(f"     OS 39 #{os39_recente['id']} já existe — mantida")
                else:
                    erros += 1
            else:
                log(f"  ⏳ AGUARDANDO: {razao} (#{id_cli}) — {atraso}d")

    # Registra execução
    agora_br = now_br().strftime('%Y-%m-%d %H:%M:%S')
    local_execute("""
        INSERT INTO cob_monitoramento_execucoes (executado_em, pagaram, retiradas, erros, obs)
        VALUES (?,?,?,?,?)
    """, (agora_br, pagaram, retiradas, erros, f"Clientes verificados: {len(clientes)}"))
    log(f"=== CONCLUÍDO: pagaram={pagaram} retiradas={retiradas} erros={erros} ===")
    retirada_acelerada_nunca_pagou()

if __name__ == "__main__":
    main()
