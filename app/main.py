from __future__ import annotations
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from datetime import date
from .auth import ROLE_HOME, ROLE_LABEL, ROLE_THEME
from .database import Base, SessionLocal, engine, DATA_DIR
from .deps import AuthRedirect
from .models import Attendance, BalMandal, Branch, Child, User
from .routers import auth, branch_admin, dossier, sanchalak, spotlight, super_admin
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
