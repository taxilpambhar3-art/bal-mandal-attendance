from __future__ import annotations
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .auth import ROLE_HOME, ROLE_LABEL, ROLE_THEME
from .database import Base, SessionLocal, engine
from .deps import AuthRedirect
from .routers import auth, branch_admin, sanchalak, super_admin
from .seed import seed_if_empty
from .weeks import current_week_info, format_dt, gujarati_month, week_number_for

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Bal Mandal Attendance System")
app.add_middleware(SessionMiddleware, secret_key="bal-mandal-dev-secret-change-me")

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals.update(
    ROLE_LABEL=ROLE_LABEL,
    ROLE_THEME=ROLE_THEME,
    ROLE_HOME=ROLE_HOME,
    gujarati_month=gujarati_month,
    week_number_for=week_number_for,
    format_dt=format_dt,
)

# share templates with routers
auth.templates = templates
super_admin.templates = templates
branch_admin.templates = templates
sanchalak.templates = templates

app.include_router(auth.router)
app.include_router(super_admin.router)
app.include_router(branch_admin.router)
app.include_router(sanchalak.router)


@app.exception_handler(AuthRedirect)
async def auth_redirect_handler(_request: Request, exc: AuthRedirect):
    return RedirectResponse(exc.url, status_code=303)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if request.method == "GET":
        cleaned = {k: v for k, v in request.query_params.items() if v.strip()}
        if len(cleaned) != len(request.query_params):
            path = request.url.path
            return RedirectResponse(f"{path}?{urlencode(cleaned)}" if cleaned else path, status_code=303)
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


@app.get("/")
def root(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    role = request.session.get("role")
    return RedirectResponse(ROLE_HOME.get(role, "/login"), status_code=303)


@app.get("/branch")
@app.get("/branch/{path:path}")
def branch_redirect(path: str = ""):
    target = f"/branch-admin/{path}" if path else "/branch-admin/"
    return RedirectResponse(target, status_code=303)


@app.get("/health")
def health():
    info = current_week_info()
    return {"ok": True, "week": info["week_label"], "month": info["month_name"]}
