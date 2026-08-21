#!/usr/bin/env python3
"""
Cron Bloqueio Antecipado — roda diariamente as 6h
Bloqueia clientes recém-ativados que não pagaram nenhuma parcela após 3 dias de vencimento
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/jactos/cobranca')
os.chdir('/opt/automacoes/jactos/cobranca')
from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)
import requests
from app.core.db import query, execute

TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHAT  = "-4989557189"

def telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        log(f"[TELEGRAM ERRO] {e}")

def main():
    log("=== BLOQUEIO ANTECIPADO NUNCA PAGOU ===")

    candidatos = query("""
        SELECT cc.id AS contrato_id, cc.id_cliente, c.razao,
               DATEDIFF(CURDATE(), cc.data_ativacao) AS dias_ativado,
               MAX(DATEDIFF(CURDATE(), f.data_vencimento)) AS dias_atraso,
               SUM(f.valor_aberto) AS total_aberto
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.cliente c ON c.id=cc.id_cliente
        INNER JOIN ixcprovedor.fn_areceber f ON f.id_cliente=cc.id_cliente
            AND f.status='A' AND f.data_vencimento < CURDATE()
        WHERE cc.status='A'
          AND cc.status_internet='A'
          AND DATEDIFF(CURDATE(), cc.data_ativacao) <= 90
          AND cc.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber WHERE status='R'
          )
        GROUP BY cc.id, cc.id_cliente, c.razao, cc.data_ativacao
        HAVING dias_atraso >= 2
    """, ())

    if not candidatos:
        log("Nenhum cliente para bloqueio antecipado")
        return

    log(f"Clientes para bloquear: {len(candidatos)}")
    bloqueados = 0
    linhas = [
        "🔒 <b>BLOQUEIO ANTECIPADO — Nunca Pagaram</b>",
        f"Clientes recém-ativados bloqueados preventivamente",
        "",
    ]

    from app.core.db_local import local_query, local_execute
    for c in candidatos:
        # Verifica nao_bloquear_ate
        nba = c.get("nao_bloquear_ate")
        if nba:
            try:
                from datetime import datetime
                nba_date = nba if isinstance(nba, type(hoje)) else datetime.strptime(str(nba), "%Y-%m-%d").date()
                if nba_date >= hoje:
                    log(f"  ⏭ {c['razao']} — não bloquear até {nba_date.strftime('%d/%m/%Y')}")
                    ignorados += 1
                    continue
            except: pass
        try:
            execute("""
                UPDATE ixcprovedor.cliente_contrato
                SET status_internet='CM', dt_ult_bloq_manual=CURDATE()
                WHERE id=%s AND status_internet='A'
            """, (c["contrato_id"],))
            # Registra no banco local
            ja_registrado = local_query("SELECT id FROM cob_bloqueios_antecipados WHERE cliente_id=? AND desbloqueado_em IS NULL", (c["id_cliente"],))
            if not ja_registrado:
                local_execute("""INSERT INTO cob_bloqueios_antecipados
                    (cliente_id, razao, bloqueado_em, dias_atraso)
                    VALUES (?,?,?,?)""",
                    (c["id_cliente"], c["razao"], now_br().strftime('%Y-%m-%d %H:%M:%S'), c["dias_atraso"]))
            log(f"  🔒 Bloqueado — {c['razao']} ({c['dias_atraso']}d atraso | {c['dias_ativado']}d ativado)")
            linhas.append(f"  • <b>{c['razao']}</b> — {c['dias_atraso']}d atraso | R$ {float(c['total_aberto']):.2f}")
            bloqueados += 1
        except Exception as e:
            log(f"  ❌ ERRO — {c['razao']}: {e}")

    # Verifica se algum bloqueado anterior foi desbloqueado sem pagar
    registrados = local_query("SELECT cliente_id, razao, bloqueado_em FROM cob_bloqueios_antecipados WHERE desbloqueado_em IS NULL AND alertado=0", ())
    if registrados:
        ids_reg = tuple(r["cliente_id"] for r in registrados)
        ph = ",".join(["%s"]*len(ids_reg))
        desbloqueados = query(f"""
            SELECT cc.id_cliente, c.razao, cc.status_internet,
                   cc.dt_ult_desbloq_manual, cc.dt_ult_desbloq_auto,
                   cc.desbloqueio_confianca_ativo
            FROM ixcprovedor.cliente_contrato cc
            INNER JOIN ixcprovedor.cliente c ON c.id=cc.id_cliente
            WHERE cc.id_cliente IN ({ph})
              AND cc.status='A'
              AND cc.status_internet != 'CM'
              AND cc.id_cliente NOT IN (
                SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber WHERE status='R'
              )
        """, ids_reg)

        if desbloqueados:
            alert_linhas = ["🚨 <b>ALERTA — Clientes desbloqueados sem pagar!</b>", ""]
            for d in desbloqueados:
                motivo = "Central do assinante" if d["desbloqueio_confianca_ativo"] == "S" else "Manual/Atendente"
                alert_linhas.append(f"  • <b>{d['razao']}</b> — desbloqueado via {motivo}")
                local_execute("UPDATE cob_bloqueios_antecipados SET desbloqueado_em=?, desbloqueado_por=?, alertado=1 WHERE cliente_id=? AND desbloqueado_em IS NULL",
                    (now_br().strftime('%Y-%m-%d %H:%M:%S'), motivo, d["id_cliente"]))
            alert_linhas.append(f"\n<i>IaTechHub · {now_br().strftime('%d/%m/%Y %H:%M')}</i>")
            telegram("\n".join(alert_linhas))
            log(f"Alerta desbloqueio: {len(desbloqueados)} clientes")

    if bloqueados > 0:
        linhas.append(f"\n<i>IaTechHub · {now_br().strftime('%d/%m/%Y %H:%M')}</i>")
        telegram("\n".join(linhas))
    log(f"Concluído — {bloqueados} clientes bloqueados")

def alertar_novos_sem_pagamento():
    """Alerta no grupo os novos clientes que não pagaram o 1º boleto"""
    from app.core.db import query
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone(timedelta(hours=-3)))

    candidatos = query("""
        SELECT c.razao,
               COALESCE(c.whatsapp, c.telefone_celular, c.fone,'') AS telefone,
               cc.data_ativacao,
               DATEDIFF(CURDATE(), cc.data_ativacao) AS dias_ativado,
               MIN(f.data_vencimento) AS primeiro_venc,
               DATEDIFF(CURDATE(), MIN(f.data_vencimento)) AS dias_atraso,
               cc.status_internet
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.cliente c ON c.id=cc.id_cliente
        INNER JOIN ixcprovedor.fn_areceber f ON f.id_cliente=cc.id_cliente
            AND f.status='A' AND f.data_vencimento < CURDATE()
            AND f.data_vencimento >= cc.data_ativacao
        WHERE cc.status='A'
          AND DATEDIFF(CURDATE(), cc.data_ativacao) <= 90
          AND cc.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber WHERE status='R'
          )
        GROUP BY c.razao, c.whatsapp, c.telefone_celular, c.fone,
                 cc.data_ativacao, cc.status_internet
        HAVING dias_atraso >= 1
        ORDER BY dias_atraso DESC
    """, ())

    if not candidatos:
        log("Nenhum novo cliente sem pagamento")
        return

    log(f"Novos sem pagamento: {len(candidatos)}")

    bloqueados  = [r for r in candidatos if r["status_internet"] == "CM"]
    desbloq     = [r for r in candidatos if r["status_internet"] != "CM"]

    linhas = [
        f"🚨 <b>NOVOS CLIENTES SEM PAGAMENTO</b>",
        f"📅 {agora.strftime('%d/%m/%Y %H:%M')} | Total: {len(candidatos)}",
        ""
    ]

    if desbloq:
        linhas.append(f"🔴 <b>Sem bloqueio ({len(desbloq)}) — cobrar HOJE:</b>")
        for r in desbloq[:8]:
            linhas.append(f"  • <b>{r['razao']}</b> — {r['telefone']} | {r['dias_atraso']}d atraso")
        linhas.append("")

    if bloqueados:
        linhas.append(f"🔒 <b>Já bloqueados ({len(bloqueados)}):</b>")
        for r in bloqueados[:5]:
            linhas.append(f"  • <b>{r['razao']}</b> — {r['dias_atraso']}d atraso")
        linhas.append("")

    linhas.append(f"<i>IaTechHub · {agora.strftime('%d/%m/%Y %H:%M')}</i>")
    telegram("\n".join(linhas))
    log(f"Alerta enviado — {len(candidatos)} clientes")

if __name__ == "__main__":
    main()
    alertar_novos_sem_pagamento()
