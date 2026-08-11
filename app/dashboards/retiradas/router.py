from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.auth.dependencies import get_usuario
from app.dashboards.cobranca.router import checar_nivel
import app.dashboards.retiradas.service as sv
from decimal import Decimal
import json, os

router = APIRouter(prefix="/retiradas")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "../../../templates"))

def jsonify(data):
    return JSONResponse(json.loads(json.dumps(data, default=lambda o: float(o) if isinstance(o, Decimal) else str(o))))

# ─── DASHBOARD ────────────────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, usuario=Depends(get_usuario)):
    kpis      = sv.get_kpis_retiradas()
    cidades   = sv.get_cidades_retiradas()
    historico = sv.get_historico_monitoramento()
    tecnicos  = sv.get_tecnicos()
    return templates.TemplateResponse("dashboards/retiradas/index.html", {
        "request": request, "usuario": usuario,
        "kpis": kpis, "cidades": cidades,
        "historico": historico, "tecnicos": tecnicos
    })

# ─── SEM AGENDAMENTO ──────────────────────────────────────────────────────────
@router.get("/sem-agendamento", response_class=HTMLResponse)
async def sem_agendamento(request: Request, busca: str = "", cidade: int = 0,
                          pagina: int = 1, usuario=Depends(get_usuario)):
    dados    = sv.get_os_sem_agendamento(busca=busca, cidade=cidade, pagina=pagina)
    total    = sv.count_os_sem_agendamento(busca=busca, cidade=cidade)
    cidades  = sv.get_cidades_retiradas()
    tecnicos = sv.get_tecnicos()
    paginas  = max(1, -(-total // 30))
    return templates.TemplateResponse("dashboards/retiradas/sem_agendamento.html", {
        "request": request, "usuario": usuario,
        "dados": dados, "total": total, "paginas": paginas,
        "pagina": pagina, "busca": busca, "cidade": cidade,
        "cidades": cidades, "tecnicos": tecnicos
    })

# ─── AGENDADAS ────────────────────────────────────────────────────────────────
@router.get("/agendadas", response_class=HTMLResponse)
async def agendadas(request: Request, busca: str = "", cidade: int = 0,
                    tecnico: int = 0, pagina: int = 1, usuario=Depends(get_usuario)):
    dados    = sv.get_os_agendadas(busca=busca, cidade=cidade, tecnico=tecnico, pagina=pagina)
    total    = sv.count_os_agendadas(busca=busca, cidade=cidade, tecnico=tecnico)
    cidades  = sv.get_cidades_retiradas()
    tecnicos = sv.get_tecnicos()
    paginas  = max(1, -(-total // 30))
    return templates.TemplateResponse("dashboards/retiradas/agendadas.html", {
        "request": request, "usuario": usuario,
        "dados": dados, "total": total, "paginas": paginas,
        "pagina": pagina, "busca": busca, "cidade": cidade, "tecnico": tecnico,
        "cidades": cidades, "tecnicos": tecnicos
    })

# ─── API AGENDAR ──────────────────────────────────────────────────────────────
@router.post("/api/agendar")
async def api_agendar(request: Request, usuario=Depends(get_usuario)):
    form         = await request.form()
    id_os        = int(form.get("id_os", 0))
    id_cliente   = int(form.get("id_cliente", 0))
    id_tecnico   = int(form.get("id_tecnico", 0))
    data_agenda  = form.get("data_agenda", "")
    obs          = form.get("obs", "")
    if not id_os or not id_tecnico:
        return JSONResponse({"ok": False, "msg": "id_os e id_tecnico obrigatórios"})
    ok, msg = sv.agendar_os(id_os, id_cliente, id_tecnico, usuario["id"], data_agenda, obs)
    return JSONResponse({"ok": ok, "msg": msg})

# ─── API CANCELAR AGENDAMENTO ─────────────────────────────────────────────────
@router.post("/api/cancelar-agendamento")
async def api_cancelar(request: Request, usuario=Depends(get_usuario)):
    form  = await request.form()
    id_os = int(form.get("id_os", 0))
    if not id_os:
        return JSONResponse({"ok": False, "msg": "id_os obrigatório"})
    sv.cancelar_agendamento(id_os)
    return JSONResponse({"ok": True})

# ─── DASHBOARD MONITORAMENTO ─────────────────────────────────────────────────
@router.get("/monitoramento", response_class=HTMLResponse)
async def monitoramento(request: Request, usuario=Depends(get_usuario)):
    from app.core.db_local import local_query, local_query_one
    execucoes = local_query("SELECT * FROM cob_monitoramento_execucoes ORDER BY id DESC LIMIT 30", ())
    totais    = local_query_one("SELECT SUM(pagaram) AS pagaram, SUM(retiradas) AS retiradas, COUNT(*) AS execucoes FROM cob_monitoramento_execucoes")
    pagaram   = local_query("SELECT * FROM cob_monitoramento_os WHERE tipo='pagou' ORDER BY id DESC LIMIT 50", ())
    retiradas = local_query("SELECT * FROM cob_monitoramento_os WHERE tipo='retirada' ORDER BY id DESC LIMIT 50", ())
    return templates.TemplateResponse("dashboards/retiradas/monitoramento.html", {
        "request": request, "usuario": usuario,
        "execucoes": execucoes, "totais": totais,
        "pagaram": pagaram, "retiradas": retiradas,
    })

# ─── API KPIs ─────────────────────────────────────────────────────────────────
@router.get("/api/kpis")
async def api_kpis(request: Request, usuario=Depends(get_usuario)):
    return jsonify(sv.get_kpis_retiradas())

# ─── API TECNICOS ─────────────────────────────────────────────────────────────
@router.get("/api/tecnicos")
async def api_tecnicos(request: Request, usuario=Depends(get_usuario)):
    return jsonify(sv.get_tecnicos())

# ─── ADMIN TÉCNICOS ───────────────────────────────────────────────────────────
@router.get("/admin/tecnicos", response_class=HTMLResponse)
async def admin_tecnicos(request: Request, usuario=Depends(get_usuario)):
    if usuario["nivel"] != 99:
        from fastapi import HTTPException
        raise HTTPException(status_code=403)
    tecnicos = sv.get_tecnicos_todos()
    return templates.TemplateResponse("dashboards/retiradas/admin_tecnicos.html", {
        "request": request, "usuario": usuario, "tecnicos": tecnicos
    })

@router.post("/admin/tecnicos/salvar")
async def salvar_tecnico(request: Request, usuario=Depends(get_usuario)):
    if usuario["nivel"] != 99:
        from fastapi import HTTPException
        raise HTTPException(status_code=403)
    form         = await request.form()
    id_tec       = form.get("id", "")
    nome         = form.get("nome", "").strip()
    ixc_login_id = int(form.get("ixc_login_id", 0))
    telefone     = form.get("telefone", "").strip()
    if not nome or not ixc_login_id:
        return JSONResponse({"ok": False, "msg": "Nome e ID IXC obrigatórios"})
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone(timedelta(hours=-3))).strftime('%Y-%m-%d %H:%M:%S')
    if id_tec:
        sv.atualizar_tecnico(int(id_tec), nome, ixc_login_id, telefone)
    else:
        sv.inserir_tecnico(nome, ixc_login_id, telefone, agora)
    return JSONResponse({"ok": True})

@router.post("/admin/tecnicos/desativar")
async def desativar_tecnico(request: Request, usuario=Depends(get_usuario)):
    if usuario["nivel"] != 99:
        from fastapi import HTTPException
        raise HTTPException(status_code=403)
    form   = await request.form()
    id_tec = int(form.get("id", 0))
    sv.desativar_tecnico(id_tec)
    return JSONResponse({"ok": True})


@router.get("/auditoria", response_class=HTMLResponse)
async def auditoria_retiradas(request: Request, data_ini: str = "", data_fim: str = "", usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1, "RET_MONITOR")
    from app.dashboards.retiradas.service_auditoria import get_ranking_tecnicos, get_os_pendentes_auditoria, get_kpis_auditoria
    from datetime import datetime, timedelta, timezone
    tz_br = timezone(timedelta(hours=-3))
    hoje = datetime.now(tz_br).strftime('%Y-%m-%d')
    ini  = data_ini or (datetime.now(tz_br) - timedelta(days=30)).strftime('%Y-%m-%d')
    fim  = data_fim or hoje
    return templates.TemplateResponse("dashboards/retiradas/auditoria.html", {
        "request": request, "usuario": usuario,
        "ranking":      get_ranking_tecnicos(ini, fim),
        "os_pendentes": get_os_pendentes_auditoria(),
        "kpis":         get_kpis_auditoria() or {},
        "data_ini": ini, "data_fim": fim,
    })

@router.post("/admin/tecnicos/ativar")
async def ativar_tecnico(request: Request, usuario=Depends(get_usuario)):
    if usuario["nivel"] != 99:
        from fastapi import HTTPException
        raise HTTPException(status_code=403)
    form   = await request.form()
    id_tec = int(form.get("id", 0))
    sv.ativar_tecnico(id_tec)
    return JSONResponse({"ok": True})
