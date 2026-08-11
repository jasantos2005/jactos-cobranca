#!/usr/bin/env python3
"""
Cron Auditoria Retiradas — executa a cada 2h
Verifica OS 39 finalizadas com técnico válido e foto → abre OS 38 estoque
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/cliquedf/cobranca')
os.chdir('/opt/automacoes/cliquedf/cobranca')
from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)

from app.core.db import query, query_one, execute
import requests, os as _os

TECNICOS_IDS = (15,31,16,13,10,42,11,36,18,14,41,47,67,17,12,55,49,50,32,60,4,59,48,66,46)
TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHAT  = "-4989557189"

def telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except: pass

def verificar_os38():
    """Monitora OS 38:
    1. Abertas há mais de 48h — alerta
    2. Finalizadas sem baixa no comodato — alerta
    3. Finalizadas com baixa no comodato — notifica sucesso
    """
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone(timedelta(hours=-3)))

    # ── 1. OS 38 abertas há mais de 48h ──
    abertas_48h = query("""
        SELECT o.id, o.id_cliente, c.razao,
               TIMESTAMPDIFF(HOUR, o.data_abertura, NOW()) AS horas_aberta,
               u.funcionario AS tecnico
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.cliente c ON c.id=o.id_cliente
        LEFT JOIN ixcprovedor.funcionarios u ON u.id=o.id_tecnico
        WHERE o.id_assunto=38 AND o.status='A'
          AND TIMESTAMPDIFF(HOUR, o.data_abertura, NOW()) > 48
    """, ())

    # ── 2. OS 38 finalizadas sem baixa no comodato ──
    sem_baixa = query("""
        SELECT o.id, o.id_cliente, c.razao,
               DATE_FORMAT(o.data_fechamento,'%%d/%%m/%%Y') AS fechamento,
               u.funcionario AS fechado_por,
               CASE WHEN o.id_tecnico != 25 THEN 'incorreto' ELSE 'ok' END AS responsavel
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.cliente c ON c.id=o.id_cliente
        LEFT JOIN ixcprovedor.funcionarios u ON u.id=o.id_tecnico
        WHERE o.id_assunto=38 AND o.status='F'
          AND DATE(o.data_fechamento) >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
          AND o.id_cliente NOT IN (
            SELECT DISTINCT cc.id_cliente
            FROM ixcprovedor.movimento_produtos mp
            INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id=mp.id_contrato
            WHERE mp.status_comodato IN ('D','B')
          )
    """, ())

    # ── 3. OS 38 finalizadas COM baixa no comodato (hoje) ──
    com_baixa = query("""
        SELECT o.id, o.id_cliente, c.razao,
               DATE_FORMAT(o.data_fechamento,'%%d/%%m/%%Y %%H:%%i') AS fechamento,
               u.funcionario AS tecnico
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.cliente c ON c.id=o.id_cliente
        LEFT JOIN ixcprovedor.funcionarios u ON u.id=o.id_tecnico
        WHERE o.id_assunto=38 AND o.status='F'
          AND DATE(o.data_fechamento) = CURDATE()
          AND o.id_cliente IN (
            SELECT DISTINCT cc.id_cliente
            FROM ixcprovedor.movimento_produtos mp
            INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id=mp.id_contrato
            WHERE mp.status_comodato IN ('D','B')
              AND (DATE(mp.ultima_atualizacao) = CURDATE() OR mp.ultima_atualizacao IS NULL)
          )
    """, ())

    alertas = []
    sucessos = []

    if abertas_48h:
        alertas.append(f"⏰ <b>{len(abertas_48h)} OS 38 abertas há +48h (estoque pendente):</b>")
        for o in abertas_48h[:5]:
            alertas.append(f"  • #{o['id']} {o['razao']} — {o['horas_aberta']}h ({o['tecnico'] or '—'})")

    if sem_baixa:
        alertas.append(f"\n❌ <b>{len(sem_baixa)} OS 38 finalizadas SEM baixa no comodato:</b>")
        for o in sem_baixa[:5]:
            resp = f"⚠️ fechado por {o['fechado_por']}" if o.get('responsavel') == 'incorreto' else o['fechado_por'] or '—'
            alertas.append(f"  • #{o['id']} {o['razao']} — fechada {o['fechamento']} ({resp})")

    if com_baixa:
        sucessos.append(f"✅ <b>{len(com_baixa)} OS 38 finalizadas COM baixa no comodato hoje:</b>")
        for o in com_baixa[:5]:
            sucessos.append(f"  • #{o['id']} {o['razao']} — {o['fechamento']} ({o['tecnico'] or '—'})")

    if alertas:
        msg = "🔴 <b>HubCobrança — Monitoramento OS 38</b>\n\n"
        msg += "\n".join(alertas)
        msg += f"\n\n<i>{agora.strftime('%d/%m/%Y %H:%M')}</i>"
        if ENVIAR_TELEGRAM: telegram(msg)
        log(f"OS38: {len(abertas_48h)} abertas +48h | {len(sem_baixa)} sem baixa comodato")

    if sucessos:
        msg = "\n".join(sucessos)
        msg += f"\n\n<i>{agora.strftime('%d/%m/%Y %H:%M')}</i>"
        if ENVIAR_TELEGRAM: telegram(msg)
        log(f"OS38: {len(com_baixa)} finalizadas com baixa comodato hoje")

    return len(abertas_48h), len(sem_baixa), len(com_baixa)

def retirada_imediata_nunca_pagou():
    """
    Clientes que nunca pagaram:
    - Fecha OS 246 se existir
    - Abre OS 39 imediatamente
    """
    from app.core.db import query, query_one, execute
    log("=== RETIRADA IMEDIATA NUNCA PAGOU ===")

    candidatos = query("""
        SELECT cc.id_cliente, c.razao,
               DATEDIFF(CURDATE(), cc.data_ativacao) AS dias_ativado,
               MAX(DATEDIFF(CURDATE(), f.data_vencimento)) AS maior_atraso,
               SUM(f.valor_aberto) AS total_aberto
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.cliente c ON c.id=cc.id_cliente
        INNER JOIN ixcprovedor.fn_areceber f ON f.id_cliente=cc.id_cliente
            AND f.status='A' AND f.data_vencimento < CURDATE()
        WHERE cc.status='A'
          AND DATEDIFF(CURDATE(), cc.data_ativacao) <= 90
          AND cc.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber WHERE status='R'
          )
          AND cc.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto=39 AND status NOT IN ('F')
          )
        GROUP BY cc.id_cliente, c.razao, cc.data_ativacao
        HAVING maior_atraso >= 30
    """, ())

    if not candidatos:
        log("Nenhum candidato para retirada imediata")
        return 0

    log(f"Candidatos retirada imediata: {len(candidatos)}")
    abertas = 0
    for c in candidatos:
        try:
            # Fecha OS 246 se existir
            os246 = query_one("""
                SELECT id FROM ixcprovedor.su_oss_chamado
                WHERE id_cliente=%s AND id_assunto=246 AND status='A' LIMIT 1
            """, (c["id_cliente"],))
            if os246:
                execute("UPDATE ixcprovedor.su_oss_chamado SET status='F', data_fechamento=NOW() WHERE id=%s", (os246["id"],))

            # Abre OS 39
            fat = query_one("""
                SELECT id, documento FROM ixcprovedor.fn_areceber
                WHERE id_cliente=%s AND status='A' AND data_vencimento < CURDATE()
                ORDER BY data_vencimento ASC LIMIT 1
            """, (c["id_cliente"],))
            fat_info = f" | Fatura #{fat['id']} ({fat['documento']})" if fat else ""

            # Busca vendedor e Serasa no comercial
            COMERCIAL_DB = "/opt/automacoes/cliquedf/comercial/hub_comercial.db"
            conn = sqlite3.connect(COMERCIAL_DB)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT vendedor_nome FROM hc_contratos_cache WHERE ixc_cliente_id=? LIMIT 1", (c["id_cliente"],))
            row_com = cur.fetchone()
            vendedor = row_com["vendedor_nome"] if row_com else "— IXC direto"
            cur.execute("""SELECT al.resultado, al.detalhes FROM hc_precadastros p
                JOIN hc_auditoria_log al ON al.precadastro_id=p.id
                WHERE p.ixc_cliente_id=?
                AND al.resultado IN ('ok','reprovado','pendente')
                ORDER BY al.id DESC LIMIT 1""", (c["id_cliente"],))
            row_ser = cur.fetchone()
            conn.close()
            serasa = f"{row_ser['resultado'].upper()} — {row_ser['detalhes'][:50]}" if row_ser else "Não consultado"

            msg = (f"RETIRADA IMEDIATA — {c['razao']}\n"
                   f"Boleto vencido há {c['maior_atraso']}d | Ativado há {c['dias_ativado']}d\n"
                   f"Sem nenhum pagamento | R$ {float(c['total_aberto']):.2f}{fat_info}\n"
                   f"Vendedor: {vendedor}\n"
                   f"Serasa: {serasa}")
            execute("""
                INSERT INTO ixcprovedor.su_oss_chamado
                    (id_cliente, id_assunto, mensagem, data_abertura, status, setor)
                VALUES (%s, 39, %s, NOW(), 'A', 8)
            """, (c["id_cliente"], msg))
            log(f"  ✅ OS 39 aberta — {c['razao']} (boleto vencido há {c['maior_atraso']}d)")
            abertas += 1
        except Exception as e:
            log(f"  ❌ ERRO — {c['razao']}: {e}")

    if abertas > 0:
        if ENVIAR_TELEGRAM: telegram(f"🚨 <b>Retirada Imediata</b>\n{abertas} OS 39 abertas para clientes que NUNCA pagaram\n<i>IaTechHub · {now_br().strftime('%d/%m/%Y %H:%M')}</i>")
    return abertas

def main():
    agora = now_br()
    hora  = agora.hour
    # Só envia Telegram entre 6h e 18h
    ENVIAR_TELEGRAM = 6 <= hora < 18
    if not ENVIAR_TELEGRAM:
        log("Fora do horário comercial — auditoria sem notificação Telegram")
    log("=== AUDITORIA RETIRADAS ===")
    ph = ",".join(["%s"]*len(TECNICOS_IDS))

    # Busca OS 39 finalizadas HOJE com técnico válido e foto, sem OS 38 aberta
    os_validas = query(f"""
        SELECT DISTINCT o.id AS os39_id, o.id_cliente, c.razao,
               u.funcionario AS tecnico_nome, o.id_tecnico,
               o.data_fechamento,
               COUNT(a.id) AS qtd_fotos
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.cliente c ON c.id=o.id_cliente
        INNER JOIN ixcprovedor.usuarios u ON u.id=o.id_tecnico
        INNER JOIN ixcprovedor.su_oss_chamado_arquivos a ON a.id_oss_chamado=o.id
        AND (a.nome_arquivo LIKE '%%.jpg' OR a.nome_arquivo LIKE '%%.jpeg' OR a.nome_arquivo LIKE '%%.png' OR a.nome_arquivo LIKE '%%.gif' OR a.nome_arquivo LIKE '%%.webp') AND a.nome_arquivo != '/' AND a.nome_arquivo != '' AND a.descricao NOT LIKE '%%Assinatura%%'
        WHERE o.id_assunto=39 AND o.status='F'
          AND DATE(o.data_fechamento) >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
          AND o.id_tecnico IN ({ph})
          AND o.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto=38
            AND DATE(data_abertura) = CURDATE()
          )
        GROUP BY o.id, o.id_cliente, c.razao, u.funcionario, o.id_tecnico, o.data_fechamento
    """, TECNICOS_IDS)

    log(f"OS válidas para abrir OS 38: {len(os_validas)}")
    abertas = erros = 0

    for os in os_validas:
        try:
            cli = query_one("SELECT cidade FROM ixcprovedor.cliente WHERE id=%s", (os["id_cliente"],))
            id_cidade = str(cli["cidade"]) if cli and cli["cidade"] else ""
            msg_os = (f"Devolução de equipamento ao estoque\n"
                      f"Técnico: {os['tecnico_nome']}\n"
                      f"OS retirada: #{os['os39_id']}\n"
                      f"Cliente: {os['razao']}\n"
                      f"Fotos anexadas: {os['qtd_fotos']}")
            execute("""
                INSERT INTO ixcprovedor.su_oss_chamado
                    (id_cliente, id_assunto, mensagem, data_abertura, status, setor)
                VALUES (%s, 38, %s, NOW(), 'A', 9)
            """, (os["id_cliente"], msg_os))
            log(f"  ✅ OS 38 aberta — {os['razao']} (técnico: {os['tecnico_nome']})")
            abertas += 1
        except Exception as e:
            log(f"  ❌ ERRO — {os['razao']}: {e}")
            erros += 1

    # Busca OS 39 finalizadas SEM foto ou SEM técnico válido para alertar
    sem_foto = query(f"""
        SELECT o.id, c.razao, o.data_fechamento,
               u.funcionario AS tecnico
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.cliente c ON c.id=o.id_cliente
        LEFT JOIN ixcprovedor.funcionarios u ON u.id=o.id_tecnico
        LEFT JOIN ixcprovedor.su_oss_chamado_arquivos a ON a.id_oss_chamado=o.id
        WHERE o.id_assunto=39 AND o.status='F'
          AND DATE(o.data_fechamento) = CURDATE()
          AND a.id IS NULL
          AND o.mensagem NOT LIKE 'Retirada automática%%'
        GROUP BY o.id, c.razao, o.data_fechamento, u.funcionario
    """, ())

    sem_tecnico = query(f"""
        SELECT o.id, c.razao, o.data_fechamento
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.cliente c ON c.id=o.id_cliente
        WHERE o.id_assunto=39 AND o.status='F'
          AND DATE(o.data_fechamento) = CURDATE()
          AND o.mensagem NOT LIKE 'Retirada automática%%'
          AND (o.id_tecnico IS NULL OR o.id_tecnico=0
               OR o.id_tecnico NOT IN ({ph}))
    """, TECNICOS_IDS)

    if sem_foto or sem_tecnico:
        msg = "⚠️ <b>HubCobrança — AUDITORIA RETIRADAS</b>\n\n"
        if sem_foto:
            msg += f"📷 <b>{len(sem_foto)} OS sem foto hoje:</b>\n"
            for o in sem_foto[:5]:
                msg += f"  • #{o['id']} {o['razao']} ({o['tecnico'] or 'sem técnico'})\n"
        if sem_tecnico:
            msg += f"\n👷 <b>{len(sem_tecnico)} OS sem técnico válido hoje:</b>\n"
            for o in sem_tecnico[:5]:
                msg += f"  • #{o['id']} {o['razao']}\n"
        msg += f"\n<i>{now_br().strftime('%d/%m/%Y %H:%M')}</i>"
        if ENVIAR_TELEGRAM: telegram(msg)

    if abertas > 0:
        if ENVIAR_TELEGRAM: telegram(f"✅ <b>HubCobrança — Retiradas</b>\n\n{abertas} OS de devolução ao estoque abertas automaticamente.\n<i>{now_br().strftime('%d/%m/%Y %H:%M')}</i>")

    # Monitora OS 38
    ab48, sb, cb = verificar_os38()
    log(f"OS38 — abertas+48h={ab48} sem_baixa={sb} com_baixa={cb}")
    log(f"=== CONCLUÍDO — abertas={abertas} erros={erros} sem_foto={len(sem_foto)} sem_tecnico={len(sem_tecnico)} ===")

def sincronizar_agendamentos():
    """Cancela agendamentos locais de OS já fechadas no IXC"""
    from app.core.db import query
    from app.core.db_local import local_query, local_execute
    log("=== SYNC AGENDAMENTOS RETIRADAS ===")

    agendados = [r["id_os"] for r in local_query(
        "SELECT id_os FROM cob_retiradas_agendamentos WHERE status='agendado'", ())]
    if not agendados:
        log("Nenhum agendamento para verificar")
        return

    ph = ",".join(["%s"]*len(agendados))
    no_ixc = query(f"""
        SELECT id FROM ixcprovedor.su_oss_chamado
        WHERE id IN ({ph}) AND status NOT IN ('F')
    """, tuple(agendados))
    ids_abertos = {r["id"] for r in no_ixc}

    cancelados = 0
    for id_os in agendados:
        if id_os not in ids_abertos:
            local_execute("UPDATE cob_retiradas_agendamentos SET status='cancelado' WHERE id_os=?", (id_os,))
            cancelados += 1

    log(f"Agendamentos cancelados (OS fechadas no IXC): {cancelados}")
    log(f"Agendamentos ativos: {len(ids_abertos)}")

if __name__ == "__main__":
    main()
    sincronizar_agendamentos()
