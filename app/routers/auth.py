from __future__ import annotations
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..auth import ROLE_HOME, ROLE_LABEL, verify_password
from ..database import get_db
from ..deps import current_user
from ..models import User

router = APIRouter(tags=["auth"])
templates: Jinja2Templates | None = None


def _demo_accounts(db: Session) -> list[dict]:
    """Build Quick Demo Login cards from live active users (not hardcoded ghosts)."""
    role_meta = {
        "super_admin": {
            "label": "Super Admin",
            "subtitle": "All Branches, Analytics & Reports",
            "icon_box": "bg-primary-subtle text-primary",
            "icon": "bi-shield-check",
            "card_id": "cardSuperadmin",
        },
        "branch_admin": {
            "label": "Branch Admin",
            "subtitle": "Branch Management",
            "icon_box": "bg-success-subtle text-success",
            "icon": "bi-building",
            "card_id": "cardBranchadmin",
        },
        "sanchalak": {
            "label": "Sanchalak",
            "subtitle": "AI Face Scanner & Live Attendance",
            "icon_box": "bg-warning-subtle text-warning",
            "icon": "bi-camera-video",
            "card_id": "cardSanchalak",
        },
    }
    demos: list[dict] = []
    for role, meta in role_meta.items():
        user = (
            db.query(User)
            .filter(User.role == role, User.is_active.is_(True))
            .order_by(User.id.asc())
            .first()
        )
        if not user:
            continue
        password = (user.plain_password or "").strip()
        if not password:
            continue
        subtitle = meta["subtitle"]
        if role == "branch_admin" and user.branch is not None:
            subtitle = f"{user.branch.name} Branch Management"
        elif role == "sanchalak" and user.bal_mandal is not None:
            subtitle = f"{user.bal_mandal.name} · Face Scanner"
        demos.append(
            {
                "username": user.username,
                "password": password,
                "label": meta["label"],
                "subtitle": subtitle,
                "icon_box": meta["icon_box"],
                "icon": meta["icon"],
                "card_id": meta["card_id"],
                "display_name": user.full_name or ROLE_LABEL.get(role, meta["label"]),
            }
        )
    return demos


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)):
    if user:
        return RedirectResponse(ROLE_HOME[user.role], status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None, "demo_accounts": _demo_accounts(db)},
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username.strip()).first()
    if not user or not verify_password(password, user.password_hash) or not user.is_active:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid Username or Password",
                "demo_accounts": _demo_accounts(db),
            },
            status_code=400,
        )
    request.session["user_id"] = user.id
    request.session["role"] = user.role
    return RedirectResponse(ROLE_HOME[user.role], status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
