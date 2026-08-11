from dataclasses import dataclass
from typing import Optional

@dataclass
class FiltrosGlobais:
    faixa:              str  = "all"
    data_ini:           Optional[str] = None
    data_fim:           Optional[str] = None
    busca:              str  = ""
    pagina:             int  = 1
    por_pagina:         int  = 50
    ocultar_cancelados: bool = False

def parse_filtros(
    faixa:              str  = "all",
    data_ini:           Optional[str] = None,
    data_fim:           Optional[str] = None,
    busca:              str  = "",
    pagina:             int  = 1,
    por_pagina:         int  = 50,
    ocultar_cancelados: bool = False
) -> FiltrosGlobais:
    return FiltrosGlobais(
        faixa=faixa,
        data_ini=data_ini,
        data_fim=data_fim,
        busca=busca,
        pagina=max(1, pagina),
        por_pagina=min(max(1, por_pagina), 200),
        ocultar_cancelados=ocultar_cancelados
    )
