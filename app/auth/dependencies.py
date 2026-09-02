from fastapi import Request, HTTPException
from app.core.security import decodificar_token
from app.core.db_local import local_query_one

def decode_token(token: str):
    return decodificar_token(token)

def get_usuario(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        from fastapi.responses import RedirectResponse
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    payload = decodificar_token(token)
    if not payload:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    u = local_query_one(
        "SELECT id, nome, login, setor, nivel, aprovado, ativo, filial_id FROM cob_usuarios WHERE id=?",
        (int(payload["sub"]),)
    )
    if not u or not u["ativo"] or not u["aprovado"]:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    # Carrega menus permitidos para o grupo
    from app.core.permissoes import get_menus_usuario
    u = dict(u)
    menus = get_menus_usuario(u["nivel"])
    u["menus_codigos"] = [m["codigo"] for m in menus]
    u["menus"] = [dict(m) for m in menus]
    # Filial: usa a da sessão (cookie) se gestor+, senão usa a do cadastro
    filial_sessao = request.cookies.get("filial_id")
    if u["nivel"] >= 3 and filial_sessao:
        u["filial_id"] = int(filial_sessao)
    else:
        u["filial_id"] = int(u.get("filial_id") or 0)
    return u

def requer_nivel(nivel_minimo: int):
    def dep(request: Request):
        u = get_usuario(request)
        if u["nivel"] < nivel_minimo and u["nivel"] != 99:
            raise HTTPException(status_code=403, detail="Acesso não autorizado para seu nível.")
        return u
    return dep

def requer_diretoria(request: Request):
    u = get_usuario(request)
    if u["setor"] != "Diretoria" and u["nivel"] != 99:
        raise HTTPException(status_code=403, detail="Acesso restrito à Diretoria.")
    return u

def requer_permissao(dashboard_code: str):
    def dep(request: Request):
        u = get_usuario(request)
        if u["nivel"] == 99:
            return u
        perm = local_query_one(
            "SELECT id FROM cob_permissoes WHERE usuario_id=? AND dashboard_code=?",
            (u["id"], dashboard_code)
        )
        if not perm:
            raise HTTPException(status_code=403, detail=f"Sem permissão para {dashboard_code}.")
        return u
    return dep
