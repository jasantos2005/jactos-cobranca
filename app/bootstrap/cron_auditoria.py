#!/usr/bin/env python3
"""
Cron de Auditoria e Auto-Correção — executa a cada 2h
Filosofia: corrige silenciosamente, alerta só quando não consegue.
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/jactos/cobranca')
os.chdir('/opt/automacoes/jactos/cobranca')

from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)

from app.core.db import query, query_one, execute
from app.core.db_local import local_query, local_query_one, local_execute
import requests

TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHAT  = "-4989557189"

def telegram(msg: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        log(f"[TELEGRAM ERRO] {e}")

def registrar(tipo, descricao, corrigido, obs=""):
    local_execute("""
        INSERT INTO cob_auditoria (executado_em, tipo, descricao, corrigido, obs)
        VALUES (?,?,?,?,?)
    """, (now_br().strftime('%Y-%m-%d %H:%M:%S'), tipo, descricao, 1 if corrigido else 0, obs))

# ── 1. VERIFICA TOKEN IXC ─────────────────────────────────────────────────────
def checar_token_ixc():
    from app.core.ixc_api import IXC_API_URL, _auth
    try:
        r = requests.get(
            f"{IXC_API_URL}/webservice/v1/cliente?id=1",
            headers={"Authorization": _auth(), "ixcsoft": ""},
            timeout=10
        )
        if r.status_code == 401:
            log("⚠️ Token IXC inválido (401)")
            telegram("⚠️ <b>HubCobrança — ALERTA</b>\n\nToken da API IXC está inválido (401).\nAções automáticas via API estão falhando.\n\n🔧 Acesse o IXC e gere um novo token.")
            registrar("token_ixc", "Token IXC retornou 401", False, "Requer intervenção manual")
            return False
        log("✅ Token IXC OK")
        return True
    except Exception as e:
        log(f"⚠️ Erro ao verificar token IXC: {e}")
        telegram(f"⚠️ <b>HubCobrança — ALERTA</b>\n\nErro ao conectar na API IXC:\n<code>{e}</code>")
        return False

# ── 2. FECHA OS 39 DE QUEM PAGOU ─────────────────────────────────────────────
def corrigir_os39_pagos():
    # Busca clientes com OS 39 aberta que NÃO têm mais nenhuma fatura em aberto
    clientes = query("""
        SELECT DISTINCT c.id, c.razao, o.id AS os39_id
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.cliente c ON c.id=o.id_cliente
        WHERE o.id_assunto=34 AND o.status NOT IN ('F')
        AND NOT EXISTS (
            SELECT 1 FROM ixcprovedor.fn_areceber f2
            INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id=f2.id_contrato
            WHERE f2.id_cliente=o.id_cliente AND f2.status='A'
            AND f2.data_vencimento < CURDATE() AND cc.status='A'
        )
    """, ())
    fechados = 0
    for c in clientes:
        try:
            execute("UPDATE ixcprovedor.su_oss_chamado SET status='F', data_fechamento=NOW() WHERE id=%s AND status<>'F'", (c["os39_id"],))
            fechados += 1
            log(f"  ✅ OS 39 #{c['os39_id']} fechada — {c['razao']}")
            registrar("os39_fechada", f"OS 39 #{c['os39_id']} fechada — {c['razao']}", True)
        except Exception as e:
            log(f"  ❌ Erro ao fechar OS 39 #{c['os39_id']}: {e}")
    return fechados

# ── 3. ABRE OS 39 PARA CRÍTICOS ───────────────────────────────────────────────
def corrigir_os39_faltantes():
    EXCLUIR = ['ESCOLA','ESCOLAR','COLEGIO','COLÉGIO','CONSELHO','CAIXA ESCOLAR','UNIDADE EXECUTORA']
    rows = local_query("SELECT DISTINCT fn_areceber_id FROM cob_interacoes WHERE segunda_cobranca=1 AND pago=0 AND resolvido=0", ())
    if not rows:
        return 0
    fn_ids = tuple(r["fn_areceber_id"] for r in rows)
    ph = ",".join(["%s"]*len(fn_ids))
    criticos = query(f"""
        SELECT f.id_cliente, c.razao,
               MAX(DATEDIFF(CURDATE(), f2.data_vencimento)) AS maior_atraso,
               SUM(f2.valor_aberto) AS total_aberto
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente c ON c.id=f.id_cliente
        LEFT JOIN ixcprovedor.fn_areceber f2 ON f2.id_cliente=f.id_cliente
            AND f2.status='A' AND f2.data_vencimento < CURDATE()
        WHERE f.id IN ({ph})
        AND f.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto=34 AND status NOT IN ('F')
        )
        GROUP BY f.id_cliente, c.razao
        HAVING maior_atraso >= 45
    """, fn_ids)
    abertos = 0
    for c in criticos:
        razao = c["razao"] or ""
        if any(k in razao.upper() for k in EXCLUIR):
            continue
        try:
            execute("""
                INSERT INTO ixcprovedor.su_oss_chamado
                    (id_cliente, id_assunto, mensagem, data_abertura, status, setor)
                VALUES (%s, 39, %s, NOW(), 'A', 8)
            """, (c["id_cliente"], f"Retirada automática — {razao} com {c['maior_atraso']}d inadimplente"))
            abertos += 1
            log(f"  ✅ OS 39 aberta — {razao} ({c['maior_atraso']}d)")
            registrar("os39_aberta", f"OS 39 aberta — {razao} ({c['maior_atraso']}d)", True)
        except Exception as e:
            log(f"  ❌ Erro ao abrir OS 39 para {razao}: {e}")
    return abertos

# ── 4. RESOLVE INTERAÇÕES INVÁLIDAS ──────────────────────────────────────────
def corrigir_interacoes_invalidas():
    from app.dashboards.cobranca.service import resolver_interacoes_pagas
    resolvidas = resolver_interacoes_pagas()
    if resolvidas > 0:
        log(f"  ✅ {resolvidas} interações resolvidas por pagamento")
        registrar("interacoes_pagas", f"{resolvidas} interações resolvidas", True)
    return resolvidas

# ── 5. VERIFICA CRONS ─────────────────────────────────────────────────────────
def verificar_crons():
    import subprocess
    alertas = []
    crons = [
        ("/var/log/cob_limpeza.log", 2, "Limpeza interações"),
        ("/var/log/cob_resolver_pagas.log", 1, "Resolver pagas"),
        ("/var/log/cob_monitoramento.log", 25, "Monitoramento OS"),
    ]
    agora = now_br()
    for logfile, max_horas, nome in crons:
        try:
            result = subprocess.run(['tail', '-1', logfile], capture_output=True, text=True)
            linha = result.stdout.strip()
            if not linha:
                alertas.append(f"⚠️ {nome}: log vazio")
                continue
            # Extrai data do log formato [DD/MM/YYYY HH:MM:SS]
            import re
            m = re.search(r'\[(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})\]', linha)
            if m:
                dt = datetime.strptime(m.group(1), '%d/%m/%Y %H:%M:%S').replace(tzinfo=TZ_BR)
                diff = (agora - dt).total_seconds() / 3600
                if diff > max_horas:
                    alertas.append(f"⚠️ {nome}: última execução há {diff:.0f}h (máximo {max_horas}h)")
                else:
                    log(f"  ✅ {nome}: OK (última execução há {diff:.1f}h)")
        except Exception as e:
            alertas.append(f"⚠️ {nome}: erro ao verificar — {e}")
    return alertas

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    log("=== INICIANDO AUDITORIA ===")
    alertas = []
    correcoes = []

    # 1. Token IXC
    token_ok = checar_token_ixc()

    # 2. Fecha OS 39 de quem pagou
    fechados = corrigir_os39_pagos()
    if fechados > 0:
        correcoes.append(f"✅ {fechados} OS 39 fechadas (clientes que pagaram)")

    # 3. Abre OS 39 faltantes
    abertos = corrigir_os39_faltantes()
    if abertos > 0:
        correcoes.append(f"✅ {abertos} OS 39 abertas (clientes +60d sem retirada)")

    # 4. Resolve interações inválidas
    resolvidas = corrigir_interacoes_invalidas()
    if resolvidas > 0:
        correcoes.append(f"✅ {resolvidas} interações resolvidas automaticamente")

    # 5. Verifica crons
    alertas_crons = verificar_crons()
    alertas.extend(alertas_crons)

    # Envia Telegram apenas se houver alertas ou correções relevantes
    if alertas:
        msg = "🔴 <b>HubCobrança — ALERTAS AUDITORIA</b>\n\n"
        msg += "\n".join(alertas)
        if correcoes:
            msg += "\n\n✅ <b>Auto-corrigido:</b>\n" + "\n".join(correcoes)
        msg += f"\n\n<i>{now_br().strftime('%d/%m/%Y %H:%M')}</i>"
        telegram(msg)
        log(f"Telegram enviado com {len(alertas)} alertas")
    elif correcoes:
        # Correções silenciosas — só loga, não incomoda no Telegram
        log(f"Auto-correções: {' | '.join(correcoes)}")

    log(f"=== AUDITORIA CONCLUÍDA — alertas={len(alertas)} correções={len(correcoes)} ===")

def fechar_os_sem_fatura():
    """Fecha OS 246 e resolve interações de clientes sem faturas vencidas."""
    from app.core.db import query, execute
    from app.core.db_local import local_query, local_execute
    log("=== LIMPEZA OS 246 SEM FATURA ===")

    candidatos = query("""
        SELECT DISTINCT o.id_cliente, o.id AS os_id
        FROM ixcprovedor.su_oss_chamado o
        WHERE o.id_assunto=190 AND o.status='A'
          AND o.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber
            WHERE status='A' AND data_vencimento < CURDATE()
          )
    """, ())

    if not candidatos:
        log("Nenhuma OS 246 para fechar")
        return

    log(f"OS 246 a fechar: {len(candidatos)}")
    for c in candidatos:
        execute("UPDATE ixcprovedor.su_oss_chamado SET status='F', data_fechamento=NOW() WHERE id=%s", (c["os_id"],))
        faturas = query("SELECT id FROM ixcprovedor.fn_areceber WHERE id_cliente=%s", (c["id_cliente"],))
        fn_ids = tuple(f["id"] for f in faturas)
        if fn_ids:
            ph = ",".join(["?"]*len(fn_ids))
            local_execute(f"UPDATE cob_interacoes SET resolvido=1 WHERE fn_areceber_id IN ({ph}) AND pago=0 AND resolvido=0", fn_ids)
    log(f"Concluído — {len(candidatos)} OS fechadas")

def limpar_segunda_cobranca_com_retirada():
    """Remove da 2ª cobrança clientes que já têm OS de retirada aberta (22 ou 39)"""
    from app.core.db import query
    from app.core.db_local import local_query, local_execute
    log("=== LIMPEZA 2ª COBRANÇA COM OS RETIRADA ===")
    clientes = query("""
        SELECT DISTINCT f.id AS fn_id
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.su_oss_chamado o ON o.id_cliente=f.id_cliente
        WHERE o.id_assunto IN (34) AND o.status NOT IN ('F') AND f.status='A'
    """, ())
    fn_ids = tuple(r["fn_id"] for r in clientes)
    if not fn_ids:
        log("Nenhuma interação para limpar")
        return
    ph = ",".join(["?"]*len(fn_ids))
    interacoes = local_query(f"""
        SELECT id FROM cob_interacoes
        WHERE segunda_cobranca=1 AND pago=0 AND (resolvido IS NULL OR resolvido=0)
        AND fn_areceber_id IN ({ph})
    """, fn_ids)
    for i in interacoes:
        local_execute("UPDATE cob_interacoes SET resolvido=1 WHERE id=?", (i["id"],))
    log(f"Removidas da 2ª cobrança: {len(interacoes)}")


def fechar_os_clientes_pagos():
    """Fecha OS 246 de clientes que pagaram, adicionando data/hora do pagamento."""
    from app.core.db import query, execute
    log("=== FECHA OS 246 CLIENTES QUE PAGARAM ===")
    candidatos = query("""
        SELECT o.id AS os_id, o.id_cliente, c.razao,
               MAX(f.baixa_data) AS ultimo_pagamento
        FROM su_oss_chamado o
        INNER JOIN cliente c ON c.id=o.id_cliente
        LEFT JOIN fn_areceber f ON f.id_cliente=o.id_cliente AND f.status='R'
        WHERE o.id_assunto=190 AND o.status='A'
          AND o.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM fn_areceber
            WHERE status='A' AND data_vencimento < CURDATE()
          )
        GROUP BY o.id, o.id_cliente, c.razao
    """, ())
    if not candidatos:
        log("Nenhuma OS 246 para fechar por pagamento")
        return
    log(f"OS 246 a fechar por pagamento: {len(candidatos)}")
    for c in candidatos:
        try:
            from datetime import datetime
            pag_fmt = ""
            if c["ultimo_pagamento"]:
                try:
                    pag_dt = datetime.strptime(str(c["ultimo_pagamento"])[:19], "%Y-%m-%d %H:%M:%S")
                    pag_fmt = pag_dt.strftime("%d/%m/%Y as %H:%M")
                except: pag_fmt = str(c["ultimo_pagamento"])[:16]
            msg_extra = f"\n\nPagamento confirmado em {pag_fmt} - Fechado pelo HubCobranca" if pag_fmt else "\n\nFatura quitada - Fechado pelo HubCobranca"
            execute("UPDATE su_oss_chamado SET status='F', data_fechamento=NOW(), mensagem=CONCAT(COALESCE(mensagem,''), %s) WHERE id=%s",
                (msg_extra, c["os_id"]))
            log(f"  OK OS #{c['os_id']} fechada — {c['razao']}")
        except Exception as e:
            log(f"  ERRO OS #{c['os_id']}: {e}")

def limpar_segunda_cobranca():
    """Resolve interações da 2ª cobrança de clientes que pagaram ou cancelaram."""
    from app.core.db import query
    from app.core.db_local import local_query, local_execute
    log("=== LIMPEZA 2ª COBRANÇA ===")

    fn_ids = tuple(r["fn_areceber_id"] for r in local_query("""
        SELECT DISTINCT fn_areceber_id FROM cob_interacoes
        WHERE segunda_cobranca=1 AND pago=0 AND (resolvido IS NULL OR resolvido=0)
    """, ()))

    if not fn_ids:
        log("Nenhuma interação para limpar")
        return

    ph = ",".join(["%s"]*len(fn_ids))

    # Pagaram
    pagos = query(f"SELECT id FROM ixcprovedor.fn_areceber WHERE id IN ({ph}) AND status='R'", tuple(fn_ids))
    for r in pagos:
        local_execute("UPDATE cob_interacoes SET pago=1, resolvido=1 WHERE fn_areceber_id=? AND pago=0", (r["id"],))

    # Contrato cancelado
    cancelados = query(f"""
        SELECT DISTINCT f.id FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id_cliente=f.id_cliente
        WHERE f.id IN ({ph}) AND cc.status='I'
    """, tuple(fn_ids))
    for r in cancelados:
        local_execute("UPDATE cob_interacoes SET resolvido=1 WHERE fn_areceber_id=? AND resolvido=0", (r["id"],))

    log(f"Pagos: {len(pagos)} | Cancelados: {len(cancelados)}")

def reabrir_os_fatura_aberta():
    """Reabre OS 39/22 fechadas de clientes que ainda têm fatura em aberto e nunca pagaram"""
    from app.core.db import query, execute
    log("=== REABRE OS RETIRADA COM FATURA ABERTA ===")

    candidatos = query("""
        SELECT DISTINCT o.id, o.id_cliente, c.razao
        FROM ixcprovedor.su_oss_chamado o
        INNER JOIN ixcprovedor.cliente c ON c.id=o.id_cliente
        INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id_cliente=o.id_cliente AND cc.status='A'
        INNER JOIN ixcprovedor.fn_areceber f ON f.id_cliente=o.id_cliente
            AND f.status='A' AND f.data_vencimento < CURDATE()
        WHERE o.id_assunto IN (34) AND o.status='F'
          AND DATEDIFF(CURDATE(), cc.data_ativacao) <= 90
          AND o.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber WHERE status='R'
          )
          AND o.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto IN (34) AND status NOT IN ('F')
          )
    """, ())

    if not candidatos:
        log("Nenhuma OS para reabrir")
        return

    log(f"OS para reabrir: {len(candidatos)}")
    for c in candidatos:
        execute("""
            UPDATE ixcprovedor.su_oss_chamado
            SET status='A', data_fechamento=NULL,
                mensagem=CONCAT(COALESCE(mensagem,''), %s)
            WHERE id=%s
        """, ('\nOS reaberta automaticamente - cliente ainda tem fatura em aberto.', c["id"]))
        log(f"  ✅ OS #{c['id']} reaberta — {c['razao']}")

if __name__ == "__main__":
    main()
    fechar_os_clientes_pagos()
    fechar_os_sem_fatura()
    reabrir_os_fatura_aberta()
    limpar_segunda_cobranca()
    limpar_segunda_cobranca_com_retirada()
