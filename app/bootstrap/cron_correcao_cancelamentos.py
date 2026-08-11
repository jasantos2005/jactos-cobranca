#!/usr/bin/env python3
"""
Cron Correção Cancelamentos — roda diariamente às 3h
Corrige data de cancelamento por inadimplência para a data do último pagamento
quando o atraso for superior a 60 dias (erro operacional)
"""
import sys, os
sys.path.insert(0, '/opt/automacoes/cliquedf/cobranca')
os.chdir('/opt/automacoes/cliquedf/cobranca')
from datetime import datetime, timezone, timedelta
from app.core.db import execute, query

TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
def log(msg): print(f"[{now_br().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)

def main():
    log("=== CORREÇÃO DATAS CANCELAMENTO ===")

    # Busca cancelamentos com atraso > 60 dias nos últimos 6 meses
    candidatos = query("""
        SELECT cc.id, cc.data_cancelamento,
               DATE(MAX(CASE WHEN f.status='R' THEN f.baixa_data END)) AS ultimo_pag,
               DATEDIFF(cc.data_cancelamento, MAX(CASE WHEN f.status='R' THEN f.baixa_data END)) AS dias_atraso
        FROM ixcprovedor.cliente_contrato cc
        LEFT JOIN ixcprovedor.fn_areceber f ON f.id_cliente=cc.id_cliente
        WHERE cc.status='I'
          AND cc.motivo_cancelamento=13
          AND cc.data_cancelamento >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
        GROUP BY cc.id, cc.data_cancelamento
        HAVING ultimo_pag IS NOT NULL AND dias_atraso > 60
    """, ())

    if not candidatos:
        log("Nenhuma correção necessária")
        return

    log(f"Contratos para corrigir: {len(candidatos)}")
    corrigidos = 0
    for c in candidatos:
        execute("""
            UPDATE ixcprovedor.cliente_contrato
            SET data_cancelamento=%s
            WHERE id=%s
        """, (c["ultimo_pag"], c["id"]))
        corrigidos += 1
        log(f"  ✅ Contrato #{c['id']} — {c['data_cancelamento']} → {c['ultimo_pag']} ({c['dias_atraso']}d atraso)")

    log(f"Concluído — {corrigidos} contratos corrigidos")

def corrigir_nunca_pagaram():
    """Corrige data cancelamento de quem nunca pagou para o primeiro vencimento"""
    log("=== CORREÇÃO NUNCA PAGARAM ===")
    candidatos = query("""
        SELECT cc.id, cc.data_cancelamento,
               DATE(MIN(f.data_vencimento)) AS primeiro_venc
        FROM ixcprovedor.cliente_contrato cc
        LEFT JOIN ixcprovedor.fn_areceber f ON f.id_cliente=cc.id_cliente
        WHERE cc.status='I' AND cc.motivo_cancelamento=13
          AND cc.data_cancelamento >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
          AND cc.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber WHERE status='R'
          )
        GROUP BY cc.id, cc.data_cancelamento
        HAVING primeiro_venc IS NOT NULL
          AND primeiro_venc >= '2025-01-01'
          AND DATEDIFF(cc.data_cancelamento, primeiro_venc) > 60
    """, ())

    if not candidatos:
        log("Nenhuma correção necessária (nunca pagaram)")
        return

    log(f"Nunca pagaram para corrigir: {len(candidatos)}")
    for c in candidatos:
        execute("UPDATE ixcprovedor.cliente_contrato SET data_cancelamento=%s WHERE id=%s",
                (c["primeiro_venc"], c["id"]))
        log(f"  ✅ Contrato #{c['id']} — {c['data_cancelamento']} → {c['primeiro_venc']}")
    log(f"Concluído — {len(candidatos)} corrigidos")

if __name__ == "__main__":
    main()
    corrigir_nunca_pagaram()
