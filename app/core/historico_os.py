from collections import Counter
from typing import Any


def _texto(valor: Any, padrao: str = "") -> str:
    if valor is None:
        return padrao

    texto = str(valor).strip()
    return texto if texto else padrao


def _data(valor: Any, padrao: str = "") -> str:
    if not valor:
        return padrao

    texto = str(valor).strip()

    if len(texto) >= 10:
        parte = texto[:10]

        if (
            len(parte) == 10
            and parte[4] == "-"
            and parte[7] == "-"
        ):
            data = (
                f"{parte[8:10]}/"
                f"{parte[5:7]}/"
                f"{parte[0:4]}"
            )

            if len(texto) > 10:
                hora = texto[11:19]
                if hora:
                    return f"{data} {hora}"

            return data

    return texto


def _data_promessa(valor: Any) -> str:
    return _data(valor)


def _normalizar_acao(valor: Any) -> str:
    return " ".join(
        _texto(valor).split()
    )


def _normalizar_obs(valor: Any) -> str:
    return " ".join(
        _texto(valor).split()
    )


def _classificar_evento(
    acao: str,
    data_promessa: Any = None,
) -> str:
    """
    Define o tipo principal do evento.

    A existência de data_promessa NÃO transforma
    automaticamente o evento em promessa.

    Exemplo:
        Ligação realizada + data_promessa
        => contato

        Pagamento realizado + data_promessa
        => pagamento
    """

    acao_normalizada = _normalizar_acao(
        acao
    ).lower()

    if acao_normalizada == "pagamento realizado":
        return "pagamento"

    if "solicitar retirada" in acao_normalizada:
        return "retirada"

    if "promessa" in acao_normalizada:
        return "promessa"

    if "não atendeu" in acao_normalizada:
        return "nao_atendeu"

    if "caixa postal" in acao_normalizada:
        return "caixa_postal"

    if "whatsapp" in acao_normalizada:
        return "whatsapp"

    if (
        "ligação" in acao_normalizada
        or "ligacao" in acao_normalizada
        or "contato" in acao_normalizada
    ):
        return "contato"

    return "outro"


def _mesma_acao_consecutiva(
    anterior: dict,
    atual: dict,
) -> bool:
    """
    Detecta duplicações consecutivas do mesmo evento.

    A comparação considera:
    - ação;
    - observação;
    - data da promessa.

    Eventos iguais consecutivos podem ser
    descartados na normalização.
    """

    return (
        _normalizar_acao(
            anterior.get("acao")
        ).lower()
        == _normalizar_acao(
            atual.get("acao")
        ).lower()
        and _normalizar_obs(
            anterior.get("obs")
        ).lower()
        == _normalizar_obs(
            atual.get("obs")
        ).lower()
        and _data_promessa(
            anterior.get("data_promessa")
        )
        == _data_promessa(
            atual.get("data_promessa")
        )
    )


def _descricao_interacao(
    acao: str,
    obs: str = "",
    data_promessa: Any = None,
) -> str:
    acao = _normalizar_acao(acao)
    obs = _normalizar_obs(obs)

    partes = []

    if acao:
        partes.append(
            f"{acao}."
        )

    if obs:
        partes.append(
            f"{obs}."
        )

    promessa = _data_promessa(
        data_promessa
    )

    if promessa:
        partes.append(
            f"Promessa para {promessa}."
        )

    return " ".join(
        partes
    ).strip()


def _eh_nova_promessa(evento: dict) -> bool:
    """
    Determina se o evento representa uma promessa
    efetivamente registrada.

    Somente o tipo principal 'promessa' conta como
    nova promessa.

    Uma ligação que possui data_promessa não conta
    como uma nova promessa.
    """

    return (
        evento.get("tipo_evento")
        == "promessa"
    )


def normalizar_historico_os(
    historico: list
) -> list:
    """
    Normaliza o histórico de cobrança para uso
    na geração das OS.

    Responsabilidades:
    - ordenar cronologicamente;
    - normalizar textos;
    - classificar eventos;
    - eliminar duplicações consecutivas;
    - preservar informações de promessa;
    - identificar pagamentos;
    - identificar segunda cobrança.
    """

    if not historico:
        return []

    eventos = [
        dict(item)
        for item in historico
    ]

    eventos.sort(
        key=lambda item: (
            _texto(item.get("criado_em")),
            int(item.get("id") or 0),
        )
    )

    normalizados = []

    for evento in eventos:

        acao = _normalizar_acao(
            evento.get("acao")
        )

        obs = _normalizar_obs(
            evento.get("obs")
        )

        data_promessa = evento.get(
            "data_promessa"
        )

        evento["acao"] = acao
        evento["obs"] = obs

        evento["data_formatada"] = _data(
            evento.get("criado_em")
        )

        evento["promessa_formatada"] = (
            _data_promessa(
                data_promessa
            )
        )

        evento["tipo_evento"] = (
            _classificar_evento(
                acao,
                data_promessa,
            )
        )

        evento["eh_pagamento"] = (
            evento["tipo_evento"]
            == "pagamento"
        )

        evento["tem_promessa"] = bool(
            data_promessa
        )

        evento["eh_promessa"] = (
            _eh_nova_promessa(evento)
        )

        evento["eh_segunda_cobranca"] = bool(
            evento.get("segunda_cobranca")
        )

        evento["descricao_os"] = (
            _descricao_interacao(
                acao,
                obs,
                data_promessa,
            )
        )

        if normalizados:
            anterior = normalizados[-1]

            if _mesma_acao_consecutiva(
                anterior,
                evento,
            ):
                continue

        normalizados.append(
            evento
        )

    return normalizados


def analisar_promessas_os(
    historico: list
) -> dict:
    """
    Analisa especificamente as promessas.

    Retorna:
    - quantidade de eventos com data de promessa;
    - quantidade de promessas efetivamente registradas;
    - quantidade de pagamentos;
    - última promessa;
    - último pagamento.
    """

    eventos = normalizar_historico_os(
        historico
    )

    eventos_com_promessa = [
        evento
        for evento in eventos
        if evento.get("tem_promessa")
    ]

    promessas_registradas = [
        evento
        for evento in eventos
        if evento.get("eh_promessa")
    ]

    pagamentos = [
        evento
        for evento in eventos
        if evento.get("eh_pagamento")
    ]

    return {
        "quantidade_eventos_com_promessa": len(
            eventos_com_promessa
        ),
        "quantidade_promessas_registradas": len(
            promessas_registradas
        ),
        "quantidade_pagamentos_registrados": len(
            pagamentos
        ),
        "ultima_promessa": (
            promessas_registradas[-1]
            if promessas_registradas
            else None
        ),
        "ultimo_pagamento": (
            pagamentos[-1]
            if pagamentos
            else None
        ),
    }


def resumir_historico_os(
    historico: list
) -> dict:
    """
    Produz um resumo operacional do histórico.
    """

    eventos = normalizar_historico_os(
        historico
    )

    tipos = Counter(
        evento.get(
            "tipo_evento",
            "outro"
        )
        for evento in eventos
    )

    pagamentos = [
        evento
        for evento in eventos
        if evento.get("eh_pagamento")
    ]

    promessas = [
        evento
        for evento in eventos
        if evento.get("eh_promessa")
    ]

    eventos_com_promessa = [
        evento
        for evento in eventos
        if evento.get("tem_promessa")
    ]

    segunda_cobranca = [
        evento
        for evento in eventos
        if evento.get(
            "eh_segunda_cobranca"
        )
    ]

    ultima_acao = (
        eventos[-1]
        if eventos
        else None
    )

    return {
        "quantidade_eventos": len(eventos),

        "teve_pagamento": bool(
            pagamentos
        ),

        "teve_promessa": bool(
            promessas
        ),

        "teve_segunda_cobranca": bool(
            segunda_cobranca
        ),

        # Nova definição:
        # somente eventos que realmente
        # representam uma promessa.
        "quantidade_promessas": len(
            promessas
        ),

        # Quantos eventos carregam
        # uma data de promessa.
        "quantidade_eventos_com_promessa": len(
            eventos_com_promessa
        ),

        "quantidade_pagamentos": len(
            pagamentos
        ),

        "quantidade_retiradas": tipos.get(
            "retirada",
            0
        ),

        "quantidade_contatos": tipos.get(
            "contato",
            0
        ),

        "quantidade_nao_atendeu": tipos.get(
            "nao_atendeu",
            0
        ),

        "quantidade_caixa_postal": tipos.get(
            "caixa_postal",
            0
        ),

        "quantidade_whatsapp": tipos.get(
            "whatsapp",
            0
        ),

        "ultima_acao": (
            ultima_acao.get("acao")
            if ultima_acao
            else None
        ),

        "ultima_data": (
            ultima_acao.get(
                "data_formatada"
            )
            if ultima_acao
            else None
        ),

        "ultimo_operador": (
            ultima_acao.get(
                "usuario_nome"
            )
            if ultima_acao
            else None
        ),
    }


def preparar_historico_os(
    historico: list
) -> dict:
    """
    Prepara o histórico completo para o gerador
    de OS.
    """

    eventos = normalizar_historico_os(
        historico
    )

    resumo = resumir_historico_os(
        historico
    )

    promessas = analisar_promessas_os(
        historico
    )

    return {
        "eventos": eventos,
        "resumo": resumo,
        "promessas": promessas,
    }
