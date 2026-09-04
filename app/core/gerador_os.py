from decimal import Decimal
from typing import Any


FILIAIS = {
    1: "MATRIZ",
    2: "NOVO MUNDO",
    3: "SOLANGE PARK",
}


def _texto(valor: Any, padrao: str = "") -> str:
    if valor is None:
        return padrao

    texto = str(valor).strip()
    return texto if texto else padrao


def _inteiro(valor: Any, padrao: int = 0) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return padrao


def _moeda(valor: Any) -> str:
    try:
        valor = Decimal(str(valor or 0))
    except Exception:
        valor = Decimal("0")

    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


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
            return (
                f"{parte[8:10]}/"
                f"{parte[5:7]}/"
                f"{parte[0:4]}"
            )

    return texto


def _filial_nome(id_filial: Any) -> str:
    filial_id = _inteiro(id_filial)

    if filial_id in FILIAIS:
        return f"JACTOS {FILIAIS[filial_id]}"

    return f"FILIAL #{filial_id}"


def _linha(titulo: str, valor: Any) -> str:
    return f"{titulo}: {_texto(valor, 'Não informado')}"


def _fatura_paga(fatura: dict) -> bool:
    status = _texto(fatura.get("status")).upper()

    try:
        valor_aberto = Decimal(
            str(fatura.get("valor_aberto") or 0)
        )
    except Exception:
        valor_aberto = Decimal("0")

    return status == "R" or valor_aberto <= 0


def _historico(contexto: dict) -> list:
    historico_os = contexto.get("historico_os")

    if isinstance(historico_os, dict):
        return list(
            historico_os.get("eventos") or []
        )

    return list(
        contexto.get("historico") or []
    )


def _formatar_evento(evento: dict) -> list:
    """
    Formata cada evento em bloco para facilitar a leitura
    por quem receber a OS.
    """

    data = _texto(
        evento.get("data_formatada")
        or evento.get("criado_em")
    )

    descricao = _texto(
        evento.get("descricao_os")
    )

    acao = _texto(
        evento.get("acao")
    )

    obs = _texto(
        evento.get("obs")
    )

    operador = _texto(
        evento.get("usuario_nome"),
        "Sistema"
    )

    promessa = _texto(
        evento.get("promessa_formatada")
    )

    linhas = []

    if data:
        linhas.append(data)

    if descricao:
        linhas.append(descricao)
    elif acao:
        linhas.append(acao)

    if obs:
        linhas.append(
            f"Observação: {obs}"
        )

    if promessa:
        linhas.append(
            f"Promessa para: {promessa}"
        )

    linhas.append(
        f"Operador: {operador}"
    )

    return linhas


def _gerar_secao_historico(contexto: dict) -> list:
    eventos = _historico(contexto)

    linhas = [
        "══════════════════════════════════════",
        "HISTÓRICO DA COBRANÇA",
        "══════════════════════════════════════",
    ]

    if not eventos:
        linhas.append(
            "Nenhuma interação registrada."
        )
        return linhas

    for indice, evento in enumerate(eventos):

        if indice > 0:
            linhas.append("")

        linhas.extend(
            _formatar_evento(evento)
        )

    return linhas


def _gerar_secao_debito(contexto: dict) -> list:
    fatura = contexto.get("fatura") or {}

    linhas = [
        "══════════════════════════════════════",
        "DÉBITO",
        "══════════════════════════════════════",
    ]

    if not fatura:
        linhas.append(
            "Nenhuma fatura vinculada à OS."
        )
        return linhas

    fatura_id = _inteiro(
        fatura.get("id")
    )

    linhas.append(
        _linha(
            "Fatura",
            f"#{fatura_id}" if fatura_id else None
        )
    )

    if fatura.get("documento"):
        linhas.append(
            _linha(
                "Documento",
                fatura.get("documento")
            )
        )

    linhas.append(
        _linha(
            "Vencimento",
            _data(
                fatura.get("data_vencimento")
            )
        )
    )

    dias_atraso = _inteiro(
        fatura.get("dias_atraso")
    )

    if dias_atraso > 0:
        linhas.append(
            _linha(
                "Dias em atraso",
                f"{dias_atraso} dias"
            )
        )
    elif dias_atraso == 0:
        linhas.append(
            "Dias em atraso: Vencimento hoje"
        )
    else:
        linhas.append(
            "Dias em atraso: Fatura ainda não vencida"
        )

    linhas.append(
        _linha(
            "Valor original",
            _moeda(
                fatura.get("valor")
            )
        )
    )

    linhas.append(
        _linha(
            "Valor em aberto",
            _moeda(
                fatura.get("valor_aberto")
            )
        )
    )

    status = _texto(
        fatura.get("status")
    )

    if status:
        linhas.append(
            _linha(
                "Status IXC",
                status
            )
        )

    if _fatura_paga(fatura):
        linhas.append(
            "Situação atual: PAGAMENTO IDENTIFICADO NO IXC"
        )
    else:
        linhas.append(
            "Situação atual: DÉBITO EM ABERTO"
        )

    return linhas


def _gerar_secao_cliente(contexto: dict) -> list:
    cliente = contexto.get("cliente") or {}
    contrato = contexto.get("contrato") or {}
    filial = contexto.get("filial") or {}

    id_contrato = _inteiro(
        contrato.get("id_contrato")
    )

    id_filial = _inteiro(
        filial.get("id")
        or contrato.get("id_filial")
    )

    linhas = [
        "══════════════════════════════════════",
        "CLIENTE",
        "══════════════════════════════════════",
    ]

    linhas.append(
        _linha(
            "Nome",
            cliente.get("nome")
        )
    )

    linhas.append(
        _linha(
            "Cliente ID",
            cliente.get("id")
        )
    )

    if cliente.get("documento"):
        linhas.append(
            _linha(
                "CPF/CNPJ",
                cliente.get("documento")
            )
        )

    linhas.append(
        _linha(
            "Contrato",
            f"#{id_contrato}" if id_contrato else None
        )
    )

    linhas.append(
        _linha(
            "Filial",
            _filial_nome(id_filial)
            if id_filial
            else None
        )
    )

    return linhas


def _gerar_secao_equipamentos(contexto: dict) -> list:
    equipamentos = contexto.get("equipamentos") or []

    linhas = [
        "══════════════════════════════════════",
        "EQUIPAMENTOS EM COMODATO",
        "══════════════════════════════════════",
    ]

    if not equipamentos:
        linhas.append(
            "Nenhum equipamento localizado "
            "para o contrato."
        )
        return linhas

    for indice, equipamento in enumerate(
        equipamentos,
        start=1
    ):
        if indice > 1:
            linhas.append("")

        descricao = _texto(
            equipamento.get("equipamento"),
            "Equipamento não informado"
        )

        linhas.append(
            f"{indice}. {descricao}"
        )

        patrimonio = equipamento.get(
            "id_patrimonio"
        )

        if patrimonio:
            linhas.append(
                f"Patrimônio: {patrimonio}"
            )

        serial = _texto(
            equipamento.get("serial")
        )

        if serial:
            linhas.append(
                f"Serial: {serial}"
            )

        mac = _texto(
            equipamento.get("id_mac")
        )

        if mac:
            linhas.append(
                f"MAC: {mac}"
            )

        valor_bem = equipamento.get(
            "valor_bem"
        )

        if valor_bem is not None:
            linhas.append(
                f"Valor do bem: {_moeda(valor_bem)}"
            )

    return linhas


def _gerar_secao_atendimento(
    acao: str = "",
    obs: str = "",
) -> list:
    linhas = [
        "══════════════════════════════════════",
        "ATENDIMENTO ATUAL",
        "══════════════════════════════════════",
    ]

    if acao:
        linhas.append(
            _linha(
                "Ação realizada",
                acao
            )
        )

    if obs:
        linhas.append(
            _linha(
                "Observação",
                obs
            )
        )

    if not acao and not obs:
        linhas.append(
            "Nenhum atendimento adicional informado."
        )

    return linhas


def _gerar_secao_situacao(
    contexto: dict
) -> list:
    historico_os = contexto.get(
        "historico_os"
    ) or {}

    resumo = historico_os.get(
        "resumo"
    ) or {}

    linhas = [
        "══════════════════════════════════════",
        "SITUAÇÃO DA COBRANÇA",
        "══════════════════════════════════════",
    ]

    quantidade_eventos = _inteiro(
        resumo.get("quantidade_eventos")
    )

    quantidade_promessas = _inteiro(
        resumo.get("quantidade_promessas")
    )

    quantidade_eventos_com_promessa = _inteiro(
        resumo.get("quantidade_eventos_com_promessa")
    )

    quantidade_pagamentos = _inteiro(
        resumo.get("quantidade_pagamentos")
    )

    quantidade_retiradas = _inteiro(
        resumo.get("quantidade_retiradas")
    )

    quantidade_nao_atendeu = _inteiro(
        resumo.get("quantidade_nao_atendeu")
    )

    quantidade_caixa_postal = _inteiro(
        resumo.get("quantidade_caixa_postal")
    )

    teve_segunda_cobranca = bool(
        resumo.get("teve_segunda_cobranca")
    )

    quantidade_segunda_cobranca = _inteiro(
        resumo.get("quantidade_segunda_cobranca")
    )

    linhas.append(
        f"Interações registradas: {quantidade_eventos}"
    )

    if quantidade_promessas:
        linhas.append(
            f"Promessas registradas: {quantidade_promessas}"
        )

    if quantidade_eventos_com_promessa:
        linhas.append(
            "Eventos com promessa: "
            f"{quantidade_eventos_com_promessa}"
        )

    if quantidade_pagamentos:
        linhas.append(
            f"Pagamentos registrados: {quantidade_pagamentos}"
        )

    if quantidade_segunda_cobranca:
        linhas.append(
            "2ª cobrança realizada: Sim"
        )

    if quantidade_retiradas:
        linhas.append(
            f"Solicitações de retirada: {quantidade_retiradas}"
        )

    if quantidade_nao_atendeu:
        linhas.append(
            f"Não atendimentos: {quantidade_nao_atendeu}"
        )

    if quantidade_caixa_postal:
        linhas.append(
            f"Caixa postal: {quantidade_caixa_postal}"
        )

    if teve_segunda_cobranca:
        linhas.append(
            "2ª cobrança realizada: Sim"
        )

    ultima_acao = _texto(
        resumo.get("ultima_acao")
    )

    ultima_data = _texto(
        resumo.get("ultima_data")
    )

    ultimo_operador = _texto(
        resumo.get("ultimo_operador")
    )

    if ultima_acao:
        linhas.append(
            f"Última ação registrada: {ultima_acao}"
        )

    if ultima_data:
        linhas.append(
            f"Data da última ação: {ultima_data}"
        )

    if ultimo_operador:
        linhas.append(
            f"Último operador: {ultimo_operador}"
        )

    return linhas


def _gerar_orientacao_cobranca(
    contexto: dict
) -> list:
    fatura = contexto.get(
        "fatura"
    ) or {}

    if _fatura_paga(fatura):
        texto = (
            "Pagamento identificado no IXC. "
            "Validar a baixa antes de qualquer "
            "nova cobrança."
        )
    else:
        texto = (
            "Prosseguir conforme o procedimento "
            "de cobrança e registrar a próxima "
            "interação no HubCobrança."
        )

    return [
        "══════════════════════════════════════",
        "ORIENTAÇÃO",
        "══════════════════════════════════════",
        texto,
    ]


def _gerar_orientacao_retirada(
    contexto: dict
) -> list:
    fatura = contexto.get(
        "fatura"
    ) or {}

    if _fatura_paga(fatura):
        texto = (
            "A fatura vinculada consta como paga "
            "no IXC. Validar a situação financeira "
            "antes de realizar a retirada."
        )
    else:
        texto = (
            "Antes da retirada, verificar a "
            "possibilidade de regularização do "
            "débito conforme o procedimento vigente. "
            "Caso a retirada seja necessária, conferir "
            "todos os equipamentos e patrimônios "
            "relacionados ao contrato."
        )

    return [
        "══════════════════════════════════════",
        "ORIENTAÇÃO",
        "══════════════════════════════════════",
        texto,
    ]


def gerar_os_cobranca(
    contexto: dict,
    acao: str = "",
    obs: str = "",
) -> str:
    """
    Gera somente o conteúdo textual de uma OS
    de cobrança.

    Não cria nem altera OS no IXC.
    """

    linhas = [
        "══════════════════════════════════════",
        "COBRANÇA — INADIMPLÊNCIA",
        "══════════════════════════════════════",
        "",
    ]

    linhas.extend(
        _gerar_secao_cliente(contexto)
    )

    linhas.append("")
    linhas.extend(
        _gerar_secao_debito(contexto)
    )

    linhas.append("")
    linhas.extend(
        _gerar_secao_historico(contexto)
    )

    linhas.append("")
    linhas.extend(
        _gerar_secao_situacao(contexto)
    )

    linhas.append("")
    linhas.extend(
        _gerar_secao_atendimento(
            acao,
            obs
        )
    )

    linhas.append("")
    linhas.extend(
        _gerar_orientacao_cobranca(
            contexto
        )
    )

    return "\n".join(linhas)


def gerar_os_retirada(
    contexto: dict,
    acao: str = "",
    obs: str = "",
) -> str:
    """
    Gera somente o conteúdo textual de uma OS
    de retirada.

    Não cria nem altera OS no IXC.
    """

    linhas = [
        "══════════════════════════════════════",
        "RETIRADA DE EQUIPAMENTOS",
        "══════════════════════════════════════",
        "",
    ]

    linhas.extend(
        _gerar_secao_cliente(contexto)
    )

    linhas.append("")
    linhas.extend(
        _gerar_secao_debito(contexto)
    )

    linhas.append("")
    linhas.extend(
        _gerar_secao_historico(contexto)
    )

    linhas.append("")
    linhas.extend(
        _gerar_secao_situacao(contexto)
    )

    linhas.append("")
    linhas.extend(
        _gerar_secao_equipamentos(contexto)
    )

    linhas.append("")
    linhas.extend(
        _gerar_secao_atendimento(
            acao,
            obs
        )
    )

    linhas.append("")
    linhas.extend(
        _gerar_orientacao_retirada(
            contexto
        )
    )

    return "\n".join(linhas)
