from __future__ import annotations
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from .auth import hash_password
from .models import Attendance, BalMandal, Branch, Child, User
from .weeks import week_number_for


def seed_if_empty(db: Session) -> None:
    if db.query(User).first():
        return

    admin = User(
        username="superadmin",
        password_hash=hash_password("admin123"),
        plain_password="password",
        full_name="Super Admin",
        mobile="9876500001",
        role="super_admin",
    )
    db.add(admin)
    db.commit()

