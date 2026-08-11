#!/usr/bin/env python3
"""
Cron: resolve interações/promessas quebradas cujas faturas já foram pagas no IXC.
Roda com frequência alta para tirar rapidamente da tela quem já pagou.
"""
import sys
sys.path.insert(0, '/opt/automacoes/cliquedf/cobranca')

from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
def now_br(): return datetime.now(TZ_BR)

from app.dashboards.cobranca.service import resolver_interacoes_pagas

def main():
    pagas = resolver_interacoes_pagas()
    if pagas:
        print(f"[{now_br()}] Interações/promessas resolvidas por pagamento: {pagas}")

if __name__ == '__main__':
    main()
