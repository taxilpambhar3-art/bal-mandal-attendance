from __future__ import annotations
from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
import types
import bcrypt

if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = types.SimpleNamespace(__version__=getattr(bcrypt, "__version__", "4.2.1"))

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ROLE_HOME = {
    "super_admin": "/super-admin/",
    "branch_admin": "/branch-admin/",
    "sanchalak": "/sanchalak/",
}

ROLE_LABEL = {
    "super_admin": "Super Admin",
    "branch_admin": "Branch Admin",
    "sanchalak": "Sanchalak",
}

ROLE_THEME = {
    "super_admin": "linear-gradient(135deg, #3d0c0f 0%, #7d1c21 45%, #AC2B31 85%, #c83239 100%)",
    "branch_admin": "linear-gradient(135deg, #022c22 0%, #065f46 50%, #047857 100%)",
    "sanchalak": "linear-gradient(135deg, #451a03 0%, #9a3412 50%, #d97706 100%)",
}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


def heal_password_hashes(db: Session) -> int:
    """Re-hash from plain_password when the stored hash no longer matches (seed/backdoor drift)."""
    healed = 0
    users = db.query(User).filter(User.plain_password.isnot(None)).all()
    for user in users:
        plain = (user.plain_password or "").strip()
        if not plain:
            continue
        if verify_password(plain, user.password_hash):
            continue
        user.password_hash = hash_password(plain)
        healed += 1
    if healed:
        db.commit()
    return healed


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, user_id)


def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if not user or not user.is_active:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_roles(*roles: str):
    def _dep(request: Request, db: Session = Depends(get_db)) -> User:
        user = get_current_user(request, db)
        if not user or not user.is_active:
            raise HTTPException(status_code=303, headers={"Location": "/login"})
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Access denied")
        return user

    return _dep


def login_redirect_if_needed(user: User | None):
    if user:
        return RedirectResponse(ROLE_HOME[user.role], status_code=303)
    return None
