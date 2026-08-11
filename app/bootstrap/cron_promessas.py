#!/usr/bin/env python3
"""
Cron: Detecta promessas quebradas e resolve interações pagas
Executa diariamente às 08:00
"""
import sys
sys.path.insert(0, '/opt/automacoes/cliquedf/cobranca')

from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)
from app.dashboards.cobranca.service import detectar_promessas_quebradas, resolver_interacoes_pagas
from app.core.db_local import local_execute

def main():
    print(f"[{now_br()}] Iniciando cron Cliquedf Cobrança...")

    try:
        # 1. Resolve interações cujas faturas foram pagas no IXC
        pagas = resolver_interacoes_pagas()
        print(f"[{now_br()}] Interações resolvidas por pagamento: {pagas}")

        # 2. Limpa promessas de contratos cancelados ou faturas pagas/canceladas
        from app.core.db import query as _query
        from app.core.db_local import local_query as _lq, local_execute as _le
        _quebradas = _lq("SELECT id, fn_areceber_id FROM cob_promessas_quebradas WHERE resolvido=0", ())
        _fn_ids = tuple(int(r["fn_areceber_id"]) for r in _quebradas if r["fn_areceber_id"])
        if _fn_ids:
            _ph = ",".join(["%s"]*len(_fn_ids))
            _resolver = _query(f"""
                SELECT f.id FROM ixcprovedor.fn_areceber f
                INNER JOIN ixcprovedor.cliente_contrato cc ON cc.id_cliente=f.id_cliente
                WHERE f.id IN ({_ph}) AND (f.status IN ('R','C') OR cc.status='I')
            """, _fn_ids)
            for _r in _resolver:
                _le("UPDATE cob_promessas_quebradas SET resolvido=1, resolvido_em=datetime('now','-3 hours') WHERE fn_areceber_id=? AND resolvido=0", (_r["id"],))
                _le("UPDATE cob_interacoes SET resolvido=1 WHERE fn_areceber_id=? AND resolvido=0", (_r["id"],))
            print(f"[{now_br()}] Promessas limpas (canceladas/pagas): {len(_resolver)}")

        # 3. Detecta promessas quebradas
        quebradas = detectar_promessas_quebradas()
        print(f"[{now_br()}] Promessas quebradas detectadas: {quebradas}")

        local_execute("""
            INSERT INTO cob_logs (usuario_id, acao, ip)
            VALUES (1, ?, 'cron')
        """, (f"pagas={pagas} quebradas={quebradas}",))

        print(f"[{now_br()}] Cron concluído com sucesso.")
    except Exception as e:
        print(f"[{now_br()}] ERRO: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
