from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.core.db_local import local_query_one, local_execute
from app.core.security import verificar_senha, criar_token
import os

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "../../templates"))

TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHATS = ["2135602169", "2135602169"]

def _telegram(msg):
    try:
        import requests
        for chat in TELEGRAM_CHATS:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                data={"chat_id": chat, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except: pass

def _log_acesso(usuario_id, login, acao, request: Request, duracao_min=None, motivo=None, nome=None):
    from datetime import datetime, timezone, timedelta
    tz_br = timezone(timedelta(hours=-3))
    agora = datetime.now(tz_br).strftime('%Y-%m-%d %H:%M:%S')
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "")
    ua = request.headers.get("user-agent", "")
    local_execute(
        "INSERT INTO cob_log_acessos (usuario_id, login, acao, ip, user_agent, criado_em) VALUES (?,?,?,?,?,?)",
        (usuario_id, login, acao, ip[:100], ua[:200], agora)
    )
    # Registra sessão
    nome_display = nome or login
    if acao == "LOGIN":
        local_execute(
            "INSERT INTO cob_sessoes (usuario_id, usuario_nome, login_em, ip) VALUES (?,?,?,?)",
            (usuario_id, nome_display, agora, ip[:100])
        )
        # Verifica se já logou hoje
        from app.core.db_local import local_query_one as lqo
        from datetime import datetime, timezone, timedelta
        tz_br = timezone(timedelta(hours=-3))
        agora_dt = datetime.now(tz_br)
        hora = agora_dt.hour
        if hora < 12:
            saudacao = "☀️ Bom dia"
        elif hora < 18:
            saudacao = "🌤️ Boa tarde"
        else:
            saudacao = "🌙 Boa noite"

        hoje = agora_dt.strftime('%Y-%m-%d')
        ja_logou_hoje = lqo(
            "SELECT id FROM cob_sessoes WHERE usuario_id=? AND login_em LIKE ? AND id != last_insert_rowid()",
            (usuario_id, f"{hoje}%")
        )
        if ja_logou_hoje:
            msg_bv = f"🔄 <b>{nome_display}</b> retornou ao HubCobrança\n{saudacao}! Bem-vindo(a) de volta 👋\n🕐 {agora[11:16]} | 🌐 {ip}"
        else:
            msg_bv = f"🟢 {saudacao}, <b>{nome_display}</b>! 👋\nBem-vindo(a) ao HubCobrança\n🕐 {agora[11:16]} | 🌐 {ip}"
        _telegram(msg_bv)
    elif acao == "LOGOUT":
        # Fecha sessão aberta
        sessao = local_query_one(
            "SELECT id, login_em FROM cob_sessoes WHERE usuario_id=? AND logout_em IS NULL ORDER BY id DESC LIMIT 1",
            (usuario_id,)
        )
        if sessao:
            from datetime import datetime as dt
            try:
                ini = dt.strptime(sessao["login_em"], '%Y-%m-%d %H:%M:%S')
                fim = dt.strptime(agora, '%Y-%m-%d %H:%M:%S')
                mins = int((fim - ini).total_seconds() / 60)
            except: mins = 0
            mot = motivo or "Manual"
            local_execute(
                "UPDATE cob_sessoes SET logout_em=?, duracao_min=?, motivo_logout=? WHERE id=?",
                (agora, mins, mot, sessao["id"])
            )
            h, m = divmod(mins, 60)
            dur = f"{h}h{m:02d}min" if h else f"{m}min"
            _telegram(f"🔴 <b>{nome_display}</b> deslogou do HubCobrança\n⏱ Duração: {dur} | Motivo: {mot}\n🕐 {agora[11:16]}")

@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request, erro: str = ""):
    return templates.TemplateResponse("login.html", {"request": request, "erro": erro})

@router.post("/login")
async def login_post(request: Request, response: Response,
                     login: str = Form(...), senha: str = Form(...)):
    u = local_query_one(
        "SELECT id, nome, senha_hash, setor, nivel, aprovado, ativo FROM cob_usuarios WHERE login=?",
        (login,)
    )
    if not u:
        return templates.TemplateResponse("login.html", {"request": request, "erro": "Usuário não encontrado."})
    if not u["ativo"]:
        return templates.TemplateResponse("login.html", {"request": request, "erro": "Usuário bloqueado."})
    if not u["aprovado"]:
        return templates.TemplateResponse("login.html", {"request": request, "erro": "Aguardando aprovação do administrador."})
    if not verificar_senha(senha, u["senha_hash"]):
        return templates.TemplateResponse("login.html", {"request": request, "erro": "Senha incorreta."})

    token = criar_token({"sub": str(u["id"]), "login": login, "nome": u["nome"], "setor": u["setor"], "nivel": u["nivel"]})
    _log_acesso(u["id"], login, "LOGIN", request, nome=u["nome"])
    destino = "/cobranca/admin/" if u["nivel"] == 99 else "/cobranca/fila" if u["nivel"] == 1 else "/cobranca/"
    from datetime import datetime, timezone, timedelta
    tz_br = timezone(timedelta(hours=-3))
    agora_dt = datetime.now(tz_br)
    hoje = agora_dt.strftime('%Y-%m-%d')
    ja_logou = local_query_one(
        "SELECT id FROM cob_sessoes WHERE usuario_id=? AND login_em LIKE ? AND id != (SELECT MAX(id) FROM cob_sessoes WHERE usuario_id=?)",
        (u["id"], f"{hoje}%", u["id"])
    )
    hora = agora_dt.hour
    saudacao = "Bom dia" if hora < 12 else "Boa tarde" if hora < 18 else "Boa noite"
    msg_bv = f"Bem-vindo(a) de volta, {u['nome'].split()[0]}!" if ja_logou else f"{saudacao}, {u['nome'].split()[0]}! Bem-vindo(a) ao HubCobrança 👋"
    resp = RedirectResponse(f"{destino}?boas_vindas={msg_bv}", status_code=302)
    resp.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=28800)
    return resp

@router.get("/logout")
async def logout(request: Request, motivo: str = "Manual"):
    token = request.cookies.get("access_token")
    if token:
        from app.auth.dependencies import decode_token
        payload = decode_token(token)
        if payload:
            # Verifica se já foi registrado logout por inatividade
            from app.core.db_local import local_query_one as lqo
            sessao = lqo(
                "SELECT id, logout_em FROM cob_sessoes WHERE usuario_id=? AND logout_em IS NULL ORDER BY id DESC LIMIT 1",
                (payload.get("sub"),)
            )
            if sessao:  # Só registra se ainda não foi fechada
                _log_acesso(payload.get("sub"), payload.get("login"), "LOGOUT", request, motivo=motivo, nome=payload.get("nome"))
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp

@router.post("/api/logout-inatividade")
async def logout_inatividade(request: Request):
    token = request.cookies.get("access_token")
    if token:
        from app.auth.dependencies import decode_token
        payload = decode_token(token)
        if payload:
            _log_acesso(payload.get("sub"), payload.get("login"), "LOGOUT", request,
                       motivo="Inatividade", nome=payload.get("nome"))
    return {"ok": True}

@router.get("/registro", response_class=HTMLResponse)
async def registro_get(request: Request, msg: str = ""):
    return templates.TemplateResponse("registro.html", {"request": request, "msg": msg})

@router.post("/registro")
async def registro_post(request: Request,
                        nome: str = Form(...),
                        login: str = Form(...),
                        senha: str = Form(...),
                        senha2: str = Form(...)):
    if senha != senha2:
        return templates.TemplateResponse("registro.html", {"request": request, "msg": "erro:As senhas não coincidem."})
    if len(senha) < 6:
        return templates.TemplateResponse("registro.html", {"request": request, "msg": "erro:Senha mínima de 6 caracteres."})
    existe = local_query_one("SELECT id FROM cob_usuarios WHERE login=?", (login,))
    if existe:
        return templates.TemplateResponse("registro.html", {"request": request, "msg": "erro:Este login já está em uso."})
    from app.core.security import hash_senha
    h = hash_senha(senha)
    local_execute(
        "INSERT INTO cob_usuarios (nome, login, senha_hash, setor, nivel, aprovado, ativo) VALUES (?,?,?,?,?,?,?)",
        (nome, login, h, "Cobrança", 0, 0, 1)
    )
    return templates.TemplateResponse("registro.html", {"request": request, "msg": "ok:Cadastro realizado! Aguarde aprovação do administrador."})
