from __future__ import annotations
from pathlib import Path
from urllib.parse import urlencode

import base64
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from datetime import date
from .auth import ROLE_HOME, ROLE_LABEL, ROLE_THEME
from .database import Base, SessionLocal, engine, DATA_DIR
from .deps import AuthRedirect
from .models import Attendance, BalMandal, Branch, Child, StoredPhoto, User
from .routers import auth, branch_admin, dossier, sanchalak, spotlight, super_admin
from .seed import seed_if_empty
from .weeks import current_week_info, format_dt, gujarati_month, week_number_for

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

AVATAR_PLACEHOLDER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
  <defs>
    <linearGradient id="avatarBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#f8fafc"/>
      <stop offset="100%" stop-color="#e2e8f0"/>
    </linearGradient>
  </defs>
  <circle cx="50" cy="50" r="48" fill="url(#avatarBg)" stroke="#cbd5e1" stroke-width="2"/>
  <circle cx="50" cy="38" r="16" fill="#94a3b8"/>
  <path d="M 22 78 C 22 62, 35 56, 50 56 C 65 56, 78 62, 78 78 Z" fill="#94a3b8"/>
</svg>"""

app = FastAPI(title="Bal Mandal Attendance System")
app.add_middleware(SessionMiddleware, secret_key="bal-mandal-dev-secret-change-me")


@app.get("/static/uploads/{filename}")
def serve_upload(filename: str):
    """
    Serve uploaded face photos and scan snapshots with database persistence.
    If the file is missing from local disk (e.g. after cloud redeployment),
    it is dynamically restored from the database StoredPhoto table.
    If not found, returns a clean SVG avatar placeholder instead of a broken 404.
    """
    safe_name = Path(filename).name
    target = UPLOAD_DIR / safe_name
    if target.exists() and target.is_file() and target.stat().st_size > 0:
        return FileResponse(target, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})

    try:
        with SessionLocal() as db_session:
            sp = db_session.query(StoredPhoto).filter(StoredPhoto.filename == safe_name).first()
            if sp and sp.data_b64:
                img_data = base64.b64decode(sp.data_b64)
                target.write_bytes(img_data)
                return Response(content=img_data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
    except Exception as e:
        print(f"StoredPhoto retrieval warning: {e}")

    return Response(
        content=AVATAR_PLACEHOLDER_SVG,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


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
dossier.templates = templates

app.include_router(auth.router)
app.include_router(super_admin.router)
app.include_router(branch_admin.router)
app.include_router(sanchalak.router)
app.include_router(spotlight.router)
app.include_router(dossier.router)


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
    if engine.dialect.name == "sqlite":
        with engine.connect() as conn:
            try:
                cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(children)").fetchall()]
                new_cols = {
                    "mobile_number": "VARCHAR(20) DEFAULT ''",
                    "first_name": "VARCHAR(60) DEFAULT ''",
                    "father_name": "VARCHAR(60) DEFAULT ''",
                    "surname": "VARCHAR(60) DEFAULT ''",
                    "dob": "DATE",
                    "dob_str": "VARCHAR(12) DEFAULT ''",
                    "gender": "VARCHAR(10) DEFAULT 'Male'",
                    "standard": "VARCHAR(20) DEFAULT ''",
                    "address": "TEXT DEFAULT ''",
                    "uses_bus": "BOOLEAN DEFAULT 0",
                    "bus_route": "VARCHAR(100) DEFAULT ''",
                    "face_descriptor": "TEXT DEFAULT NULL",
                }
                for col_name, col_def in new_cols.items():
                    if cols and col_name not in cols:
                        conn.exec_driver_sql(f"ALTER TABLE children ADD COLUMN {col_name} {col_def}")
                conn.commit()
            except Exception as e:
                print("Migration warning:", e)
    db = SessionLocal()
    try:
        seed_if_empty(db)
        # Backfill legacy children if needed
        legacy = db.query(Child).filter((Child.first_name == "") | (Child.first_name.is_(None))).all()
        for c in legacy:
            if c.name:
                parts = c.name.strip().split()
                if len(parts) == 1:
                    c.first_name = parts[0]
                elif len(parts) == 2:
                    c.first_name = parts[0]
                    c.surname = parts[1]
                    c.father_name = c.guardian_name or ""
                elif len(parts) >= 3:
                    c.first_name = parts[0]
                    c.father_name = parts[1]
                    c.surname = " ".join(parts[2:])
            if not c.mobile_number:
                c.mobile_number = "9876543210"
            if not c.dob_str and c.age:
                birth_year = date.today().year - c.age
                c.dob_str = f"15/06/{birth_year}"
                c.dob = date(birth_year, 6, 15)
            if not c.standard and c.age:
                age_std_map = {
                    4: "Jr KG", 5: "Sr KG", 6: "1st Standard", 7: "2nd Standard",
                    8: "3rd Standard", 9: "4th Standard", 10: "5th Standard",
                    11: "6th Standard", 12: "7th Standard", 13: "8th Standard",
                    14: "9th Standard", 15: "10th Standard", 16: "11th Standard",
                    17: "12th Standard"
                }
                c.standard = age_std_map.get(c.age, "4th Standard")
            if not c.gender:
                c.gender = "Male"
        if legacy:
            db.commit()
    except Exception as e:
        print("Backfill warning:", e)
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
