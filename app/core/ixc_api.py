import requests
import base64
from app.config import IXC_API_URL, IXC_API_USER, IXC_API_TOKEN
from app.core.db import query_one

def _auth():
    token = f"{IXC_API_USER}:{IXC_API_TOKEN}".encode("utf-8")
    return "Basic " + base64.b64encode(token).decode("utf-8")

def _get_dados_cliente(id_cliente: int) -> dict:
    r = query_one("""
        SELECT c.endereco, c.numero, c.bairro, c.cidade AS id_cidade,
               c.latitude, c.longitude, c.cep,
               u.sigla AS uf_sigla, cid.nome AS cidade_nome
        FROM ixcprovedor.cliente c
        LEFT JOIN ixcprovedor.cidade cid ON cid.id = c.cidade
        LEFT JOIN ixcprovedor.uf u ON u.id = c.uf
        WHERE c.id = %s
    """, (id_cliente,))
    return dict(r) if r else {}

def abrir_os_retirada(id_cliente: int, mensagem: str = "") -> dict:
    """Abre OS de retirada de equipamento (assunto 39) no IXC."""
    url = f"{IXC_API_URL}/webservice/v1/su_oss_chamado"

    cli = _get_dados_cliente(id_cliente)

    # Monta endereco no formato IXC
    uf      = cli.get("uf_sigla", "")
    cidade  = cli.get("cidade_nome", "")
    cep     = cli.get("cep", "")
    bairro  = cli.get("bairro", "")
    end     = cli.get("endereco", "")
    numero  = cli.get("numero", "SN")
    endereco_completo = f"{uf} {cidade} {cep} {bairro} - {end}, {numero}".strip()

    data = {
        "tipo":                      "C",
        "id_assunto":                "34",
        "id_cliente":                str(id_cliente),
        "id_filial":                 "1",
        "id_login":                  "0",
        "setor":                     "27",
        "origem_endereco":           "C",
        "origem_endereco_estrutura": "E",
        "prioridade":                "B",
        "melhor_horario_agenda":     "Q",
        "mensagem":                  mensagem or "OS de retirada de equipamento — sistema de cobranca Cliquedf",
        "status":                    "A",
        "status_assinatura":         "A",
        "gera_comissao":             "S",
        "liberado":                  "1",
        "impresso":                  "N",
        "origem_cadastro":           "P",
        "origem_change_endereco":    "default",
        "status_sla":                "NULL",
        "valor_unit_comissao":       "0,00",
        "valor_total_comissao":      "0,00",
        "endereco":                  endereco_completo,
        "bairro":                    bairro,
        "id_cidade":                 str(cli.get("id_cidade", "")),
        "latitude":                  str(cli.get("latitude", "")),
        "longitude":                 str(cli.get("longitude", "")),
    }

    headers = {
        "Authorization": _auth(),
        "ixcsoft": ""
    }

    try:
        r = requests.post(url, data=data, headers=headers, timeout=10)
        res = r.json()
        if res.get("type") == "success":
            return {"ok": True, "id_os": res.get("id", ""), "msg": "OS criada com sucesso"}
        return {"ok": False, "msg": res.get("message", str(res))}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def abrir_os_cobranca(id_cliente: int, acao: str, obs: str = "", id_login: int = 0, id_cidade: int = 0, fn_areceber_id: int = 0) -> dict:
    """Abre OS de cobrança (assunto 190, setor 7) no IXC.
    Só abre se não houver OS aberta com esse assunto para o cliente.
    Mensagem = acao + obs combinados, com o ID da fatura sendo cobrada.
    """
    # Verifica OS já aberta
    existente = query_one("""
        SELECT id FROM ixcprovedor.su_oss_chamado
        WHERE id_cliente = %s AND id_assunto = 190 AND status <> 'F'
        LIMIT 1
    """, (id_cliente,))
    if existente:
        return {"ok": False, "ja_existe": True, "id_os": existente["id"],
                "msg": f"Já existe OS de cobrança aberta #{existente['id']}"}

    mensagem = f"Fatura #{fn_areceber_id} — {acao}" if fn_areceber_id else acao
    if obs and obs.strip():
        mensagem = f"{mensagem} — {obs.strip()}"

    url = f"{IXC_API_URL}/webservice/v1/su_oss_chamado"
    data = {
        "tipo":                   "C",
        "id_assunto":             "190",
        "id_cliente":             str(id_cliente),
        "id_filial":              "1",
        "id_login":               str(id_login) if id_login else "0",
        "id_tecnico":             str(id_login) if id_login else "0",
        "setor":                  "7",
        "mensagem":               mensagem,
        "status":                 "A",
        "prioridade":             "B",
        "melhor_horario_agenda":  "Q",
        "gera_comissao":          "N",
        "liberado":               "1",
        "impresso":               "N",
        "origem_cadastro":        "P",
        "origem_endereco":        "C",
        "id_cidade":              str(id_cidade) if id_cidade else "",
        "status_pesquisa_satisfacao": "0",
    }
    headers = {"Authorization": _auth(), "ixcsoft": ""}
    try:
        r = requests.post(url, data=data, headers=headers, timeout=10)
        res = r.json()
        if res.get("type") == "success":
            return {"ok": True, "id_os": res.get("id",""), "msg": "OS de cobrança criada"}
        return {"ok": False, "ja_existe": False, "msg": res.get("message", str(res))}
    except Exception as e:
        return {"ok": False, "ja_existe": False, "msg": str(e)}

def abrir_os_cobranca(id_cliente: int, acao: str, obs: str = "", id_login: int = 0, id_cidade: int = 0, fn_areceber_id: int = 0) -> dict:
    """Abre OS de cobrança (assunto 190, setor 7) no IXC.
    Só abre se não houver OS aberta com esse assunto para o cliente.
    Mensagem = acao + obs combinados, com o ID da fatura sendo cobrada.
    """
    # Verifica OS já aberta
    existente = query_one("""
        SELECT id FROM ixcprovedor.su_oss_chamado
        WHERE id_cliente = %s AND id_assunto = 190 AND status <> 'F'
        LIMIT 1
    """, (id_cliente,))
    if existente:
        return {"ok": False, "ja_existe": True, "id_os": existente["id"],
                "msg": f"Já existe OS de cobrança aberta #{existente['id']}"}

    mensagem = f"Fatura #{fn_areceber_id} — {acao}" if fn_areceber_id else acao
    if obs and obs.strip():
        mensagem = f"{mensagem} — {obs.strip()}"

    url = f"{IXC_API_URL}/webservice/v1/su_oss_chamado"
    data = {
        "tipo":                   "C",
        "id_assunto":             "190",
        "id_cliente":             str(id_cliente),
        "id_filial":              "1",
        "id_login":               str(id_login) if id_login else "0",
        "id_tecnico":             str(id_login) if id_login else "0",
        "setor":                  "7",
        "mensagem":               mensagem,
        "status":                 "A",
        "prioridade":             "B",
        "melhor_horario_agenda":  "Q",
        "gera_comissao":          "N",
        "liberado":               "1",
        "impresso":               "N",
        "origem_cadastro":        "P",
        "origem_endereco":        "C",
        "id_cidade":              str(id_cidade) if id_cidade else "",
        "status_pesquisa_satisfacao": "0",
    }
    headers = {"Authorization": _auth(), "ixcsoft": ""}
    try:
        r = requests.post(url, data=data, headers=headers, timeout=10)
        res = r.json()
        if res.get("type") == "success":
            return {"ok": True, "id_os": res.get("id",""), "msg": "OS de cobrança criada"}
        return {"ok": False, "ja_existe": False, "msg": res.get("message", str(res))}
    except Exception as e:
        return {"ok": False, "ja_existe": False, "msg": str(e)}
