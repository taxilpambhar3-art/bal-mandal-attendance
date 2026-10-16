from __future__ import annotations
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..auth import ROLE_HOME, verify_password
from ..database import get_db
from ..deps import current_user
from ..models import User

router = APIRouter(tags=["auth"])
templates: Jinja2Templates | None = None


@router.get("/login")
def login_page(request: Request, user: User | None = Depends(current_user)):
    if user:
        return RedirectResponse(ROLE_HOME[user.role], status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None},
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
            {"request": request, "error": "Invalid Username or Password"},
            status_code=400,
        )
    request.session["user_id"] = user.id
    request.session["role"] = user.role
    return RedirectResponse(ROLE_HOME[user.role], status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
