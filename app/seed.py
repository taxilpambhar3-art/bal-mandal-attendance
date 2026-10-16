from __future__ import annotations
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from .auth import hash_password
from .models import Attendance, BalMandal, Branch, Child, User
from .weeks import week_number_for


def seed_if_empty(db: Session) -> None:
    if db.query(User).first():
        return

    maninagar = Branch(
        name="મણિનગર Branch",
        code="BR-001",
        city="અમદાવાદ",
        phone="079-25432100",
        address="મણિનગર, અમદાવાદ – 380008",
    )
    ellisbridge = Branch(
        name="એલિસબ્રિજ Branch",
        code="BR-025",
        city="અમદાવાદ",
        phone="079-26543210",
        address="એલિસબ્રિજ, અમદાવાદ – 380006",
    )
    db.add_all([maninagar, ellisbridge])
    db.flush()

    shaniwar = BalMandal(
        name="શનિવાર બાલ મંડળ",
        branch_id=maninagar.id,
        weekday="શનિવાર",
        meeting_time=time(10, 30),
    )
    mangalwar = BalMandal(
        name="મંગળવાર બાલ મંડળ",
        branch_id=maninagar.id,
        weekday="મંગળવાર",
        meeting_time=time(17, 0),
    )
    ravivar = BalMandal(
        name="રવિવાર બાલ મંડળ",
        branch_id=ellisbridge.id,
        weekday="રવિવાર",
        meeting_time=time(9, 0),
    )
    db.add_all([shaniwar, mangalwar, ravivar])
    db.flush()

    users = [
        User(
            username="superadmin",
            password_hash=hash_password("admin123"),
            full_name="રમેશ પટેલ",
            mobile="9876500001",
            role="super_admin",
        ),
        User(
            username="maninagar_admin",
            password_hash=hash_password("branch123"),
            full_name="કિરણ શાહ",
            mobile="9876543220",
            role="branch_admin",
            branch_id=maninagar.id,
        ),
        User(
            username="hetal_shani",
            password_hash=hash_password("scan123"),
            full_name="હેતલ પટેલ",
            mobile="9876566666",
            role="sanchalak",
            branch_id=maninagar.id,
            bal_mandal_id=shaniwar.id,
        ),
        User(
            username="kavita_mangal",
            password_hash=hash_password("scan123"),
            full_name="કવિતા રાવલ",
            mobile="9876566667",
            role="sanchalak",
            branch_id=maninagar.id,
            bal_mandal_id=mangalwar.id,
        ),
    ]
    db.add_all(users)

    kids = [
        ("CH-00123", "આર્ય પટેલ", 9, "જય પટેલ"),
        ("CH-00124", "ધ્રુવી શાહ", 8, "નીરવ શાહ"),
        ("CH-00125", "કૃષ્ણ મહેતા", 10, "અમિત મહેતા"),
        ("CH-00126", "પાર્થ જોષી", 7, "રાજેશ જોષી"),
        ("CH-00127", "રિદ્ધિ દેસાઈ", 9, "હિમેશ દેસાઈ"),
        ("CH-00128", "યશ પંડ્યા", 11, "કિરણ પંડ્યા"),
        ("CH-00129", "અન્યા પટેલ", 8, "મિલન પટેલ"),
        ("CH-00130", "વૈભવ શાહ", 10, "જીગ્નેશ શાહ"),
    ]
    child_objs = []
    for code, name, age, guardian in kids:
        c = Child(
            child_code=code,
            name=name,
            age=age,
            guardian_name=guardian,
            bal_mandal_id=shaniwar.id,
        )
        child_objs.append(c)
        db.add(c)
    db.flush()

    # Seed some attendance for current month (weeks 1–current)
    today = date.today()
    for week in range(1, week_number_for(today) + 1):
        # Use first Saturday-like date in that week band
        day = min((week - 1) * 7 + 3, today.day if week == week_number_for(today) else week * 7)
        day = max(1, min(day, today.day))
        att_date = date(today.year, today.month, day)
        for i, child in enumerate(child_objs):
            # Leave last child absent in current week for demo
            if week == week_number_for(today) and i == len(child_objs) - 1:
                continue
            db.add(
                Attendance(
                    child_id=child.id,
                    bal_mandal_id=shaniwar.id,
                    attendance_date=att_date,
                    year=att_date.year,
                    month=att_date.month,
                    week_number=week_number_for(att_date),
                    scanned_at=datetime.combine(att_date, time(10, 30)) + timedelta(minutes=i),
                    status="present",
                    marked_by=None,
                )
            )

    db.commit()
