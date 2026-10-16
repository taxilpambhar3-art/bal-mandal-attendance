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
        name="Maninagar Branch",
        code="BR-001",
        city="Ahmedabad",
        phone="079-25432100",
        address="Maninagar, Ahmedabad – 380008",
    )
    ellisbridge = Branch(
        name="Ellisbridge Branch",
        code="BR-025",
        city="Ahmedabad",
        phone="079-26543210",
        address="Ellisbridge, Ahmedabad – 380006",
    )
    db.add_all([maninagar, ellisbridge])
    db.flush()

    shaniwar = BalMandal(
        name="Saturday Bal Mandal",
        branch_id=maninagar.id,
        weekday="Saturday",
        meeting_time=time(10, 30),
    )
    mangalwar = BalMandal(
        name="Tuesday Bal Mandal",
        branch_id=maninagar.id,
        weekday="Tuesday",
        meeting_time=time(17, 0),
    )
    ravivar = BalMandal(
        name="Sunday Bal Mandal",
        branch_id=ellisbridge.id,
        weekday="Sunday",
        meeting_time=time(9, 0),
    )
    db.add_all([shaniwar, mangalwar, ravivar])
    db.flush()

    users = [
        User(
            username="superadmin",
            password_hash=hash_password("admin123"),
            full_name="Ramesh Patel",
            mobile="9876500001",
            role="super_admin",
        ),
        User(
            username="maninagar_admin",
            password_hash=hash_password("branch123"),
            full_name="Kiran Shah",
            mobile="9876543220",
            role="branch_admin",
            branch_id=maninagar.id,
        ),
        User(
            username="hetal_shani",
            password_hash=hash_password("scan123"),
            full_name="Hetal Patel",
            mobile="9876566666",
            role="sanchalak",
            branch_id=maninagar.id,
            bal_mandal_id=shaniwar.id,
        ),
        User(
            username="kavita_mangal",
            password_hash=hash_password("scan123"),
            full_name="Kavita Raval",
            mobile="9876566667",
            role="sanchalak",
            branch_id=maninagar.id,
            bal_mandal_id=mangalwar.id,
        ),
    ]
    db.add_all(users)

    kids = [
        ("CH-00123", "Aryan Patel", 9, "Jay Patel"),
        ("CH-00124", "Dhruvi Shah", 8, "Nirav Shah"),
        ("CH-00125", "Krishna Mehta", 10, "Amit Mehta"),
        ("CH-00126", "Parth Joshi", 7, "Rajesh Joshi"),
        ("CH-00127", "Riddhi Desai", 9, "Himesh Desai"),
        ("CH-00128", "Yash Pandya", 11, "Kiran Pandya"),
        ("CH-00129", "Anya Patel", 8, "Milan Patel"),
        ("CH-00130", "Vaibhav Shah", 10, "Jignesh Shah"),
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
