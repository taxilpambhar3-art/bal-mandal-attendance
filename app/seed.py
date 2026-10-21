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

    from .child_utils import parse_dob_strict

    kids = [
        ("CH-00123", "Aryan", "Jayeshbhai", "Patel", "15/05/2015", "Male", "4th Standard", "A-201 Shivalik Heights, Maninagar", "9876543210", True, "Route #1 - Maninagar Cross Road"),
        ("CH-00124", "Dhruvi", "Niravbhai", "Shah", "22/08/2016", "Female", "3rd Standard", "B-12 Radhe Society, Khokhra", "9898123456", False, ""),
        ("CH-00125", "Krishna", "Amitbhai", "Mehta", "10/01/2014", "Female", "5th Standard", "45 Swaminarayan Park, Ghodasar", "9825011223", True, "Route #2 - Ghodasar Canal"),
        ("CH-00126", "Parth", "Rajeshbhai", "Joshi", "05/11/2017", "Male", "2nd Standard", "12 Akshar Flats, Isanpur", "9909033445", False, ""),
        ("CH-00127", "Riddhi", "Himeshbhai", "Desai", "18/03/2015", "Female", "4th Standard", "C-402 Nilkanth Residency, Maninagar", "9727055667", True, "Route #1 - Maninagar Cross Road"),
        ("CH-00128", "Yash", "Kiranbhai", "Pandya", "30/09/2013", "Male", "6th Standard", "78 Yogeshwar Nagar, Vatva", "9824077889", False, ""),
        ("CH-00129", "Anya", "Jayeshbhai", "Patel", "12/12/2016", "Female", "3rd Standard", "A-201 Shivalik Heights, Maninagar", "9876543210", True, "Route #1 - Maninagar Cross Road"),  # Sibling
        ("CH-00130", "Vaibhav", "Niravbhai", "Shah", "14/04/2014", "Male", "5th Standard", "B-12 Radhe Society, Khokhra", "9898123456", False, ""),  # Sibling
    ]
    child_objs = []
    for code, fn, fath, sn, dob_str, gender, std, addr, mobile, uses_bus, bus_route in kids:
        dob_dt, dob_clean, age = parse_dob_strict(dob_str)
        c = Child(
            child_code=code,
            name=f"{fn} {fath} {sn}".strip(),
            first_name=fn,
            father_name=fath,
            surname=sn,
            dob=dob_dt,
            dob_str=dob_clean or dob_str,
            age=age,
            gender=gender,
            standard=std,
            address=addr,
            guardian_name=fath,
            mobile_number=mobile,
            uses_bus=uses_bus,
            bus_route=bus_route,
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
