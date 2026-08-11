from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
import os
app = FastAPI(title="Cliquedf Cobrança", docs_url=None, redoc_url=None)
static_path = os.path.join(os.path.dirname(__file__), "../static")
app.mount("/static", StaticFiles(directory=static_path), name="static")
from app.auth.router import router as auth_router
from app.dashboards.cobranca.router import router as cob_router
from app.admin.router import router as admin_router
from app.dashboards.retiradas.router import router as ret_router
from app.dashboards.cobranca.whatsapp_router import router as whatsapp_router
app.include_router(auth_router)
app.include_router(cob_router)
app.include_router(admin_router)
app.include_router(ret_router)
app.include_router(whatsapp_router)
@app.get("/")
async def root():
    return RedirectResponse("/cobranca/")
@app.exception_handler(403)
async def forbidden(request: Request, exc):
    from fastapi.responses import HTMLResponse
    return HTMLResponse("<h2 style='font-family:sans-serif;color:#f85149;padding:40px'>403 — Acesso não autorizado.</h2>", status_code=403)
@app.exception_handler(302)
async def redirect_handler(request: Request, exc):
    return RedirectResponse("/login")
