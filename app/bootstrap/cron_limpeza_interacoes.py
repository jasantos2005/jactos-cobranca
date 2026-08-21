"""
Cron de limpeza de interações — executa a cada hora
Regras:
- Fatura paga ou cancelada → resolvido=1
- Contrato inativo/cancelado → resolvido=1
- OS de retirada aberta → resolvido=1
- OS 246 aberta → segunda_cobranca=1 (move para 2ª cobrança)
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/cliquedf/cobranca')
os.chdir('/opt/automacoes/cliquedf/cobranca')
from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)

from app.core.db import query, query_one
from app.core.db_local import local_query, local_query_one, local_execute

def limpar():
    # Busca todas interações abertas
    rows = local_query("""
        SELECT DISTINCT fn_areceber_id FROM cob_interacoes
        WHERE pago=0 AND (resolvido IS NULL OR resolvido=0)
        AND fn_areceber_id IS NOT NULL
    """, ())
    if not rows:
        log("Nenhuma interação aberta.")
        return

    fn_ids = tuple(r["fn_areceber_id"] for r in rows)
    ph = ",".join(["%s"]*len(fn_ids))

    # Busca faturas + contrato + cliente no IXC
    faturas = query(f"""
        SELECT f.id, f.status AS fatura_status, f.id_cliente,
               cc.status AS contrato_status
        FROM ixcprovedor.fn_areceber f
        LEFT JOIN ixcprovedor.cliente_contrato cc ON cc.id = f.id_contrato
        WHERE f.id IN ({ph})
    """, fn_ids)
    faturas_map = {str(f["id"]): dict(f) for f in faturas}

    # Clientes para verificar OS
    id_clientes = list({f["id_cliente"] for f in faturas if f.get("id_cliente")})
    clientes_com_retirada = set()
    clientes_com_os246 = set()
    if id_clientes:
        ph2 = ",".join(["%s"]*len(id_clientes))
        ret = query(f"""
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto=34 AND status IN ('A','EN','AG','REG','RAG')
            AND id_cliente IN ({ph2})
        """, tuple(id_clientes))
        clientes_com_retirada = {r["id_cliente"] for r in ret}

        os246 = query(f"""
            SELECT DISTINCT id_cliente FROM ixcprovedor.su_oss_chamado
            WHERE id_assunto=190 AND status='A'
            AND id_cliente IN ({ph2})
        """, tuple(id_clientes))
        clientes_com_os246 = {r["id_cliente"] for r in os246}

    resolvidos = 0
    movidos = 0

    for fn_id_str, fat in faturas_map.items():
        fn_id = int(fn_id_str)
        id_cli = fat.get("id_cliente")

        # Fatura paga/cancelada ou contrato inativo
        if fat.get("fatura_status") != "A" or fat.get("contrato_status") not in ("A", None):
            local_execute("UPDATE cob_interacoes SET resolvido=1 WHERE fn_areceber_id=? AND resolvido=0", (fn_id,))
            resolvidos += 1
            continue

        # OS de retirada aberta — resolve apenas interações SEM promessa futura
        if id_cli and id_cli in clientes_com_retirada:
            from datetime import date
            hoje = date.today().isoformat()
            local_execute("""
                UPDATE cob_interacoes SET resolvido=1
                WHERE fn_areceber_id=? AND resolvido=0
                AND (data_promessa IS NULL OR data_promessa < ?)
            """, (fn_id, hoje))
            resolvidos += 1
            continue

        # NOTA: removida a promoção automática para 2ª cobrança baseada em
        # "cliente tem OS 246 aberta". Essa checagem promovia a própria
        # interação recém-criada (vinda da Fila) para 2ª cobrança, pulando
        # a Primeira Cobrança. A transição agora só acontece de forma
        # explícita, quando o operador registra a 2ª interação em
        # Primeira Cobrança (rota /api/mover-segunda-cobranca).
        pass

    # Faturas não encontradas no IXC
    for row in rows:
        fn_id = row["fn_areceber_id"]
        if str(fn_id) not in faturas_map:
            local_execute("UPDATE cob_interacoes SET resolvido=1 WHERE fn_areceber_id=? AND resolvido=0", (fn_id,))
            resolvidos += 1

    log(f"Limpeza concluída — resolvidos: {resolvidos}, movidos para 2ª: {movidos}")

    # Avança o degrau de cobrança automaticamente se o atual estiver vazio
    try:
        from app.dashboards.cobranca.service import avancar_degrau_se_vazio
        novo_degrau = avancar_degrau_se_vazio()
        if novo_degrau:
            log(f"[DEGRAU] Faixa atual zerou — novo degrau liberado: {novo_degrau}")
    except Exception as e:
        log(f"[DEGRAU ERRO] {e}")

if __name__ == "__main__":
    limpar()
