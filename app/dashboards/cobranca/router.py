from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.auth.dependencies import get_usuario
from app.core.filters import parse_filtros
from app.core.db import query_one
import app.dashboards.cobranca.service as sv
from app.core.ixc_api import abrir_os_retirada as ixc_abrir_os, abrir_os_cobranca
from decimal import Decimal
import json, os

router = APIRouter(prefix="/cobranca")

TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
TELEGRAM_CHAT  = "-4989557189"

_tg_cache = {}  # controle de duplicidade

def _tg_acao(usuario_nome, acao, cliente_nome, obs="", pagina=""):
    import requests, time
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone(timedelta(hours=-3))).strftime('%H:%M')

    # Evita duplicidade: mesmo operador + mesmo cliente + mesma ação em 60s
    chave = f"{usuario_nome}|{cliente_nome}|{acao}"
    agora_ts = time.time()
    if chave in _tg_cache and agora_ts - _tg_cache[chave] < 60:
        return
    _tg_cache[chave] = agora_ts
    emoji = {
        "ligacao": "📞", "ligar": "📞",
        "whatsapp": "💬", "mensagem": "💬",
        "pago": "✅", "pagamento": "✅",
        "promessa": "🤝", "acordo": "🤝",
        "retirada": "🚛", "solicitar retirada": "🚛",
        "material": "📦", "recolhido": "📦",
        "negociacao": "💰", "negociação": "💰",
        "retido": "🛡️",
    }.get(acao.lower().split()[0] if acao else "", "📋")
    pag = f" — {pagina}" if pagina else ""
    obs_txt = f"\n💬 _{obs}_" if obs else ""
    msg = f"{emoji} <b>{usuario_nome}</b> → <b>{cliente_nome}</b>\n📋 {acao}{pag}{obs_txt}\n🕐 {agora}"
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except: pass
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "../../../templates"))

def jsonify(data):
    return JSONResponse(json.loads(json.dumps(data, default=lambda o: float(o) if isinstance(o, Decimal) else str(o))))

def checar_nivel(usuario, minimo, codigo_menu: str = None):
    if usuario["nivel"] == 99:
        return
    if codigo_menu:
        from app.core.permissoes import tem_permissao
        if not tem_permissao(usuario["nivel"], codigo_menu):
            raise HTTPException(status_code=403, detail="Acesso negado para seu grupo.")
        return
    if usuario["nivel"] < minimo:
        raise HTTPException(status_code=403, detail="Acesso negado")

# ─── INADIMPLÊNCIA (N2+) ─────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def painel(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    return templates.TemplateResponse("dashboards/cobranca.html", {"request": request, "usuario": usuario})

@router.get("/api/kpis")
async def api_kpis(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    return jsonify(sv.get_kpis())

@router.get("/api/lista")
async def api_lista(request: Request, faixa: str = "all", busca: str = "", pagina: int = 1, por_pagina: int = 50, ocultar_cancelados: bool = True, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    filtros = parse_filtros(faixa=faixa, busca=busca, pagina=pagina, por_pagina=por_pagina, ocultar_cancelados=ocultar_cancelados)
    return jsonify({"dados": sv.get_inadimplentes(filtros), "total": sv.count_inadimplentes(filtros)})

@router.get("/api/evolucao")
async def api_evolucao(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    return jsonify(sv.get_evolucao_diaria())

@router.get("/api/cliente/{id_cliente}")
async def api_cliente(id_cliente: int, request: Request, usuario=Depends(get_usuario)):
    return jsonify({
        "cliente":    sv.get_cliente(id_cliente),
        "faturas":    sv.get_faturas_cliente(id_cliente),
        "os":         sv.get_os_cliente(id_cliente),
        "interacoes": sv.get_interacoes_cliente(id_cliente),
    })

@router.post("/api/interacao")
async def api_interacao(request: Request, usuario=Depends(get_usuario)):
    fd = await request.form()
    fn_id_i = int(fd.get("fn_areceber_id", 0))
    acao_i  = fd.get("acao", "")
    sv.registrar_interacao(
        fn_areceber_id=fn_id_i,
        usuario_id=usuario["id"],
        acao=acao_i,
        obs=fd.get("obs", ""),
        pago=int(fd.get("pago", 0)),
        data_promessa=fd.get("data_promessa") or None
    )
    # Alerta Telegram
    from app.core.db import query_one as qo_i
    ref = request.headers.get("referer", "")
    pagina_i = "Promessas" if "/promessas" in ref else "Primeira Cobrança"
    fat_i = qo_i("SELECT id_cliente FROM ixcprovedor.fn_areceber WHERE id=%s", (fn_id_i,))
    if fat_i:
        cli_i = qo_i("SELECT razao FROM ixcprovedor.cliente WHERE id=%s", (fat_i["id_cliente"],))
        if cli_i:
            if acao_i not in ["Pagamento realizado","Pago","💰 Pagamento realizado"]: _tg_acao(usuario["nome"], acao_i, cli_i["razao"], fd.get("obs",""), pagina_i)
    return {"ok": True}

@router.post("/api/abrir-os")
async def api_abrir_os(request: Request, usuario=Depends(get_usuario)):
    fd = await request.form()
    id_cliente = int(fd.get("id_cliente", 0))
    if sv.check_os_aberta(id_cliente):
        return {"ok": False, "msg": "OS já aberta"}
    res = ixc_abrir_os(id_cliente)
    return JSONResponse(res)

# ─── FILA (N1+) ──────────────────────────────────────────────────────────────
@router.get("/fila", response_class=HTMLResponse)
async def fila(request: Request, faixa: str = "30", busca: str = "", pagina: int = 1, ocultar_cancelados: bool = True, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    from fastapi.responses import RedirectResponse

    # Admin (nivel 99) tem acesso irrestrito
    if usuario["nivel"] != 99:
        # Verifica permissão da faixa via tabela de menus
        from app.core.db_local import local_query_one as lqo
        faixa_codigo = {
            "30": "COB_FAIXA_30", "60": "COB_FAIXA_60",
            "90": "COB_FAIXA_90", "120": "COB_FAIXA_90P"
        }.get(faixa)
        if faixa_codigo:
            menu = lqo("SELECT id FROM cob_menus WHERE codigo=?", (faixa_codigo,))
            if menu:
                perm = lqo(
                    "SELECT ativo FROM cob_permissoes_menu WHERE grupo_id=? AND menu_id=?",
                    (usuario["nivel"], menu["id"])
                )
                # Se tem permissão liberada pelo admin — acesso direto
                if perm and perm["ativo"] == 1:
                    pass  # libera acesso
                elif not sv.faixa_esta_liberada(faixa):
                    degrau = sv.get_degrau_liberado()
                    return RedirectResponse(f"/cobranca/fila?faixa={degrau}&pagina=1")
        elif not sv.faixa_esta_liberada(faixa):
            degrau = sv.get_degrau_liberado()
            return RedirectResponse(f"/cobranca/fila?faixa={degrau}&pagina=1")

    filtros = parse_filtros(faixa=faixa, busca=busca, pagina=pagina, ocultar_cancelados=ocultar_cancelados)
    dados   = sv.get_fila(filtros)
    total   = sv.count_fila(filtros)
    degrau_liberado = sv.get_degrau_liberado()
    resp = templates.TemplateResponse("dashboards/fila.html", {
        "request": request, "usuario": usuario,
        "dados": dados, "total": total, "filtros": filtros,
        "pagina": filtros.pagina, "paginas": max(1, -(-total//filtros.por_pagina)),
        "degrau_liberado": degrau_liberado,
        "is_admin": usuario["nivel"] == 99,
        "faixa_30_ok": usuario["nivel"] == 99 or bool(__import__('app.core.db_local', fromlist=['local_query_one']).local_query_one("SELECT ativo FROM cob_permissoes_menu WHERE grupo_id=? AND menu_id=(SELECT id FROM cob_menus WHERE codigo='COB_FAIXA_30')", (usuario["nivel"],))),
        "faixa_60_ok": usuario["nivel"] == 99 or bool(__import__('app.core.db_local', fromlist=['local_query_one']).local_query_one("SELECT ativo FROM cob_permissoes_menu WHERE grupo_id=? AND menu_id=(SELECT id FROM cob_menus WHERE codigo='COB_FAIXA_60')", (usuario["nivel"],))),
        "faixa_90_ok": usuario["nivel"] == 99 or bool(__import__('app.core.db_local', fromlist=['local_query_one']).local_query_one("SELECT ativo FROM cob_permissoes_menu WHERE grupo_id=? AND menu_id=(SELECT id FROM cob_menus WHERE codigo='COB_FAIXA_90')", (usuario["nivel"],))),
        "faixa_90p_ok": usuario["nivel"] == 99 or bool(__import__('app.core.db_local', fromlist=['local_query_one']).local_query_one("SELECT ativo FROM cob_permissoes_menu WHERE grupo_id=? AND menu_id=(SELECT id FROM cob_menus WHERE codigo='COB_FAIXA_90P')", (usuario["nivel"],))),
    })
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp

@router.post("/api/fila/liberar-degrau")
async def api_liberar_degrau(request: Request, usuario=Depends(get_usuario)):
    """Override manual do admin para liberar o próximo degrau ou forçar uma faixa."""
    checar_nivel(usuario, 99)
    fd = await request.form()
    degrau = fd.get("degrau", "")
    if degrau not in sv.DEGRAUS:
        return JSONResponse({"ok": False, "msg": "Degrau inválido"})
    sv.set_degrau_liberado(degrau)
    return JSONResponse({"ok": True, "degrau": degrau})

@router.post("/api/registrar-cobranca")
async def api_registrar(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    fd   = await request.form()
    acao = fd.get("acao", "")
    fn_id = int(fd.get("fn_areceber_id", 0))


    pago_i = int(fd.get("pago", 0))
    sv.registrar_interacao(
        fn_areceber_id=fn_id,
        usuario_id=usuario["id"],
        acao=acao,
        obs=fd.get("obs", ""),
        pago=pago_i,
        data_promessa=fd.get("data_promessa") or None,
        # Toda interacao feita na 1a cobranca ja escala para a 2a cobranca,
        # a nao ser que o caso ja tenha sido resolvido com pagamento agora
        segunda_cobranca=0 if pago_i == 1 else 1
    )

    # Alerta Telegram
    from app.core.db import query_one as qo_f
    fat_f = qo_f("SELECT id_cliente FROM ixcprovedor.fn_areceber WHERE id=%s", (fn_id,))
    if fat_f:
        cli_f = qo_f("SELECT razao FROM ixcprovedor.cliente WHERE id=%s", (fat_f["id_cliente"],))
        if cli_f:
            if acao not in ["Pagamento realizado","Pago","💰 Pagamento realizado"]: _tg_acao(usuario["nome"], acao, cli_f["razao"], fd.get("obs",""), fd.get("pagina","Fila de Cobrança"))
    else:
        pass

    # Ações especiais
    if acao in ["🚛 Solicitar retirada", "Solicitar retirada", "📦 Material recolhido", "Material recolhido"]:
        from app.core.db import query_one, execute
        fat = query_one("SELECT id_cliente FROM ixcprovedor.fn_areceber WHERE id=%s", (fn_id,))
        if fat:
            id_cliente = fat["id_cliente"]
            cli = query_one("SELECT razao FROM ixcprovedor.cliente WHERE id=%s", (id_cliente,))
            razao = cli["razao"] if cli else ""

            if "recolhido" in acao.lower() or "Material" in acao:
                # Material recolhido — fecha OS 246 + fecha OS 39 + abre OS 38 estoque
                os246 = query_one("SELECT id FROM ixcprovedor.su_oss_chamado WHERE id_cliente=%s AND id_assunto=190 AND status='A' LIMIT 1", (id_cliente,))
                if os246:
                    execute("UPDATE ixcprovedor.su_oss_chamado SET status='F', data_fechamento=NOW() WHERE id=%s", (os246["id"],))
                # Verifica OS 39 finalizada recentemente
                os39_fin = query_one("SELECT id FROM ixcprovedor.su_oss_chamado WHERE id_cliente=%s AND id_assunto=34 AND status='F' ORDER BY data_fechamento DESC LIMIT 1", (id_cliente,))
                # Abre OS 38 se não existir
                os38 = query_one("SELECT id FROM ixcprovedor.su_oss_chamado WHERE id_cliente=%s AND id_assunto=38 AND status NOT IN ('F') LIMIT 1", (id_cliente,))
                if not os38:
                    execute("""
                        INSERT INTO ixcprovedor.su_oss_chamado
                            (id_cliente, id_assunto, mensagem, data_abertura, status, setor)
                        VALUES (%s, 38, %s, NOW(), 'A', 9)
                    """, (id_cliente, f"Devolução ao estoque — {razao}. Material recolhido informado pelo operador de cobrança."))
            else:
                # Solicitar retirada — abre OS 39 se não existir
                os39 = query_one("SELECT id FROM ixcprovedor.su_oss_chamado WHERE id_cliente=%s AND id_assunto=34 AND status NOT IN ('F') LIMIT 1", (id_cliente,))
                if not os39:
                    obs_text = fd.get("obs", "")
                    execute("""
                        INSERT INTO ixcprovedor.su_oss_chamado
                            (id_cliente, id_assunto, mensagem, data_abertura, status, setor)
                        VALUES (%s, 39, %s, NOW(), 'A', 8)
                    """, (id_cliente, f"Retirada solicitada pelo operador — {razao}. {obs_text}"))

    return {"ok": True}

@router.post("/api/abrir-os-retirada")
async def api_os_retirada(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    fd = await request.form()
    id_cliente = int(fd.get("id_cliente", 0))
    if sv.check_os_aberta(id_cliente):
        return {"ok": False, "msg": "OS já aberta"}
    res = ixc_abrir_os(id_cliente)
    return JSONResponse(res)

# ─── ANDAMENTO (N1+) ─────────────────────────────────────────────────────────
@router.get("/andamento", include_in_schema=False)
async def andamento_redirect(request: Request, usuario=Depends(get_usuario)):
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/cobranca/primeira-cobranca")

@router.get("/primeira-cobranca", response_class=HTMLResponse)
async def andamento(request: Request, faixa: str = "all", busca: str = "", pagina: int = 1,
                    filtrar_operador: int = 0, data_inicio: str = "", data_fim: str = "",
                    usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    filtros = parse_filtros(faixa=faixa, busca=busca, pagina=pagina)
    if usuario["nivel"] == 99:
        uid = filtrar_operador if filtrar_operador else None
    else:
        uid = usuario["id"]
    di = data_inicio or None
    df = data_fim or None
    dados = sv.get_andamento(filtros, usuario_id=uid, data_inicio=di, data_fim=df)
    total = sv.count_andamento(usuario_id=uid, data_inicio=di, data_fim=df)
    return templates.TemplateResponse("dashboards/primeira_cobranca.html", {
        "request": request, "usuario": usuario,
        "dados": dados, "total": total, "filtros": filtros,
        "pagina": filtros.pagina, "paginas": max(1, -(-total//filtros.por_pagina)),
        "filtrar_operador": filtrar_operador,
        "data_inicio": data_inicio, "data_fim": data_fim,
        "operadores": sv.get_operadores() if usuario["nivel"] == 99 else []
    })

@router.get("/segunda-cobranca", response_class=HTMLResponse)
async def segunda_cobranca(request: Request, pagina: int = 1, filtrar_operador: int = 0,
                           data_inicio: str = "", data_fim: str = "",
                           usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    if usuario["nivel"] == 99:
        uid = filtrar_operador if filtrar_operador else None
    else:
        uid = usuario["id"]
    di    = data_inicio or None
    df    = data_fim or None
    dados = sv.get_segunda_cobranca(usuario_id=uid, data_inicio=di, data_fim=df, pagina=pagina)
    total = sv.count_segunda_cobranca(usuario_id=uid, data_inicio=di, data_fim=df)
    return templates.TemplateResponse("dashboards/segunda_cobranca.html", {
        "request": request, "usuario": usuario,
        "dados": dados, "total": total,
        "pagina": pagina, "paginas": max(1, -(-total//30)),
        "filtrar_operador": filtrar_operador,
        "data_inicio": data_inicio, "data_fim": data_fim,
        "operadores": sv.get_operadores() if usuario["nivel"] == 99 else []
    })

@router.post("/api/mover-segunda-cobranca")
async def api_mover_segunda(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    fd = await request.form()
    ok = sv.mover_para_segunda_cobranca(
        interacao_id  = int(fd.get("interacao_id", 0)),
        acao          = fd.get("acao", ""),
        obs           = fd.get("obs", ""),
        data_promessa = fd.get("data_promessa") or None
    )
    return {"ok": ok}

@router.post("/api/atualizar-interacao")
async def api_atualizar(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    fd = await request.form()
    interacao_id  = int(fd.get("interacao_id", 0))
    acao          = fd.get("acao", "")
    obs           = fd.get("obs", "")
    pago          = int(fd.get("pago", 0))
    data_promessa = fd.get("data_promessa") or None

    # Busca interação original para saber fn_areceber_id e segunda_cobranca
    from app.core.db_local import local_query_one
    orig = local_query_one("SELECT fn_areceber_id, segunda_cobranca FROM cob_interacoes WHERE id=?", (interacao_id,))

    if orig and orig["fn_areceber_id"]:
        # Atualiza o conteudo da interacao original e marca ela como
        # resolvida, pois a nova interacao (abaixo) vai substitui-la.
        # Isso evita que as duas fiquem "abertas" ao mesmo tempo e
        # dupliquem a contagem da fila de 2a cobranca.
        sv.atualizar_interacao(interacao_id=interacao_id, acao=acao, obs=obs, pago=pago, data_promessa=data_promessa)
        from app.core.db_local import local_execute as lex_a
        lex_a("UPDATE cob_interacoes SET resolvido=1 WHERE id=?", (interacao_id,))

        # A nova interacao herda se o caso continua na 2a cobranca,
        # a nao ser que o pagamento tenha sido confirmado agora
        is_segunda = 0 if pago == 1 else (orig["segunda_cobranca"] or 0)
        # Cria nova interação quantificando para o operador atual
        sv.registrar_interacao(
            fn_areceber_id=orig["fn_areceber_id"],
            usuario_id=usuario["id"],
            acao=acao,
            obs=obs,
            pago=pago,
            data_promessa=data_promessa,
            segunda_cobranca=is_segunda
        )
        # Alerta Telegram
        from app.core.db import query_one as qo_s
        fat_s = qo_s("SELECT id_cliente FROM ixcprovedor.fn_areceber WHERE id=%s", (orig["fn_areceber_id"],))
        if fat_s:
            cli_s = qo_s("SELECT razao FROM ixcprovedor.cliente WHERE id=%s", (fat_s["id_cliente"],))
            if cli_s:
                if acao not in ["Pagamento realizado","Pago","💰 Pagamento realizado"]: _tg_acao(usuario["nome"], acao, cli_s["razao"], obs, "Segunda Cobrança")
    else:
        sv.atualizar_interacao(interacao_id=interacao_id, acao=acao, obs=obs, pago=pago, data_promessa=data_promessa)
    return {"ok": True}

# ─── PROMESSAS (N1+) ─────────────────────────────────────────────────────────
@router.get("/promessas", response_class=HTMLResponse)
async def promessas(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    return templates.TemplateResponse("dashboards/promessas.html", {"request": request, "usuario": usuario})

@router.get("/api/promessas")
async def api_promessas(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    uid = usuario["id"] if usuario["nivel"] < 99 else None
    filtros = parse_filtros()
    return jsonify({"total": sv.count_promessas_quebradas(uid), "dados": sv.get_promessas_quebradas(usuario_id=uid, filtros=filtros)})

# ─── PROMESSAS REALIZADAS (N1+) ──────────────────────────────────────────────
@router.get("/promessas-realizadas", response_class=HTMLResponse)
async def promessas_realizadas(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    return templates.TemplateResponse("dashboards/promessas_realizadas.html", {"request": request, "usuario": usuario})

@router.get("/api/promessas-realizadas")
async def api_promessas_realizadas(request: Request, usuario=Depends(get_usuario), data_ini: str = "", data_fim: str = ""):
    checar_nivel(usuario, 1)
    uid = usuario["id"] if usuario["nivel"] < 99 else None
    filtros = parse_filtros()
    di = data_ini or None
    df = data_fim or None
    return jsonify({"total": sv.count_promessas_realizadas(uid, data_ini=di, data_fim=df), "dados": sv.get_promessas_realizadas(usuario_id=uid, filtros=filtros, data_ini=di, data_fim=df)})

@router.post("/api/detectar-promessas")
async def api_detectar(request: Request, usuario=Depends(get_usuario)):
    return {"detectadas": sv.detectar_promessas_quebradas()}

@router.post("/api/resolver-promessa/{pq_id}")
async def api_resolver(pq_id: int, request: Request, usuario=Depends(get_usuario)):
    sv.resolver_promessa_quebrada(pq_id)
    return {"ok": True}

# ─── PAGOS (N2+) ─────────────────────────────────────────────────────────────
@router.get("/desempenho-equipe", response_class=HTMLResponse)
async def desempenho_equipe(request: Request, data_ini: str = "", data_fim: str = "", usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1, "GES_DESEMP_EQ")
    from app.core.db_local import local_query
    from datetime import datetime, timedelta, timezone
    tz_br = timezone(timedelta(hours=-3))
    hoje = datetime.now(tz_br).strftime('%Y-%m-%d')
    ini  = data_ini or hoje[:7] + '-01'
    fim  = data_fim or hoje
    # Dados por dia por operador
    dados = local_query("""
        SELECT u.nome, date(i.criado_em) AS dia, COUNT(*) AS total,
               SUM(CASE WHEN i.pago=1 THEN 1 ELSE 0 END) AS pagos,
               SUM(CASE WHEN i.acao='Promessa de pagamento' THEN 1 ELSE 0 END) AS promessas
        FROM cob_interacoes i
        JOIN cob_usuarios u ON u.id=i.usuario_id
        WHERE date(i.criado_em) BETWEEN ? AND ?
          AND u.nivel = 2
        GROUP BY u.nome, dia
        ORDER BY dia, u.nome
    """, (ini, fim))
    # Totais por operador
    totais = local_query("""
        SELECT u.nome, COUNT(*) AS total,
               SUM(CASE WHEN i.pago=1 THEN 1 ELSE 0 END) AS pagos,
               SUM(CASE WHEN i.acao='Promessa de pagamento' THEN 1 ELSE 0 END) AS promessas
        FROM cob_interacoes i
        JOIN cob_usuarios u ON u.id=i.usuario_id
        WHERE date(i.criado_em) BETWEEN ? AND ?
          AND u.nivel = 2
        GROUP BY u.nome
        ORDER BY total DESC
    """, (ini, fim))
    return templates.TemplateResponse("dashboards/desempenho_equipe.html", {
        "request": request, "usuario": usuario,
        "dados": [dict(d) for d in dados],
        "totais": totais,
        "data_ini": ini, "data_fim": fim,
    })

@router.get("/pagos", response_class=HTMLResponse)
async def pagos(request: Request, filtrar_operador: int = 0, pagina: int = 1, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    filtros = parse_filtros(pagina=pagina)
    if usuario["nivel"] == 99:
        uid = filtrar_operador if filtrar_operador else None
    else:
        uid = usuario["id"]
    dados   = sv.get_pagos(filtros, usuario_id=uid)
    total   = sv.count_pagos(usuario_id=uid)
    return templates.TemplateResponse("dashboards/pagos.html", {
        "request": request, "usuario": usuario,
        "dados": dados, "pagos": dados, "total": total, "filtros": filtros,
        "pagina": filtros.pagina, "paginas": max(1, -(-total//filtros.por_pagina)),
        "filtrar_operador": filtrar_operador,
        "operadores": sv.get_operadores_pagos() if usuario["nivel"] == 99 else []
    })

# ─── EQUIPE (N99) ────────────────────────────────────────────────────────────
@router.get("/equipe", response_class=HTMLResponse)
async def equipe(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1, "GES_EQUIPE")
    return templates.TemplateResponse("dashboards/equipe.html", {"request": request, "usuario": usuario})

@router.get("/api/equipe")
async def api_equipe(request: Request, data_ini: str = None, data_fim: str = None, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1, "GES_EQUIPE")
    return jsonify(sv.get_desempenho_equipe(data_ini, data_fim))

@router.get("/api/equipe/operador")
async def api_operador(request: Request, usuario_id: int, data_ini: str = None, data_fim: str = None, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1, "GES_EQUIPE")
    return jsonify({
        "desempenho": sv.get_desempenho_operador(usuario_id, data_ini, data_fim),
        "historico":  sv.get_historico_operador(usuario_id, data_ini, data_fim)
    })


# ─── MEU DESEMPENHO (N1+) ────────────────────────────────────────────────────
@router.get("/desempenho", response_class=HTMLResponse)
async def desempenho(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    return templates.TemplateResponse("dashboards/desempenho.html", {
        "request": request, "usuario": usuario
    })


@router.get("/api/top10-devedores")
async def api_top10(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    from decimal import Decimal
    def fix(r):
        return {k: float(v) if isinstance(v, Decimal) else v for k, v in dict(r).items()}
    return JSONResponse([fix(r) for r in sv.get_top10_devedores()])

@router.get("/api/inadimplencia-por-cidade")
async def api_por_cidade(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    from decimal import Decimal
    def fix(r):
        return {k: float(v) if isinstance(v, Decimal) else v for k, v in dict(r).items()}
    return JSONResponse([fix(r) for r in sv.get_inadimplencia_por_cidade()])

@router.get("/api/clientes-por-cidade/{id_cidade}")
async def api_clientes_cidade(id_cidade: int, request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    from decimal import Decimal
    def fix(r):
        return {k: float(v) if isinstance(v, Decimal) else v for k, v in dict(r).items()}
    return JSONResponse([fix(r) for r in sv.get_clientes_por_cidade(id_cidade)])


@router.post("/api/abrir-os-cobranca")
async def api_abrir_os_cobranca(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    form = await request.form()
    id_cliente = int(form.get("id_cliente", 0))
    acao       = form.get("acao", "")
    obs        = form.get("obs", "")
    fn_areceber_id = int(form.get("fn_areceber_id", 0) or 0)
    print(f"[OS-COB] id_cliente={id_cliente} acao={acao} fn_areceber_id={fn_areceber_id}", flush=True)
    if not id_cliente:
        return JSONResponse({"ok": False, "msg": "id_cliente obrigatório"})
    id_login  = sv.get_ixc_login(usuario["id"])
    id_cidade = sv.get_id_cidade_cliente(id_cliente)
    resultado = abrir_os_cobranca(id_cliente, acao, obs, id_login=id_login, id_cidade=id_cidade, fn_areceber_id=fn_areceber_id)
    return JSONResponse(resultado)


@router.post("/api/abrir-os-cobranca")
async def api_abrir_os_cobranca(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    form = await request.form()
    id_cliente = int(form.get("id_cliente", 0))
    acao       = form.get("acao", "")
    obs        = form.get("obs", "")
    fn_areceber_id = int(form.get("fn_areceber_id", 0) or 0)
    print(f"[OS-COB] id_cliente={id_cliente} acao={acao} fn_areceber_id={fn_areceber_id}", flush=True)
    if not id_cliente:
        return JSONResponse({"ok": False, "msg": "id_cliente obrigatório"})
    id_login  = sv.get_ixc_login(usuario["id"])
    id_cidade = sv.get_id_cidade_cliente(id_cliente)
    resultado = abrir_os_cobranca(id_cliente, acao, obs, id_login=id_login, id_cidade=id_cidade, fn_areceber_id=fn_areceber_id)
    return JSONResponse(resultado)


@router.get("/api/check-os-cobranca/{id_cliente}")
async def api_check_os_cobranca(id_cliente: int, request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    r = query_one("""
        SELECT id, DATE_FORMAT(data_abertura,'%%d/%%m/%%Y') AS data_abertura
        FROM ixcprovedor.su_oss_chamado
        WHERE id_cliente=%s AND id_assunto=190 AND status<>'F'
        ORDER BY data_abertura DESC LIMIT 1
    """, (id_cliente,))
    if r:
        return JSONResponse({"aberta": True, "id_os": r["id"], "data_abertura": r["data_abertura"]})
    return JSONResponse({"aberta": False})

@router.get("/api/novos-pagamentos")
async def api_novos_pagamentos(request: Request, desde: str = "", usuario=Depends(get_usuario)):
    """Retorna pagamentos novos desde o timestamp informado para o operador."""
    from app.core.db_local import local_query
    from app.core.db import query
    from datetime import datetime, timezone, timedelta
    uid = usuario["id"] if usuario["nivel"] < 99 else None
    uid_filter = f"AND usuario_id = {uid}" if uid else ""
    interagidos = local_query(f"SELECT DISTINCT fn_areceber_id FROM cob_interacoes WHERE fn_areceber_id IS NOT NULL {uid_filter}", ())
    if not interagidos:
        return JSONResponse({"novos": [], "total": 0})
    fn_ids = tuple(int(r["fn_areceber_id"]) for r in interagidos if r["fn_areceber_id"])
    ph = ",".join(["%s"]*len(fn_ids))
    desde_filter = f"AND f.baixa_data >= '{desde}'" if desde else "AND f.baixa_data >= DATE_SUB(NOW(), INTERVAL 30 MINUTE)"
    novos = query(f"""
        SELECT f.id, f.documento, f.valor_recebido,
               DATE_FORMAT(f.baixa_data,'%%H:%%i') AS hora_pag,
               c.razao
        FROM ixcprovedor.fn_areceber f
        INNER JOIN ixcprovedor.cliente c ON c.id=f.id_cliente
        WHERE f.status='R' AND f.id IN ({ph}) {desde_filter}
        ORDER BY f.baixa_data DESC LIMIT 10
    """, fn_ids)
    return JSONResponse({"novos": [dict(r) for r in novos], "total": len(novos)})


@router.get("/qualidade-vendas", response_class=HTMLResponse)
async def qualidade_vendas(request: Request, mes: str = "", vendedor: str = "", parcela: str = "", usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    from app.dashboards.cobranca.service_qualidade import (
        get_qualidade_vendas, get_kpis_qualidade,
        get_meses_disponiveis, get_vendedores_disponiveis, get_ranking_planos, get_score_vendedores,
        get_inadimplencia_cidade
    )
    from datetime import datetime, timezone, timedelta
    mes_sel = mes or datetime.now(timezone(timedelta(hours=-3))).strftime('%Y-%m')
    parc    = int(parcela) if parcela else None
    rows    = get_qualidade_vendas(mes=mes_sel, vendedor=vendedor or None, parcela=parc)
    kpis    = get_kpis_qualidade(mes=mes_sel, parcela=parc)
    return templates.TemplateResponse("dashboards/qualidade_vendas.html", {
        "request": request, "usuario": usuario,
        "rows": rows, "kpis": kpis,
        "meses": get_meses_disponiveis(),
        "vendedores": get_vendedores_disponiveis(),
        "mes_sel": mes_sel, "vendedor_sel": vendedor, "parcela_sel": parcela,
        "ranking_planos": get_ranking_planos(mes=mes_sel),
        "score_vendedores": get_score_vendedores(mes=mes_sel),
        "inad_cidade": get_inadimplencia_cidade(),
    })


@router.get("/nunca-pagaram", response_class=HTMLResponse)
async def nunca_pagaram(request: Request, pagina: int = 1, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    from app.dashboards.cobranca.service_nunca_pagaram import get_nunca_pagaram, count_nunca_pagaram, get_kpis_nunca_pagaram
    from app.core.db import query_one
    por_pagina = 30
    rows  = get_nunca_pagaram(pagina=pagina, por_pagina=por_pagina)
    total = count_nunca_pagaram()
    kpis  = get_kpis_nunca_pagaram()
    # Conta quantos já têm OS 39
    com_os39 = query_one("""
        SELECT COUNT(DISTINCT cc.id_cliente) AS total
        FROM ixcprovedor.cliente_contrato cc
        INNER JOIN ixcprovedor.fn_areceber f ON f.id_cliente=cc.id_cliente
            AND f.status='A' AND f.data_vencimento < CURDATE()
        INNER JOIN ixcprovedor.su_oss_chamado o ON o.id_cliente=cc.id_cliente
            AND o.id_assunto=34 AND o.status NOT IN ('F')
        WHERE cc.status='A'
          AND DATEDIFF(CURDATE(), cc.data_ativacao) <= 90
          AND cc.id_cliente NOT IN (
            SELECT DISTINCT id_cliente FROM ixcprovedor.fn_areceber WHERE status='R'
          )
    """, ())
    import math
    return templates.TemplateResponse("dashboards/nunca_pagaram.html", {
        "request": request, "usuario": usuario,
        "rows": rows, "total": total, "kpis": kpis,
        "com_os39": com_os39["total"] if com_os39 else 0,
        "pagina": pagina, "paginas": math.ceil(total / por_pagina),
    })


@router.post("/api/registrar-cobranca-np")
async def api_registrar_np(request: Request, usuario=Depends(get_usuario)):
    """Registra interação para clientes que nunca pagaram — vai direto para 2ª cobrança.
    Se ação negativa e sem interações anteriores → abre OS 39 automaticamente."""
    checar_nivel(usuario, 1)
    fd = await request.form()
    fn_id  = int(fd.get("fn_areceber_id", 0))
    acao   = fd.get("acao", "")
    obs    = fd.get("obs", "")
    promessa = fd.get("data_promessa") or None

    ACOES_NEGATIVAS = ["Não atendeu", "Não vai pagar"]

    # Registra interação direto na 2ª cobrança
    sv.registrar_interacao(
        fn_areceber_id=fn_id,
        usuario_id=usuario["id"],
        acao=acao,
        obs=obs,
        pago=0,
        data_promessa=promessa,
        segunda_cobranca=1
    )
    # Alerta Telegram
    from app.core.db import query_one as qo_np
    fat_np = qo_np("SELECT id_cliente FROM ixcprovedor.fn_areceber WHERE id=%s", (fn_id,))
    if fat_np:
        cli_np = qo_np("SELECT razao FROM ixcprovedor.cliente WHERE id=%s", (fat_np["id_cliente"],))
        if cli_np:
            if acao not in ["Pagamento realizado","Pago","💰 Pagamento realizado"]: _tg_acao(usuario["nome"], acao, cli_np["razao"], obs, "Nunca Pagaram")

    abriu_os39 = False
    # Se ação negativa — verifica se já tinha interações anteriores
    if acao in ACOES_NEGATIVAS:
        from app.core.db_local import local_query_one
        from app.core.db import query_one, execute
        inter_anterior = local_query_one("""
            SELECT COUNT(*) AS total FROM cob_interacoes
            WHERE fn_areceber_id=? AND id != (SELECT MAX(id) FROM cob_interacoes WHERE fn_areceber_id=?)
        """, (fn_id, fn_id))

        # Se não tinha interação anterior — abre OS 39
        if inter_anterior and inter_anterior["total"] == 0:
            fat = query_one("SELECT id_cliente FROM ixcprovedor.fn_areceber WHERE id=%s", (fn_id,))
            if fat:
                id_cliente = fat["id_cliente"]
                os_existe = query_one("""
                    SELECT id FROM ixcprovedor.su_oss_chamado
                    WHERE id_cliente=%s AND id_assunto=34 AND status NOT IN ('F') LIMIT 1
                """, (id_cliente,))
                if not os_existe:
                    cli = query_one("SELECT razao FROM ixcprovedor.cliente WHERE id=%s", (id_cliente,))
                    razao = cli["razao"] if cli else ""
                    execute("""
                        INSERT INTO ixcprovedor.su_oss_chamado
                            (id_cliente, id_assunto, mensagem, data_abertura, status, setor)
                        VALUES (%s, 39, %s, NOW(), 'A', 8)
                    """, (id_cliente, f"RETIRADA — {razao} nunca pagou. Ação: {acao}. {obs}"))
                    abriu_os39 = True

    return {"ok": True, "abriu_os39": abriu_os39}


@router.get("/reprovados-serasa", response_class=HTMLResponse)
async def reprovados_serasa(request: Request, data_ini: str = "2026-01-01", data_fim: str = "", usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    from app.dashboards.cobranca.service_reprovados import get_reprovados_ativados, get_kpis_reprovados
    from datetime import datetime, timezone, timedelta
    hoje = datetime.now(timezone(timedelta(hours=-3))).strftime('%Y-%m-%d')
    fim  = data_fim or hoje
    rows = get_reprovados_ativados(data_ini=data_ini, data_fim=fim)
    kpis = get_kpis_reprovados(data_ini=data_ini, data_fim=fim)
    return templates.TemplateResponse("dashboards/reprovados_serasa.html", {
        "request": request, "usuario": usuario,
        "rows": rows, "kpis": kpis,
        "data_ini": data_ini, "data_fim": fim,
    })


@router.get("/cancelamentos", response_class=HTMLResponse)
async def cancelamentos(request: Request, data_ini: str = "", data_fim: str = "", pagina: int = 1, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    from app.dashboards.cobranca.service_cancelamentos import get_cancelamentos, get_kpis_cancelamentos, get_resumo_motivos, get_resumo_parcelas
    from datetime import datetime, timezone, timedelta
    import math
    agora = datetime.now(timezone(timedelta(hours=-3)))
    ini   = data_ini or agora.strftime("%Y-%m-01")
    fim   = data_fim or agora.strftime("%Y-%m-%d")
    por_pagina = 30
    rows  = get_cancelamentos(data_ini=ini, data_fim=fim, pagina=pagina, por_pagina=por_pagina)
    kpis  = get_kpis_cancelamentos(data_ini=ini, data_fim=fim)
    total = kpis.get("total", 0)
    return templates.TemplateResponse("dashboards/cancelamentos.html", {
        "request": request, "usuario": usuario,
        "rows": rows, "kpis": kpis,
        "motivos": get_resumo_motivos(data_ini=ini, data_fim=fim),
        "parc": get_resumo_parcelas(data_ini=ini, data_fim=fim),
        "data_ini": ini, "data_fim": fim,
        "pagina": pagina, "paginas": math.ceil(total / por_pagina) if total else 1,
    })


@router.get("/resultado-nunca-pagaram", response_class=HTMLResponse)
async def resultado_nunca_pagaram(request: Request, data_ini: str = "2026-01-01", data_fim: str = "", pagina: int = 1, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    from app.dashboards.cobranca.service_resultado_np import get_resultado_nunca_pagaram, count_resultado_nunca_pagaram, get_kpis_resultado
    from datetime import datetime, timezone, timedelta
    import math
    agora = datetime.now(timezone(timedelta(hours=-3)))
    fim = data_fim or agora.strftime("%Y-%m-%d")
    por_pagina = 30
    rows  = get_resultado_nunca_pagaram(data_ini=data_ini, data_fim=fim, pagina=pagina, por_pagina=por_pagina)
    total = count_resultado_nunca_pagaram(data_ini=data_ini, data_fim=fim)
    kpis  = get_kpis_resultado(data_ini=data_ini, data_fim=fim)
    return templates.TemplateResponse("dashboards/resultado_nunca_pagaram.html", {
        "request": request, "usuario": usuario,
        "rows": rows, "kpis": kpis,
        "data_ini": data_ini, "data_fim": fim,
        "pagina": pagina, "paginas": math.ceil(total / por_pagina) if total else 1,
    })


@router.get("/cancelamentos-inadimplencia", response_class=HTMLResponse)
async def cancelamentos_inadimplencia(request: Request, data_ini: str = "", data_fim: str = "", pagina: int = 1, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    from app.dashboards.cobranca.service_cancelamentos_inad import get_cancelamentos_inadimplencia, get_kpis_cancelamentos_inad, count_cancelamentos_inad
    from datetime import datetime, timezone, timedelta
    import math
    agora = datetime.now(timezone(timedelta(hours=-3)))
    ini = data_ini or agora.strftime("%Y-%m-01")
    fim = data_fim or agora.strftime("%Y-%m-%d")
    por_pagina = 30
    rows  = get_cancelamentos_inadimplencia(data_ini=ini, data_fim=fim, pagina=pagina, por_pagina=por_pagina)
    kpis  = get_kpis_cancelamentos_inad(data_ini=ini, data_fim=fim)
    total = count_cancelamentos_inad(data_ini=ini, data_fim=fim)
    return templates.TemplateResponse("dashboards/cancelamentos_inad.html", {
        "request": request, "usuario": usuario,
        "rows": rows, "kpis": kpis,
        "data_ini": ini, "data_fim": fim,
        "pagina": pagina, "paginas": math.ceil(total / por_pagina) if total else 1,
    })


@router.get("/retencao", response_class=HTMLResponse)
async def retencao(request: Request, pagina: int = 1, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    from app.dashboards.cobranca.service_retencao import get_retencao, get_kpis_retencao
    import math
    por_pagina = 30
    rows, total = get_retencao(pagina=pagina, por_pagina=por_pagina)
    kpis = get_kpis_retencao()
    return templates.TemplateResponse("dashboards/retencao.html", {
        "request": request, "usuario": usuario,
        "rows": rows, "kpis": kpis,
        "pagina": pagina, "paginas": math.ceil(total / por_pagina) if total else 1,
    })


@router.get("/retencao", response_class=HTMLResponse)
async def retencao(request: Request, pagina: int = 1, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    from app.dashboards.cobranca.service_retencao import get_retencao, get_kpis_retencao
    import math
    por_pagina = 30
    rows, total = get_retencao(pagina=pagina, por_pagina=por_pagina)
    kpis = get_kpis_retencao()
    return templates.TemplateResponse("dashboards/retencao.html", {
        "request": request, "usuario": usuario,
        "rows": rows, "kpis": kpis,
        "pagina": pagina, "paginas": math.ceil(total / por_pagina) if total else 1,
    })


@router.post("/api/retencao-contato")
async def api_retencao_contato(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    from app.core.db_local import local_execute
    from datetime import datetime, timezone, timedelta
    fd = await request.form()
    local_execute("""
        INSERT INTO cob_retencao_contatos (cliente_id, usuario_id, tipo, obs, criado_em)
        VALUES (?,?,?,?,?)
    """, (int(fd.get("cliente_id",0)), usuario["id"], fd.get("tipo",""), fd.get("obs",""),
          datetime.now(timezone(timedelta(hours=-3))).strftime('%Y-%m-%d %H:%M:%S')))
    return {"ok": True}

@router.post("/api/retencao-retido")
async def api_retencao_retido(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    from app.core.db_local import local_execute
    from datetime import datetime, timezone, timedelta
    fd = await request.form()
    local_execute("""
        INSERT INTO cob_retencao_resultados (cliente_id, usuario_id, acao, obs, criado_em)
        VALUES (?,?,?,?,?)
    """, (int(fd.get("cliente_id",0)), usuario["id"], fd.get("acao",""), fd.get("obs",""),
          datetime.now(timezone(timedelta(hours=-3))).strftime('%Y-%m-%d %H:%M:%S')))
    return {"ok": True}


@router.get("/gerencial", response_class=HTMLResponse)
async def gerencial(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 3)
    from app.dashboards.cobranca.service_gerencial import get_dashboard_gerencial
    d = get_dashboard_gerencial()
    return templates.TemplateResponse("dashboards/gerencial.html", {
        "request": request, "usuario": usuario, "d": d,
    })


@router.get("/sessoes", response_class=HTMLResponse)
async def sessoes(request: Request, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 3)
    from app.dashboards.cobranca.service_sessoes import get_sessoes_dashboard
    dados = get_sessoes_dashboard()
    return templates.TemplateResponse("dashboards/sessoes.html", {
        "request": request, "usuario": usuario, **dados
    })


@router.get("/api/check-os-retirada/{fn_id}")
async def check_os_retirada(fn_id: int, request: Request, usuario=Depends(get_usuario)):
    from app.core.db import query_one
    fat = query_one("SELECT id_cliente FROM ixcprovedor.fn_areceber WHERE id=%s", (fn_id,))
    if not fat:
        return {"existe": False, "os_id": None, "id_cliente": None}
    id_cliente = fat["id_cliente"]
    os_ret = query_one("""
        SELECT id FROM ixcprovedor.su_oss_chamado
        WHERE id_cliente=%s AND id_assunto IN (34)
        AND status NOT IN ('F')
        ORDER BY data_abertura DESC LIMIT 1
    """, (id_cliente,))
    if os_ret:
        return {"existe": True, "os_id": os_ret["id"], "id_cliente": id_cliente}
    return {"existe": False, "os_id": None, "id_cliente": id_cliente}


@router.get("/api/briefing-diario")
async def api_briefing(request: Request, usuario=Depends(get_usuario)):
    """Retorna briefing do dia para o operador — só na primeira vez do dia"""
    from datetime import date
    from app.core.db_local import local_query_one, local_execute
    from app.core.db import query_one as qo

    # Só para nível 1 e 2
    if usuario["nivel"] >= 3:
        return {"mostrar": False}

    hoje = date.today().isoformat()
    uid  = usuario["id"]

    # Verifica se já viu hoje
    ja_viu = local_query_one(
        "SELECT id FROM cob_briefing_ciencia WHERE usuario_id=? AND data_ciencia=?",
        (uid, hoje)
    )
    if ja_viu:
        return {"mostrar": False}

    # Busca dados de prioridade
    from app.core.db_local import local_query_one as lqo

    # Promessas quebradas
    pq = lqo("SELECT COUNT(*) AS total FROM cob_promessas_quebradas WHERE resolvido=0", ())
    total_pq = int(pq["total"]) if pq else 0

    # Segunda cobrança
    sc = lqo("""SELECT COUNT(DISTINCT fn_areceber_id) AS total FROM cob_interacoes
                WHERE segunda_cobranca=1 AND pago=0 AND (resolvido IS NULL OR resolvido=0)""", ())
    total_sc = int(sc["total"]) if sc else 0

    # Primeira cobrança
    from app.dashboards.cobranca.service import count_andamento
    total_pc = count_andamento(usuario_id=uid if usuario["nivel"]==1 else None)

    return {
        "mostrar": True,
        "nome": usuario["nome"].split()[0],
        "promessas_quebradas": total_pq,
        "segunda_cobranca": total_sc,
        "primeira_cobranca": total_pc,
        "total": total_pq + total_sc + total_pc
    }

@router.post("/api/briefing-ciencia")
async def api_briefing_ciencia(request: Request, usuario=Depends(get_usuario)):
    """Registra que o operador viu e confirmou o briefing do dia"""
    from datetime import date
    from app.core.db_local import local_execute
    hoje = date.today().isoformat()
    agora = __import__('datetime').datetime.now(__import__('datetime').timezone(
        __import__('datetime').timedelta(hours=-3))).strftime('%Y-%m-%d %H:%M:%S')
    local_execute(
        "INSERT OR IGNORE INTO cob_briefing_ciencia (usuario_id, data_ciencia, criado_em) VALUES (?,?,?)",
        (usuario["id"], hoje, agora)
    )
    # Alerta Telegram
    TELEGRAM_TOKEN = "8027006096:AAHiJEdtFyPresI81tWgs-Je2PKdaYAyWtY"
    TELEGRAM_CHAT  = "-4989557189"
    try:
        import requests as req
        nome = usuario["nome"]
        hora = agora[11:16]
        msg = (f"✅ <b>{nome}</b> logou e está ciente das atividades do dia\n"
               f"🕐 {hora} | Pronto para iniciar atendimento!")
        req.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except: pass
    return {"ok": True}


@router.get("/equipamentos-cancelados", response_class=HTMLResponse)
async def equipamentos_cancelados(request: Request, meses: int = 6, mes_filtro: str = "", usuario=Depends(get_usuario)):
    checar_nivel(usuario, 2)
    from app.dashboards.cobranca.service_equipamentos import get_kpis_equipamentos, get_equipamentos_cancelados
    kpis = get_kpis_equipamentos(meses=meses)
    rows = get_equipamentos_cancelados(meses=meses, mes_filtro=mes_filtro or None)
    return templates.TemplateResponse("dashboards/equipamentos_cancelados.html", {
        "request": request, "usuario": usuario,
        "kpis": kpis, "rows": rows,
        "meses": meses, "mes_filtro": mes_filtro,
    })

@router.get("/api/desempenho")
async def api_desempenho(request: Request, data_ini: str = None, data_fim: str = None, usuario=Depends(get_usuario)):
    checar_nivel(usuario, 1)
    return jsonify({
        "desempenho": sv.get_desempenho_operador(usuario["id"], data_ini, data_fim),
        "historico":  sv.get_historico_operador(usuario["id"], data_ini, data_fim)
    })
