from __future__ import annotations
from pathlib import Path
from urllib.parse import urlencode

import base64
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from datetime import date
from .auth import ROLE_HOME, ROLE_LABEL, ROLE_THEME, heal_password_hashes
from .database import Base, SessionLocal, engine, DATA_DIR
from .deps import AuthRedirect
from .models import Attendance, BalMandal, Branch, Child, Event, StoredPhoto, User
from .routers import auth, branch_admin, dossier, notifications, sanchalak, spotlight, super_admin
from .seed import seed_if_empty
from .weeks import current_week_info, format_dt, gujarati_month, ist_today, week_number_for

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
app.include_router(notifications.router)


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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    if isinstance(exc, (StarletteHTTPException, HTTPException)):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return HTMLResponse(
        content=f"<h3>Internal Server Error</h3><pre>{traceback.format_exc()}</pre>",
        status_code=500
    )


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
                    "position": "VARCHAR(30) DEFAULT 'Student'",
                    "standard": "VARCHAR(20) DEFAULT ''",
                    "address": "TEXT DEFAULT ''",
                    "uses_bus": "BOOLEAN DEFAULT 0",
                    "bus_route": "VARCHAR(100) DEFAULT ''",
                    "face_descriptor": "TEXT DEFAULT NULL",
                }
                for col_name, col_def in new_cols.items():
                    if cols and col_name not in cols:
                        conn.exec_driver_sql(f"ALTER TABLE children ADD COLUMN {col_name} {col_def}")

                # events table columns migration
                try:
                    e_cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(events)").fetchall()]
                    e_new_cols = {
                        "is_completed": "BOOLEAN DEFAULT 0",
                        "completed_at": "DATETIME DEFAULT NULL",
                        "completed_by_id": "INTEGER DEFAULT NULL",
                        "completed_notes": "TEXT DEFAULT ''",
                        "attendance_start_time": "VARCHAR(30) DEFAULT ''",
                        "attendance_end_time": "VARCHAR(30) DEFAULT ''",
                    }
                    for c_name, c_def in e_new_cols.items():
                        if e_cols and c_name not in e_cols:
                            conn.exec_driver_sql(f"ALTER TABLE events ADD COLUMN {c_name} {c_def}")
                except Exception as e:
                    print("Events migration warning:", e)

                # attendance table columns migration
                try:
                    a_cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(attendance)").fetchall()]
                    if a_cols and "event_id" not in a_cols:
                        conn.exec_driver_sql("ALTER TABLE attendance ADD COLUMN event_id INTEGER DEFAULT NULL")
                except Exception as e:
                    print("Attendance migration warning:", e)

                # notifications table migration
                try:
                    conn.exec_driver_sql("""
                    CREATE TABLE IF NOT EXISTS notifications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title VARCHAR(200) NOT NULL,
                        message TEXT DEFAULT '',
                        notification_type VARCHAR(50) DEFAULT 'event_created',
                        event_id INTEGER DEFAULT NULL,
                        branch_id INTEGER DEFAULT NULL,
                        bal_mandal_id INTEGER DEFAULT NULL,
                        target_role VARCHAR(30) DEFAULT 'all',
                        link_url VARCHAR(255) DEFAULT '',
                        created_by_id INTEGER DEFAULT NULL,
                        created_at DATETIME,
                        is_active BOOLEAN DEFAULT 1
                    )
                    """)
                    conn.exec_driver_sql("""
                    CREATE TABLE IF NOT EXISTS user_notification_reads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        notification_id INTEGER NOT NULL,
                        read_at DATETIME
                    )
                    """)
                except Exception as e:
                    print("Notifications sqlite migration warning:", e)

                conn.commit()
            except Exception as e:
                print("Migration warning:", e)
    elif engine.dialect.name == "postgresql":
        with engine.connect() as conn:
            pg_stmts = [
                "ALTER TABLE children ADD COLUMN IF NOT EXISTS mobile_number VARCHAR(20) DEFAULT ''",
                "ALTER TABLE children ADD COLUMN IF NOT EXISTS first_name VARCHAR(60) DEFAULT ''",
                "ALTER TABLE children ADD COLUMN IF NOT EXISTS father_name VARCHAR(60) DEFAULT ''",
                "ALTER TABLE children ADD COLUMN IF NOT EXISTS surname VARCHAR(60) DEFAULT ''",
                "ALTER TABLE children ADD COLUMN IF NOT EXISTS dob DATE",
                "ALTER TABLE children ADD COLUMN IF NOT EXISTS dob_str VARCHAR(12) DEFAULT ''",
                "ALTER TABLE children ADD COLUMN IF NOT EXISTS gender VARCHAR(10) DEFAULT 'Male'",
                "ALTER TABLE children ADD COLUMN IF NOT EXISTS position VARCHAR(30) DEFAULT 'Student'",
                "ALTER TABLE children ADD COLUMN IF NOT EXISTS standard VARCHAR(20) DEFAULT ''",
                "ALTER TABLE children ADD COLUMN IF NOT EXISTS address TEXT DEFAULT ''",
                "ALTER TABLE children ADD COLUMN IF NOT EXISTS uses_bus BOOLEAN DEFAULT FALSE",
                "ALTER TABLE children ADD COLUMN IF NOT EXISTS bus_route VARCHAR(100) DEFAULT ''",
                "ALTER TABLE children ADD COLUMN IF NOT EXISTS face_descriptor TEXT DEFAULT NULL",
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS is_completed BOOLEAN DEFAULT FALSE",
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL",
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS completed_by_id INTEGER DEFAULT NULL",
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS completed_notes TEXT DEFAULT ''",
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS attendance_start_time VARCHAR(30) DEFAULT ''",
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS attendance_end_time VARCHAR(30) DEFAULT ''",
                "ALTER TABLE attendance ADD COLUMN IF NOT EXISTS event_id INTEGER DEFAULT NULL",
                "ALTER TABLE attendance DROP CONSTRAINT IF EXISTS uq_child_date",
                """CREATE TABLE IF NOT EXISTS notifications (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR(200) NOT NULL,
                    message TEXT DEFAULT '',
                    notification_type VARCHAR(50) DEFAULT 'event_created',
                    event_id INTEGER DEFAULT NULL,
                    branch_id INTEGER DEFAULT NULL,
                    bal_mandal_id INTEGER DEFAULT NULL,
                    target_role VARCHAR(30) DEFAULT 'all',
                    link_url VARCHAR(255) DEFAULT '',
                    created_by_id INTEGER DEFAULT NULL,
                    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )""",
                """CREATE TABLE IF NOT EXISTS user_notification_reads (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    notification_id INTEGER NOT NULL,
                    read_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )""",
            ]
            for stmt in pg_stmts:
                try:
                    conn.exec_driver_sql(stmt)
                    conn.commit()
                except Exception as e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    print("Postgres migration warning:", stmt, e)
    db = SessionLocal()
    try:
        seed_if_empty(db)
        try:
            healed = heal_password_hashes(db)
            if healed:
                print(f"Healed {healed} password hash(es) from plain_password")
        except Exception as e:
            print("Password heal warning:", e)
        # Backfill legacy children if needed
        for c in db.query(Child).filter((Child.position.is_(None)) | (Child.position == "")).all():
            c.position = "Student"
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
                birth_year = ist_today().year - c.age
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


@app.get("/admin")
@app.get("/admin-panel")
def admin_redirect(request: Request):
    user_id = request.session.get("user_id")
    role = request.session.get("role")
    if user_id:
        if role == "super_admin":
            return RedirectResponse("/super-admin/users", status_code=303)
        elif role == "branch_admin":
            return RedirectResponse("/branch-admin/", status_code=303)
        elif role == "sanchalak":
            return RedirectResponse("/sanchalak/", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/health")
def health():
    info = current_week_info()
    return {"ok": True, "week": info["week_label"], "month": info["month_name"]}

@app.get("/manifest.json")
def manifest():
    manifest_file = BASE_DIR / "static" / "manifest.json"
    return FileResponse(manifest_file, media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    sw_file = BASE_DIR / "static" / "sw.js"
    return FileResponse(
        sw_file,
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )
