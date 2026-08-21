"""
Endpoints novos do HubCobrança para a automação de WhatsApp (n8n).

Como plugar: no arquivo principal do FastAPI (main.py / app.py, onde os outros
routers já são incluídos), adicionar:

    from app.dashboards.cobranca.whatsapp_router import router as whatsapp_router
    app.include_router(whatsapp_router)

Autenticação: todos os endpoints exigem o header  X-API-Key .
Defina a chave numa variável de ambiente antes de subir o serviço:

    export WHATSAPP_COBRANCA_API_KEY="gere-uma-chave-forte-aqui"

(no systemd/service do HubCobrança, ou no .env carregado pela aplicação)
"""
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.core.db import query
from app.core.db_local import local_query, local_query_one, local_execute
from app.core.ixc_api import abrir_os_cobranca

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp-cobranca"])

API_KEY_WHATSAPP = os.getenv("WHATSAPP_COBRANCA_API_KEY", "")
BOT_USUARIO_LOGIN = "bot_whatsapp"

TZ_BR = timezone(timedelta(hours=-3))


def _now_br_str() -> str:
    return datetime.now(TZ_BR).strftime("%Y-%m-%d %H:%M:%S")


def _verifica_key(x_api_key: Optional[str]):
    if not API_KEY_WHATSAPP:
        # Falha segura: se a env var não foi configurada, bloqueia tudo
        # em vez de deixar os endpoints abertos sem senha.
        raise HTTPException(status_code=500, detail="WHATSAPP_COBRANCA_API_KEY não configurada no servidor")
    if x_api_key != API_KEY_WHATSAPP:
        raise HTTPException(status_code=401, detail="API key inválida")


def _bot_usuario_id() -> int:
    row = local_query_one("SELECT id FROM cob_usuarios WHERE login=?", (BOT_USUARIO_LOGIN,))
    if not row:
        raise HTTPException(
            status_code=500,
            detail="Usuário 'bot_whatsapp' não encontrado — rode a migration migrate_v3_whatsapp primeiro",
        )
    return row["id"]


# ─────────────────────────────────────────────────────────────────────────
# GET /api/whatsapp/fila
# ─────────────────────────────────────────────────────────────────────────
@router.get("/fila")
def fila_cobranca(x_api_key: str = Header(None, alias="X-API-Key")):
    """
    Lista faturas vencidas elegíveis para cobrança automática via WhatsApp.

    Exclui automaticamente:
      - Faturas com OS de cobrança já aberta no IXC (id_assunto=190, status<>'F')
        -> mesma regra que o time humano já usa (abrir_os_cobranca)
      - Faturas/telefones em opt-out (cob_whatsapp_optout)
      - Clientes sem telefone cadastrado
    """
    _verifica_key(x_api_key)

    inadimplentes = query(
        """
        SELECT c.id AS id_cliente, c.razao, c.cnpj_cpf,
               COALESCE(c.whatsapp, c.telefone_celular, c.fone, '') AS telefone,
               f.id AS fn_areceber_id, f.data_vencimento, f.valor_aberto, f.nparcela,
               DATEDIFF(CURDATE(), f.data_vencimento) AS dias_atraso
        FROM ixcprovedor.cliente c
        INNER JOIN ixcprovedor.cliente_contrato cc
            ON cc.id_cliente = c.id AND cc.status = 'A'
        INNER JOIN ixcprovedor.fn_areceber f
            ON f.id_cliente = c.id AND f.status = 'A' AND f.data_vencimento < CURDATE()
        WHERE NOT EXISTS (
            SELECT 1 FROM ixcprovedor.su_oss_chamado o
            WHERE o.id_cliente = c.id AND o.id_assunto = 246 AND o.status <> 'F'
        )
        GROUP BY c.id, f.id
        HAVING dias_atraso BETWEEN 1 AND 30
        ORDER BY dias_atraso DESC
        """,
        (),
    )

    if not inadimplentes:
        return {"fila": [], "total": 0}

    optouts = local_query("SELECT fn_areceber_id, telefone FROM cob_whatsapp_optout", ())
    ids_optout = {o["fn_areceber_id"] for o in optouts if o["fn_areceber_id"]}
    tel_optout = {o["telefone"] for o in optouts if o["telefone"]}

    fila = [
        r for r in inadimplentes
        if r["fn_areceber_id"] not in ids_optout
        and r["telefone"] not in tel_optout
        and r["telefone"]
    ]

    return {"fila": fila, "total": len(fila)}


# ─────────────────────────────────────────────────────────────────────────
# GET /api/whatsapp/fila-reenvio
# ─────────────────────────────────────────────────────────────────────────
@router.get("/fila-reenvio")
def fila_reenvio(dias_desde_1a_msg: int = 7, x_api_key: str = Header(None, alias="X-API-Key")):
    """
    Lista faturas que já receberam a 1ª cobrança via bot há N dias (padrão 7),
    ainda não foram pagas, ainda não tiveram reenvio, e ainda não tiveram
    nenhuma resposta do cliente (etapa de sessão nunca avançou).

    Diferente de /fila: aqui o cliente NECESSARIAMENTE já tem OS 246 aberta
    (foi aberta na 1ª mensagem) — por isso precisa de query própria.
    """
    _verifica_key(x_api_key)
    usuario_id = _bot_usuario_id()

    primeiras = local_query(
        """
        SELECT fn_areceber_id, MIN(criado_em) AS primeira_em, COUNT(*) AS qtd
        FROM cob_interacoes
        WHERE usuario_id = ? AND acao = 'whatsapp' AND obs LIKE '1a_cobranca%'
          AND (pago IS NULL OR pago = 0)
        GROUP BY fn_areceber_id
        """,
        (usuario_id,),
    )

    ja_reenviados = {
        r["fn_areceber_id"]
        for r in local_query(
            "SELECT DISTINCT fn_areceber_id FROM cob_interacoes WHERE usuario_id=? AND acao='whatsapp' AND obs LIKE 'reenvio%'",
            (usuario_id,),
        )
    }

    elegiveis_ids = [
        r["fn_areceber_id"]
        for r in primeiras
        if r["fn_areceber_id"] not in ja_reenviados
        and (datetime.now(TZ_BR) - datetime.strptime(r["primeira_em"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ_BR)).days >= dias_desde_1a_msg
    ]

    if not elegiveis_ids:
        return {"fila": [], "total": 0}

    ph = ",".join(["%s"] * len(elegiveis_ids))
    dados = query(
        f"""
        SELECT c.id AS id_cliente, c.razao, c.cnpj_cpf,
               COALESCE(c.whatsapp, c.telefone_celular, c.fone, '') AS telefone,
               f.id AS fn_areceber_id, f.data_vencimento, f.valor_aberto, f.nparcela,
               DATEDIFF(CURDATE(), f.data_vencimento) AS dias_atraso
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente c ON c.id = f.id_cliente
        WHERE f.id IN ({ph}) AND f.status = 'A'
        """,
        tuple(elegiveis_ids),
    )

    optouts_tel = {o["telefone"] for o in local_query("SELECT telefone FROM cob_whatsapp_optout", ()) if o["telefone"]}
    # Trava de segurança: se já passou dos 30 dias, o cliente virou "humanizado" — a automação não reenvia mais
    fila = [
        r for r in dados
        if r["telefone"] and r["telefone"] not in optouts_tel and r["dias_atraso"] <= 30
    ]

    return {"fila": fila, "total": len(fila)}


# ─────────────────────────────────────────────────────────────────────────
# Geração de Pix copia-e-cola (padrão EMV / BR Code do Banco Central)
# ─────────────────────────────────────────────────────────────────────────
def _emv_field(id_: str, value: str) -> str:
    return f"{id_}{len(value):02d}{value}"


def _crc16_ccitt(payload: str) -> str:
    """CRC16-CCITT (0xFFFF), exigido no final do payload Pix pelo Bacen."""
    poly = 0x1021
    crc = 0xFFFF
    for b in payload.encode("utf-8"):
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return format(crc, "04X")


def gerar_pix_copia_cola(chave_pix: str, valor: float, txid: str, nome_recebedor: str = "CLIQUEDF", cidade: str = "NEOPOLIS") -> str:
    """
    Monta o payload Pix estático (copia-e-cola) no padrão EMV do Bacen.
    Usa a chave já cadastrada na carteira de cobrança (fn_carteira_cobranca.pix_chave) —
    não depende de nenhuma API bancária.
    """
    # Merchant Account Information (GUI + chave + opcional descrição)
    mai = _emv_field("00", "br.gov.bcb.pix") + _emv_field("01", chave_pix)
    payload = (
        _emv_field("00", "01")                          # Payload Format Indicator
        + _emv_field("26", mai)                          # Merchant Account Info (Pix)
        + _emv_field("52", "0000")                       # Merchant Category Code
        + _emv_field("53", "986")                        # Moeda (BRL)
        + _emv_field("54", f"{valor:.2f}")                # Valor
        + _emv_field("58", "BR")                          # País
        + _emv_field("59", nome_recebedor[:25])            # Nome recebedor
        + _emv_field("60", cidade[:15])                    # Cidade
        + _emv_field("62", _emv_field("05", txid[:25]))    # TXID
    )
    payload_com_crc_marker = payload + "6304"
    crc = _crc16_ccitt(payload_com_crc_marker)
    return payload_com_crc_marker + crc


@router.get("/pagamento/{fn_areceber_id}")
def dados_pagamento(fn_areceber_id: int, x_api_key: str = Header(None, alias="X-API-Key")):
    """
    Retorna os dados de pagamento da fatura para envio ao cliente via WhatsApp:
    - linha_digitavel (se a carteira for do tipo Boleto/Gateway)
    - pix_copia_cola (se a carteira tiver chave Pix configurada)
    Uma fatura pode ter os dois, um só, ou nenhum (nesse caso, escala pra humano).
    """
    _verifica_key(x_api_key)

    fatura = query(
        """
        SELECT f.id, f.valor_aberto, f.linha_digitavel, f.data_vencimento,
               f.id_carteira_cobranca, f.id_cliente,
               fc.pix_chave, fc.tipo_chave_pix, fc.permite_pagamento_por_chave_pix,
               fc.descricao, fc.tipo_recebimento
        FROM ixcprovedor.fn_areceber f
        LEFT JOIN ixcprovedor.fn_carteira_cobranca fc ON fc.id = f.id_carteira_cobranca
        WHERE f.id = %s
        """,
        (fn_areceber_id,),
    )

    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    f = fatura[0]
    resultado = {
        "ok": True,
        "fn_areceber_id": fn_areceber_id,
        "valor": float(f["valor_aberto"]),
        "vencimento": str(f["data_vencimento"]),
        "carteira": f.get("descricao"),
        "linha_digitavel": None,
        "pix_copia_cola": None,
    }

    if f.get("linha_digitavel"):
        resultado["linha_digitavel"] = f["linha_digitavel"]

    if f.get("pix_chave") and f.get("permite_pagamento_por_chave_pix") == "S":
        txid = f"COB{fn_areceber_id}"
        resultado["pix_copia_cola"] = gerar_pix_copia_cola(
            chave_pix=f["pix_chave"], valor=float(f["valor_aberto"]), txid=txid,
        )

    if not resultado["linha_digitavel"] and not resultado["pix_copia_cola"]:
        resultado["ok"] = False
        resultado["motivo"] = "Fatura sem linha digitável nem Pix configurado nessa carteira — escalar para humano"

    return resultado


@router.get("/pix/{fn_areceber_id}")
def gerar_pix(fn_areceber_id: int, x_api_key: str = Header(None, alias="X-API-Key")):
    """
    (Mantido por compatibilidade — prefira usar /pagamento/{id}, que já traz Pix + linha digitável juntos)
    Retorna o Pix copia-e-cola para a fatura informada, usando a chave
    cadastrada na carteira de cobrança vinculada a ela.
    """
    _verifica_key(x_api_key)

    fatura = query(
        """
        SELECT f.id, f.valor_aberto, f.id_carteira_cobranca, f.id_cliente,
               fc.pix_chave, fc.tipo_chave_pix, fc.permite_pagamento_por_chave_pix, fc.descricao
        FROM ixcprovedor.fn_areceber f
        LEFT JOIN ixcprovedor.fn_carteira_cobranca fc ON fc.id = f.id_carteira_cobranca
        WHERE f.id = %s
        """,
        (fn_areceber_id,),
    )

    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    f = fatura[0]

    if not f["pix_chave"] or f["permite_pagamento_por_chave_pix"] != "S":
        return {
            "ok": False,
            "motivo": "Fatura sem carteira com Pix configurado — usar apenas boleto para essa cobrança",
            "carteira": f.get("descricao"),
        }

    txid = f"COB{fn_areceber_id}"
    copia_cola = gerar_pix_copia_cola(
        chave_pix=f["pix_chave"],
        valor=float(f["valor_aberto"]),
        txid=txid,
    )

    return {
        "ok": True,
        "fn_areceber_id": fn_areceber_id,
        "valor": float(f["valor_aberto"]),
        "carteira": f["descricao"],
        "pix_copia_cola": copia_cola,
    }


# ─────────────────────────────────────────────────────────────────────────
# POST /api/whatsapp/registrar
# ─────────────────────────────────────────────────────────────────────────
class RegistrarRequest(BaseModel):
    fn_areceber_id: int
    acao: str  # ex: "whatsapp"
    obs: str
    pago: int = 0


@router.post("/registrar")
def registrar_interacao_whatsapp(req: RegistrarRequest, x_api_key: str = Header(None, alias="X-API-Key")):
    """Grava uma interação do bot em cob_interacoes, igual um atendente humano registraria."""
    _verifica_key(x_api_key)
    usuario_id = _bot_usuario_id()

    interacao_id = local_execute(
        "INSERT INTO cob_interacoes (fn_areceber_id, usuario_id, acao, obs, pago, criado_em) VALUES (?,?,?,?,?,?)",
        (req.fn_areceber_id, usuario_id, req.acao, req.obs, req.pago, _now_br_str()),
    )
    return {"ok": True, "interacao_id": interacao_id}


# ─────────────────────────────────────────────────────────────────────────
# POST /api/whatsapp/abrir-os
# ─────────────────────────────────────────────────────────────────────────
class AbrirOSRequest(BaseModel):
    id_cliente: int
    acao: str
    obs: str = ""


@router.post("/abrir-os")
def abrir_os_whatsapp(req: AbrirOSRequest, x_api_key: str = Header(None, alias="X-API-Key")):
    """Abre a OS de cobrança (id_assunto=190) no IXC, reaproveitando a função já usada pelo hub."""
    _verifica_key(x_api_key)
    resultado = abrir_os_cobranca(req.id_cliente, req.acao, req.obs)
    return {"ok": True, "resultado": resultado}


# ─────────────────────────────────────────────────────────────────────────
# POST /api/whatsapp/optout
# ─────────────────────────────────────────────────────────────────────────
class OptoutRequest(BaseModel):
    fn_areceber_id: Optional[int] = None
    cliente_id: Optional[int] = None
    telefone: str


@router.post("/optout")
def optout(req: OptoutRequest, x_api_key: str = Header(None, alias="X-API-Key")):
    """Registra opt-out — esse telefone/fatura nunca mais entra na fila automática."""
    _verifica_key(x_api_key)
    local_execute(
        "INSERT INTO cob_whatsapp_optout (fn_areceber_id, cliente_id, telefone, criado_em) VALUES (?,?,?,?)",
        (req.fn_areceber_id, req.cliente_id, req.telefone, _now_br_str()),
    )
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────
# Sessão de conversa (estado por telefone)
# ─────────────────────────────────────────────────────────────────────────
class SessaoUpsert(BaseModel):
    telefone: str
    fn_areceber_id: Optional[int] = None
    cliente_id: Optional[int] = None
    etapa: str
    canal: str = "texto"  # "texto" | "audio"
    instance_origem: Optional[str] = None
    cpf_candidato: Optional[str] = None
    dados_extra: Optional[str] = None  # JSON string livre, uso do workflow


@router.post("/sessao")
def upsert_sessao(req: SessaoUpsert, x_api_key: str = Header(None, alias="X-API-Key")):
    _verifica_key(x_api_key)
    existente = local_query_one("SELECT id FROM cob_whatsapp_sessao WHERE telefone=?", (req.telefone,))
    if existente:
        local_execute(
            """
            UPDATE cob_whatsapp_sessao
            SET fn_areceber_id=?, cliente_id=?, etapa=?, canal=?, instance_origem=?,
                cpf_candidato=?, dados_extra=?, atualizado_em=?
            WHERE telefone=?
            """,
            (
                req.fn_areceber_id, req.cliente_id, req.etapa, req.canal, req.instance_origem,
                req.cpf_candidato, req.dados_extra, _now_br_str(), req.telefone,
            ),
        )
        return {"ok": True, "id": existente["id"], "acao": "atualizado"}

    novo_id = local_execute(
        """
        INSERT INTO cob_whatsapp_sessao
            (telefone, fn_areceber_id, cliente_id, etapa, canal, instance_origem,
             cpf_candidato, dados_extra, criado_em, atualizado_em)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            req.telefone, req.fn_areceber_id, req.cliente_id, req.etapa, req.canal,
            req.instance_origem, req.cpf_candidato, req.dados_extra, _now_br_str(), _now_br_str(),
        ),
    )
    return {"ok": True, "id": novo_id, "acao": "criado"}


@router.get("/sessao/{telefone}")
def get_sessao(telefone: str, x_api_key: str = Header(None, alias="X-API-Key")):
    _verifica_key(x_api_key)
    row = local_query_one("SELECT * FROM cob_whatsapp_sessao WHERE telefone=?", (telefone,))
    return {"sessao": row}


@router.delete("/sessao/{telefone}")
def limpa_sessao(telefone: str, x_api_key: str = Header(None, alias="X-API-Key")):
    """Encerra a sessão (ex: depois de resolvida ou escalada)."""
    _verifica_key(x_api_key)
    local_execute("DELETE FROM cob_whatsapp_sessao WHERE telefone=?", (telefone,))
    return {"ok": True}
