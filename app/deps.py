from __future__ import annotations
from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .auth import ROLE_HOME, get_current_user
from .database import get_db
from .models import User


def safe_int(val: object) -> int | None:
    if val is None:
        return None
    val_str = str(val).strip()
    if not val_str:
        return None
    try:
        return int(val_str)
    except (ValueError, TypeError):
        return None


class AuthRedirect(Exception):
    def __init__(self, url: str):
        self.url = url


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    return get_current_user(request, db)


def login_required(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if not user:
        raise AuthRedirect("/login")
    return user


def role_required(*roles: str):
    def _inner(request: Request, db: Session = Depends(get_db)) -> User:
        user = get_current_user(request, db)
        if not user:
            raise AuthRedirect("/login")
        if user.role not in roles:
            raise AuthRedirect(ROLE_HOME.get(user.role, "/login"))
        return user

    return _inner
