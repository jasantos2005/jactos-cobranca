from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.auth.dependencies import requer_diretoria
from app.core.db_local import local_query, local_query_one, local_execute
from app.core.security import hash_senha
import os

router = APIRouter(prefix="/cobranca/admin", tags=["admin"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "../../templates"))

NIVEIS = {0: "Aguardando", 1: "Operador", 2: "Supervisor", 3: "Gerente", 4: "Diretoria", 99: "Desenvolvimento"}
PERMISSOES_NIVEL = {
    1: ["COB_FILA"],
    2: ["COB_FILA", "COB_ANDAMENTO", "COB_PAGOS"],
    3: ["COB_PAINEL", "COB_FILA", "COB_ANDAMENTO", "COB_PAGOS"],
    99: ["COB_PAINEL", "COB_FILA", "COB_ANDAMENTO", "COB_PAGOS", "COB_ADMIN"],
}

def _aplicar_permissoes(usuario_id: int, nivel: int):
    local_execute("DELETE FROM cob_permissoes WHERE usuario_id=?", (usuario_id,))
    for code in PERMISSOES_NIVEL.get(nivel, []):
        local_execute(
            "INSERT INTO cob_permissoes (usuario_id, dashboard_code) VALUES (?,?)",
            (usuario_id, code)
        )

def _get_usuarios():
    return local_query("""
        SELECT u.id, u.nome, u.login, u.setor, u.nivel, u.aprovado, u.ativo,
               GROUP_CONCAT(p.dashboard_code) AS perms
        FROM cob_usuarios u
        LEFT JOIN cob_permissoes p ON p.usuario_id = u.id
        GROUP BY u.id ORDER BY u.nivel DESC, u.nome ASC
    """)

@router.get("/", response_class=HTMLResponse)
async def admin_get(request: Request, usuario=Depends(requer_diretoria), msg: str = ""):
    usuarios   = _get_usuarios()
    pendentes  = [u for u in usuarios if u["aprovado"] == 0]
    ativos     = [u for u in usuarios if u["aprovado"] == 1]
    logs = local_query("""
        SELECT login, acao, ip, strftime('%d/%m/%Y %H:%M', criado_em) AS quando
        FROM cob_log_acessos ORDER BY criado_em DESC LIMIT 50
    """)
    return templates.TemplateResponse("admin/index.html", {
        "request": request, "usuario": usuario,
        "pendentes": pendentes, "ativos": ativos,
        "logs": logs, "niveis": NIVEIS, "msg": msg
    })

@router.post("/aprovar/{uid}")
async def aprovar(request: Request, uid: int, nivel: int = Form(...), usuario=Depends(requer_diretoria)):
    local_execute("UPDATE cob_usuarios SET aprovado=1, nivel=?, ativo=1 WHERE id=?", (nivel, uid))
    _aplicar_permissoes(uid, nivel)
    return RedirectResponse("/cobranca/admin/?msg=ok:Usuário aprovado com sucesso.", status_code=302)

@router.post("/rejeitar/{uid}")
async def rejeitar(request: Request, uid: int, usuario=Depends(requer_diretoria)):
    local_execute("DELETE FROM cob_usuarios WHERE id=? AND aprovado=0", (uid,))
    return RedirectResponse("/cobranca/admin/?msg=ok:Solicitação rejeitada.", status_code=302)

@router.post("/nivel/{uid}")
async def mudar_nivel(request: Request, uid: int, nivel: int = Form(...), usuario=Depends(requer_diretoria)):
    local_execute("UPDATE cob_usuarios SET nivel=? WHERE id=?", (nivel, uid))
    _aplicar_permissoes(uid, nivel)
    return RedirectResponse("/cobranca/admin/?msg=ok:Nível atualizado.", status_code=302)

@router.post("/toggle/{uid}")
async def toggle_ativo(request: Request, uid: int, usuario=Depends(requer_diretoria)):
    u = local_query_one("SELECT ativo FROM cob_usuarios WHERE id=?", (uid,))
    novo = 0 if u["ativo"] else 1
    local_execute("UPDATE cob_usuarios SET ativo=? WHERE id=?", (novo, uid))
    return RedirectResponse("/cobranca/admin/?msg=ok:Status atualizado.", status_code=302)

@router.post("/senha/{uid}")
async def reset_senha(request: Request, uid: int, nova_senha: str = Form(...), usuario=Depends(requer_diretoria)):
    local_execute("UPDATE cob_usuarios SET senha_hash=? WHERE id=?", (hash_senha(nova_senha), uid))
    return RedirectResponse("/cobranca/admin/?msg=ok:Senha atualizada.", status_code=302)

@router.post("/criar")
async def criar_usuario(request: Request,
    nome: str = Form(...), login: str = Form(...),
    senha: str = Form(...), setor: str = Form(...),
    nivel: int = Form(...), usuario=Depends(requer_diretoria)):
    existe = local_query_one("SELECT id FROM cob_usuarios WHERE login=?", (login,))
    if existe:
        return RedirectResponse("/cobranca/admin/?msg=erro:Login já em uso.", status_code=302)
    local_execute(
        "INSERT INTO cob_usuarios (nome, login, senha_hash, setor, nivel, aprovado, ativo) VALUES (?,?,?,?,?,1,1)",
        (nome, login, hash_senha(senha), setor, nivel)
    )
    uid = local_query_one("SELECT id FROM cob_usuarios WHERE login=?", (login,))["id"]
    _aplicar_permissoes(uid, nivel)
    return RedirectResponse("/cobranca/admin/?msg=ok:Usuário criado com sucesso.", status_code=302)

@router.post("/excluir/{uid}")
async def excluir(request: Request, uid: int, usuario=Depends(requer_diretoria)):
    local_execute("DELETE FROM cob_permissoes WHERE usuario_id=?", (uid,))
    local_execute("DELETE FROM cob_usuarios WHERE id=? AND nivel != 99", (uid,))
    return RedirectResponse("/cobranca/admin/?msg=ok:Usuário removido.", status_code=302)


# ─── PERMISSÕES POR GRUPO ────────────────────────────────────────────────────
@router.get("/permissoes", response_class=HTMLResponse)
async def permissoes_get(request: Request, usuario=Depends(requer_diretoria), grupo_id: int = 1):
    from app.core.permissoes import get_grupos, get_todos_menus, get_permissoes_grupo
    grupos  = get_grupos()
    menus   = get_todos_menus()
    ativos  = get_permissoes_grupo(grupo_id)
    # Agrupa menus por secao
    secoes = {}
    for m in menus:
        s = m["secao"]
        if s not in secoes:
            secoes[s] = []
        secoes[s].append(dict(m))
    return templates.TemplateResponse("admin/permissoes.html", {
        "request": request, "usuario": usuario,
        "grupos": grupos, "secoes": secoes,
        "ativos": ativos, "grupo_id": grupo_id
    })

@router.post("/permissoes/salvar")
async def permissoes_salvar(request: Request, usuario=Depends(requer_diretoria)):
    from app.core.permissoes import salvar_permissoes
    form     = await request.form()
    grupo_id = int(form.get("grupo_id", 1))
    menu_ids = [int(v) for k, v in form.multi_items() if k == "menu_ids"]
    salvar_permissoes(grupo_id, menu_ids)
    return RedirectResponse(f"/cobranca/admin/permissoes?grupo_id={grupo_id}&msg=ok:Permissões salvas.", status_code=302)
