from __future__ import annotations
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..auth import hash_password
from ..database import get_db, UPLOAD_DIR
from ..deps import role_required, safe_int
from ..models import Attendance, BalMandal, Branch, Child, User
from ..weeks import current_week_info, gujarati_month
from ..child_utils import STANDARDS, promote_standard

router = APIRouter(prefix="/super-admin", tags=["super-admin"])
templates: Jinja2Templates | None = None

CITIES = ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Bhavnagar"]


def _ctx(request: Request, user: User, **extra):
    return {
        "request": request,
        "user": user,
        "active": extra.pop("active", "dashboard"),
        "week": current_week_info(),
        **extra,
    }


@router.get("/")
@router.get("/dashboard")
def dashboard(
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
):
    branches = db.query(Branch).order_by(Branch.name).all()
    total_branches = len(branches)
    total_bm = db.query(BalMandal).count()
    total_children = db.query(Child).filter(Child.is_active.is_(True)).count()
    total_admins = db.query(User).filter(User.role == "branch_admin").count()
    total_sanchalaks = db.query(User).filter(User.role == "sanchalak").count()

    week = current_week_info()
    today_present = (
        db.query(func.count(Attendance.id))
        .filter(Attendance.attendance_date == week["date"])
        .scalar()
        or 0
    )
    recent_scans = (
        db.query(Attendance)
        .options(
            joinedload(Attendance.child),
            joinedload(Attendance.bal_mandal).joinedload(BalMandal.branch),
        )
        .order_by(Attendance.scanned_at.desc())
        .limit(10)
        .all()
    )
    present = (
        db.query(func.count(Attendance.id))
        .filter(
            Attendance.year == week["year"],
            Attendance.month == week["month"],
            Attendance.week_number == week["week_number"],
            Attendance.status == "present",
        )
        .scalar()
        or 0
    )
    rate = round((present / total_children) * 100, 1) if total_children else 0

    branch_rows = []
    for b in branches:
        admin = (
            db.query(User)
            .filter(User.branch_id == b.id, User.role == "branch_admin")
            .first()
        )
        bm_ids = [m.id for m in b.bal_mandals]
        kids = db.query(Child).filter(Child.bal_mandal_id.in_(bm_ids), Child.is_active.is_(True)).count() if bm_ids else 0
        present_b = (
            db.query(func.count(Attendance.id))
            .filter(
                Attendance.bal_mandal_id.in_(bm_ids),
                Attendance.year == week["year"],
                Attendance.month == week["month"],
                Attendance.week_number == week["week_number"],
            )
            .scalar()
            if bm_ids
            else 0
        ) or 0

        mandals_detail = []
        for m in b.bal_mandals:
            m_kids = db.query(Child).filter(Child.bal_mandal_id == m.id, Child.is_active.is_(True)).count()
            m_pres = (
                db.query(func.count(Attendance.id))
                .filter(
                    Attendance.bal_mandal_id == m.id,
                    Attendance.year == week["year"],
                    Attendance.month == week["month"],
                    Attendance.week_number == week["week_number"],
                )
                .scalar()
                or 0
            )
            sanch = (
                db.query(User)
                .filter(User.bal_mandal_id == m.id, User.role == "sanchalak")
                .first()
            )
            mandals_detail.append({
                "id": m.id,
                "name": m.name,
                "weekday": m.weekday,
                "meeting_time": m.meeting_time,
                "sanchalak_name": sanch.full_name if sanch else "—",
                "sanchalak_mobile": sanch.mobile if sanch else None,
                "children_count": m_kids,
                "present_count": m_pres,
                "rate": min(round((m_pres / m_kids) * 100, 1), 100.0) if m_kids else 0,
            })

        branch_rows.append(
            {
                "branch": b,
                "admin": admin,
                "mandals": len(bm_ids),
                "mandals_detail": mandals_detail,
                "children": kids,
                "present": present_b,
                "absent": max(kids - present_b, 0),
                "rate": min(round((present_b / kids) * 100, 1), 100.0) if kids else 0,
            }
        )
    branch_rows.sort(key=lambda r: r["rate"], reverse=True)

    week_stats = []
    for w in range(1, 6):
        p = (
            db.query(func.count(Attendance.id))
            .filter(
                Attendance.year == week["year"],
                Attendance.month == week["month"],
                Attendance.week_number == w,
            )
            .scalar()
            or 0
        )
        week_stats.append({"week": w, "present": p, "rate": round((p / total_children) * 100) if total_children else 0})

    return templates.TemplateResponse(
        "super_admin/dashboard.html",
        _ctx(
            request,
            user,
            active="dashboard",
            total_branches=total_branches,
            total_bm=total_bm,
            total_children=total_children,
            total_admins=total_admins,
            total_sanchalaks=total_sanchalaks,
            today_present=today_present,
            recent_scans=recent_scans,
            rate=rate,
            branch_rows=branch_rows,
            week_stats=week_stats,
        ),
    )


@router.get("/branches")
def branches_list(
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
):
    branches = db.query(Branch).options(joinedload(Branch.bal_mandals)).order_by(Branch.name).all()
    week = current_week_info()
    rows = []
    for b in branches:
        admin = (
            db.query(User)
            .filter(User.branch_id == b.id, User.role == "branch_admin")
            .first()
        ) or (
            db.query(User)
            .filter(User.branch_id == b.id)
            .first()
        )
        bm_ids = [m.id for m in b.bal_mandals]
        kids = (
            db.query(func.count(Child.id))
            .join(BalMandal)
            .filter(BalMandal.branch_id == b.id, Child.is_active.is_(True))
            .scalar()
            or 0
        )
        present_b = (
            db.query(func.count(Attendance.id))
            .filter(
                Attendance.bal_mandal_id.in_(bm_ids),
                Attendance.year == week["year"],
                Attendance.month == week["month"],
                Attendance.week_number == week["week_number"],
            )
            .scalar()
            if bm_ids
            else 0
        ) or 0
        mandals_detail = []
        for m in b.bal_mandals:
            m_kids = db.query(Child).filter(Child.bal_mandal_id == m.id, Child.is_active.is_(True)).count()
            sanch = (
                db.query(User)
                .filter(User.bal_mandal_id == m.id, User.role == "sanchalak")
                .first()
            )
            mandals_detail.append({
                "id": m.id,
                "name": m.name,
                "weekday": m.weekday,
                "sanchalak_name": sanch.full_name if sanch else "—",
                "children_count": m_kids,
            })
        rows.append({
            "branch": b,
            "admin": admin,
            "children": kids,
            "present": present_b,
            "rate": round((present_b / kids) * 100, 1) if kids else 0,
            "mandals_detail": mandals_detail,
        })
    return templates.TemplateResponse(
        "super_admin/branches.html",
        _ctx(request, user, active="branches", rows=rows),
    )


@router.get("/branches/{branch_id}/summary")
def branch_summary_view(
    branch_id: int,
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
):
    branch = db.get(Branch, branch_id)
    if not branch:
        return RedirectResponse("/super-admin/branches", status_code=303)

    admin = (
        db.query(User)
        .filter(User.branch_id == branch_id, User.role == "branch_admin")
        .first()
    ) or (
        db.query(User)
        .filter(User.branch_id == branch_id)
        .first()
    )
    week = current_week_info()
    bm_ids = [m.id for m in branch.bal_mandals]
    kids = db.query(Child).filter(Child.bal_mandal_id.in_(bm_ids), Child.is_active.is_(True)).count() if bm_ids else 0
    present_b = (
        db.query(func.count(Attendance.id))
        .filter(
            Attendance.bal_mandal_id.in_(bm_ids),
            Attendance.year == week["year"],
            Attendance.month == week["month"],
            Attendance.week_number == week["week_number"],
        )
        .scalar()
        if bm_ids
        else 0
    ) or 0
    rate = min(round((present_b / kids) * 100, 1), 100.0) if kids else 0

    mandals_detail = []
    for m in branch.bal_mandals:
        m_kids = db.query(Child).filter(Child.bal_mandal_id == m.id, Child.is_active.is_(True)).count()
        m_pres = (
            db.query(func.count(Attendance.id))
            .filter(
                Attendance.bal_mandal_id == m.id,
                Attendance.year == week["year"],
                Attendance.month == week["month"],
                Attendance.week_number == week["week_number"],
            )
            .scalar()
            or 0
        )
        sanch = (
            db.query(User)
            .filter(User.bal_mandal_id == m.id, User.role == "sanchalak")
            .first()
        )
        mandals_detail.append({
            "id": m.id,
            "name": m.name,
            "weekday": m.weekday,
            "meeting_time": m.meeting_time,
            "sanchalak_name": sanch.full_name if sanch else "—",
            "sanchalak_mobile": sanch.mobile if sanch else None,
            "children_count": m_kids,
            "present_count": m_pres,
            "absent_count": max(m_kids - m_pres, 0),
            "rate": min(round((m_pres / m_kids) * 100, 1), 100.0) if m_kids else 0,
        })

    # Weekly attendance trends for this branch
    week_stats = []
    for w in range(1, 6):
        p = (
            db.query(func.count(Attendance.id))
            .filter(
                Attendance.bal_mandal_id.in_(bm_ids),
                Attendance.year == week["year"],
                Attendance.month == week["month"],
                Attendance.week_number == w,
            )
            .scalar()
            if bm_ids
            else 0
        ) or 0
        week_stats.append({"week": w, "present": p, "rate": min(round((p / kids) * 100), 100) if kids else 0})

    return templates.TemplateResponse(
        "super_admin/branch_summary.html",
        _ctx(
            request,
            user,
            active="branches",
            branch=branch,
            admin=admin,
            mandals=mandals_detail,
            total_mandals=len(bm_ids),
            total_children=kids,
            present=present_b,
            absent=max(kids - present_b, 0),
            rate=rate,
            week_stats=week_stats,
        ),
    )


@router.get("/branches/add")
def branch_add_form(
    request: Request,
    user: User = Depends(role_required("super_admin")),
):
    return templates.TemplateResponse(
        "super_admin/branch_form.html",
        _ctx(request, user, active="branches", branch=None, admin=None, cities=CITIES),
    )


@router.post("/branches/add")
def branch_add(
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
    name: str = Form(...),
    code: str = Form(...),
    city: str = Form(...),
    phone: str = Form(""),
    address: str = Form(""),
    admin_name: str = Form(""),
    admin_mobile: str = Form(""),
    admin_username: str = Form(""),
    admin_role: str = Form("branch_admin"),
    admin_password: str = Form(""),
    status: str = Form("Active"),
):
    branch = Branch(
        name=name.strip(),
        code=code.strip(),
        city=city,
        phone=phone.strip() or None,
        address=address.strip() or None,
        is_active=status == "Active",
    )
    db.add(branch)
    db.flush()
    u_name = admin_username.strip()
    if not u_name and code.strip():
        clean_code = "".join(c for c in code.lower() if c.isalnum() or c == "_")
        u_name = f"admin_{clean_code}"

    if u_name:
        u_role = admin_role.strip() if admin_role.strip() in ["branch_admin", "sanchalak", "super_admin"] else "branch_admin"
        pwd = admin_password.strip() or "branch123"
        existing = db.query(User).filter(User.username == u_name).first()
        if existing:
            existing.branch_id = branch.id
            existing.role = u_role
            if admin_name.strip():
                existing.full_name = admin_name.strip()
            if admin_mobile.strip():
                existing.mobile = admin_mobile.strip()
            if admin_password.strip():
                existing.password_hash = hash_password(admin_password.strip())
                existing.plain_password = admin_password.strip()
        else:
            db.add(
                User(
                    username=u_name,
                    password_hash=hash_password(pwd),
                    plain_password=pwd,
                    full_name=admin_name.strip() or u_name,
                    mobile=admin_mobile.strip() or None,
                    role=u_role,
                    branch_id=branch.id,
                )
            )
    db.commit()
    return RedirectResponse("/super-admin/branches", status_code=303)


@router.get("/branches/{branch_id}/edit")
def branch_edit_form(
    branch_id: int,
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
):
    branch = db.get(Branch, branch_id)
    if not branch:
        return RedirectResponse("/super-admin/branches", status_code=303)
    admin = (
        db.query(User)
        .filter(User.branch_id == branch_id, User.role == "branch_admin")
        .first()
    ) or (
        db.query(User)
        .filter(User.branch_id == branch_id)
        .first()
    )
    return templates.TemplateResponse(
        "super_admin/branch_form.html",
        _ctx(request, user, active="branches", branch=branch, admin=admin, cities=CITIES),
    )


@router.post("/branches/{branch_id}/edit")
def branch_edit(
    branch_id: int,
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
    name: str = Form(...),
    code: str = Form(...),
    city: str = Form(...),
    phone: str = Form(""),
    address: str = Form(""),
    admin_name: str = Form(""),
    admin_mobile: str = Form(""),
    admin_username: str = Form(""),
    admin_role: str = Form("branch_admin"),
    admin_password: str = Form(""),
    status: str = Form("Active"),
):
    branch = db.get(Branch, branch_id)
    if not branch:
        return RedirectResponse("/super-admin/branches", status_code=303)
    branch.name = name.strip()
    branch.code = code.strip()
    branch.city = city
    branch.phone = phone.strip() or None
    branch.address = address.strip() or None
    branch.is_active = status == "Active"

    u_role = admin_role.strip() if admin_role.strip() in ["branch_admin", "sanchalak", "super_admin"] else "branch_admin"
    admin = (
        db.query(User)
        .filter(User.branch_id == branch_id, User.role == "branch_admin")
        .first()
    ) or (
        db.query(User)
        .filter(User.branch_id == branch_id)
        .first()
    )
    if admin:
        if admin_name.strip():
            admin.full_name = admin_name.strip()
        if admin_mobile.strip():
            admin.mobile = admin_mobile.strip()
        if admin_username.strip():
            admin.username = admin_username.strip()
        admin.role = u_role
        if admin_password.strip():
            admin.password_hash = hash_password(admin_password.strip())
            admin.plain_password = admin_password.strip()
    elif admin_username.strip():
        existing = db.query(User).filter(User.username == admin_username.strip()).first()
        if existing:
            existing.branch_id = branch.id
            existing.role = u_role
            if admin_name.strip():
                existing.full_name = admin_name.strip()
            if admin_mobile.strip():
                existing.mobile = admin_mobile.strip()
            if admin_password.strip():
                existing.password_hash = hash_password(admin_password.strip())
                existing.plain_password = admin_password.strip()
        else:
            pwd = admin_password.strip() or "branch123"
            db.add(
                User(
                    username=admin_username.strip(),
                    password_hash=hash_password(pwd),
                    plain_password=pwd,
                    full_name=admin_name.strip() or admin_username.strip(),
                    mobile=admin_mobile.strip() or None,
                    role=u_role,
                    branch_id=branch.id,
                )
            )
    db.commit()
    return RedirectResponse("/super-admin/branches", status_code=303)


@router.get("/reports")
def reports(
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
    year: str | None = None,
    month: str | None = None,
    week: str | None = None,
    branch_id: str | None = None,
    mandal_id: str | None = None,
):
    info = current_week_info()
    year_val = safe_int(year) or info["year"]
    month_val = safe_int(month) or info["month"]
    week_val = safe_int(week)
    b_id = safe_int(branch_id)
    m_id = safe_int(mandal_id)

    q = db.query(Attendance).filter(Attendance.year == year_val, Attendance.month == month_val)
    if week_val:
        q = q.filter(Attendance.week_number == week_val)
    if m_id:
        q = q.filter(Attendance.bal_mandal_id == m_id)
    elif b_id:
        q = q.filter(Attendance.bal_mandal.has(BalMandal.branch_id == b_id))

    child_q = db.query(Child).filter(Child.is_active.is_(True))
    if m_id:
        child_q = child_q.filter(Child.bal_mandal_id == m_id)
    elif b_id:
        child_q = child_q.join(BalMandal).filter(BalMandal.branch_id == b_id)
    total_children = child_q.count()

    present = q.count()
    absent = max(total_children - present, 0)
    rate = round((present / total_children) * 100, 1) if total_children else 0

    week_rows = []
    for w in range(1, 6):
        wq = db.query(func.count(Attendance.id)).filter(
            Attendance.year == year_val,
            Attendance.month == month_val,
            Attendance.week_number == w,
        )
        if m_id:
            wq = wq.filter(Attendance.bal_mandal_id == m_id)
        elif b_id:
            wq = wq.filter(Attendance.bal_mandal.has(BalMandal.branch_id == b_id))
        p = wq.scalar() or 0
        week_rows.append(
            {
                "week": w,
                "present": p,
                "absent": max(total_children - p, 0),
                "rate": round((p / total_children) * 100, 1) if total_children else 0,
            }
        )

    branches_query = db.query(Branch).order_by(Branch.name)
    if b_id:
        branches_query = branches_query.filter(Branch.id == b_id)
    branches_filtered = branches_query.all()

    drill = []
    for b in branches_filtered:
        for m in b.bal_mandals:
            if m_id and m.id != m_id:
                continue
            kids = db.query(Child).filter(Child.bal_mandal_id == m.id, Child.is_active.is_(True)).count()
            pq = db.query(func.count(Attendance.id)).filter(
                Attendance.bal_mandal_id == m.id,
                Attendance.year == year_val,
                Attendance.month == month_val,
            )
            if week_val:
                pq = pq.filter(Attendance.week_number == week_val)
            p = pq.scalar() or 0
            sanch = (
                db.query(User)
                .filter(User.bal_mandal_id == m.id, User.role == "sanchalak")
                .first()
            )
            drill.append(
                {
                    "branch_id": b.id,
                    "branch": b.name,
                    "branch_city": b.city,
                    "mandal": m.name,
                    "sanchalak": sanch.full_name if sanch else "—",
                    "children": kids,
                    "present": p,
                    "rate": round((p / kids) * 100, 1) if kids else 0,
                }
            )

    all_branches = db.query(Branch).order_by(Branch.name).all()
    mandals_dropdown = (
        db.query(BalMandal).filter(BalMandal.branch_id == b_id).order_by(BalMandal.name).all()
        if b_id
        else db.query(BalMandal).order_by(BalMandal.name).all()
    )

    return templates.TemplateResponse(
        "super_admin/reports.html",
        _ctx(
            request,
            user,
            active="reports",
            year=year_val,
            month=month_val,
            week_filter=week_val,
            month_label=f"{gujarati_month(month_val)} {year_val}",
            total_children=total_children,
            present=present,
            absent=absent,
            rate=rate,
            week_rows=week_rows,
            drill=drill,
            branches=all_branches,
            mandals=mandals_dropdown,
            selected_branch=b_id,
            selected_mandal=m_id,
        ),
    )


@router.get("/mandals")
def mandals_list(
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
    branch_id: str | None = None,
    mandal_id: str | None = None,
    q: str | None = None,
):
    b_id = safe_int(branch_id)
    m_id = safe_int(mandal_id)
    query = db.query(BalMandal).options(joinedload(BalMandal.branch), joinedload(BalMandal.sanchalak))
    if b_id:
        query = query.filter(BalMandal.branch_id == b_id)
    if m_id:
        query = query.filter(BalMandal.id == m_id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(BalMandal.name.ilike(term))
    mandals = query.order_by(BalMandal.name).all()
    branches = db.query(Branch).order_by(Branch.name).all()
    all_mandals = (
        db.query(BalMandal).filter(BalMandal.branch_id == b_id).order_by(BalMandal.name).all()
        if b_id
        else db.query(BalMandal).order_by(BalMandal.name).all()
    )
    week = current_week_info()

    rows = []
    for m in mandals:
        kids = db.query(Child).filter(Child.bal_mandal_id == m.id, Child.is_active.is_(True)).count()
        pres = (
            db.query(func.count(Attendance.id))
            .filter(
                Attendance.bal_mandal_id == m.id,
                Attendance.year == week["year"],
                Attendance.month == week["month"],
                Attendance.week_number == week["week_number"],
            )
            .scalar()
            or 0
        )
        sanch = db.query(User).filter(User.bal_mandal_id == m.id, User.role == "sanchalak").first()
        rows.append({
            "mandal": m,
            "branch": m.branch,
            "sanchalak": sanch,
            "children": kids,
            "present": pres,
            "rate": min(round((pres / kids) * 100, 1), 100.0) if kids else 0,
        })
    return templates.TemplateResponse(
        "super_admin/mandals.html",
        _ctx(
            request,
            user,
            active="mandals",
            rows=rows,
            branches=branches,
            mandals=all_mandals,
            selected_branch=b_id,
            selected_mandal=m_id,
            search_query=q or "",
        ),
    )


@router.get("/users")
def users_list(
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
    role: str | None = None,
    branch_id: str | None = None,
    mandal_id: str | None = None,
):
    b_id = safe_int(branch_id)
    m_id = safe_int(mandal_id)
    role_val = role.strip() if role and role.strip() else None
    q = (
        db.query(User)
        .options(joinedload(User.branch), joinedload(User.bal_mandal))
        .filter(User.role.in_(["branch_admin", "sanchalak"]))
    )
    if role_val and role_val in ["branch_admin", "sanchalak"]:
        q = q.filter(User.role == role_val)
    if b_id:
        q = q.filter(User.branch_id == b_id)
    if m_id:
        q = q.filter(User.bal_mandal_id == m_id)
    users = q.order_by(User.role, User.full_name).all()
    branches = db.query(Branch).order_by(Branch.name).all()
    mandals = (
        db.query(BalMandal).filter(BalMandal.branch_id == b_id).order_by(BalMandal.name).all()
        if b_id
        else db.query(BalMandal).order_by(BalMandal.name).all()
    )
    return templates.TemplateResponse(
        "super_admin/users.html",
        _ctx(
            request,
            user,
            active="users",
            users=users,
            branches=branches,
            mandals=mandals,
            selected_role=role_val,
            selected_branch=b_id,
            selected_mandal=m_id,
        ),
    )


@router.get("/credentials")
def credentials_list(
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
    role: str | None = None,
    branch_id: str | None = None,
    mandal_id: str | None = None,
    q: str | None = None,
    msg: str | None = None,
):
    b_id = safe_int(branch_id)
    m_id = safe_int(mandal_id)
    role_val = role.strip() if role and role.strip() else None

    query = db.query(User).options(joinedload(User.branch), joinedload(User.bal_mandal))
    if role_val:
        query = query.filter(User.role == role_val)
    if b_id:
        query = query.filter(User.branch_id == b_id)
    if m_id:
        query = query.filter(User.bal_mandal_id == m_id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            (User.username.ilike(term)) | (User.full_name.ilike(term)) | (User.mobile.ilike(term))
        )

    all_users = query.all()
    role_order = {"super_admin": 0, "branch_admin": 1, "sanchalak": 2}
    all_users.sort(key=lambda u: (role_order.get(u.role, 99), (u.branch.name if u.branch else ""), u.full_name))

    branches = db.query(Branch).order_by(Branch.name).all()
    mandals = (
        db.query(BalMandal).filter(BalMandal.branch_id == b_id).order_by(BalMandal.name).all()
        if b_id
        else db.query(BalMandal).order_by(BalMandal.name).all()
    )

    total_count = db.query(User).count()
    super_admin_count = db.query(User).filter(User.role == "super_admin").count()
    branch_admin_count = db.query(User).filter(User.role == "branch_admin").count()
    sanchalak_count = db.query(User).filter(User.role == "sanchalak").count()

    return templates.TemplateResponse(
        "super_admin/credentials.html",
        _ctx(
            request,
            user,
            active="credentials",
            users=all_users,
            branches=branches,
            mandals=mandals,
            selected_role=role_val,
            selected_branch=b_id,
            selected_mandal=m_id,
            q=q or "",
            msg=msg,
            total_count=total_count,
            super_admin_count=super_admin_count,
            branch_admin_count=branch_admin_count,
            sanchalak_count=sanchalak_count,
        ),
    )


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
    new_password: str = Form(...),
):
    target_user = db.get(User, user_id)
    if not target_user:
        return RedirectResponse("/super-admin/credentials?msg=error_not_found", status_code=303)
    pwd = new_password.strip()
    if pwd:
        target_user.password_hash = hash_password(pwd)
        target_user.plain_password = pwd
        db.commit()
    return RedirectResponse(f"/super-admin/credentials?msg=pwd_updated", status_code=303)


@router.get("/children")
def children_list(
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
    branch_id: str | None = None,
    mandal_id: str | None = None,
    q: str | None = None,
):
    b_id = safe_int(branch_id)
    m_id = safe_int(mandal_id)
    query = (
        db.query(Child)
        .join(BalMandal)
        .join(Branch)
        .options(joinedload(Child.bal_mandal).joinedload(BalMandal.branch))
        .filter(Child.is_active.is_(True))
    )
    if b_id:
        query = query.filter(BalMandal.branch_id == b_id)
    if m_id:
        query = query.filter(Child.bal_mandal_id == m_id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter((Child.name.ilike(term)) | (Child.child_code.ilike(term)))
    children = query.order_by(Child.name).all()

    branches = db.query(Branch).order_by(Branch.name).all()
    mandals = (
        db.query(BalMandal).filter(BalMandal.branch_id == b_id).order_by(BalMandal.name).all()
        if b_id
        else db.query(BalMandal).order_by(BalMandal.name).all()
    )
    week = current_week_info()

    rows = []
    for c in children:
        pres_count = (
            db.query(func.count(Attendance.id))
            .filter(
                Attendance.child_id == c.id,
                Attendance.year == week["year"],
                Attendance.month == week["month"],
            )
            .scalar()
            or 0
        )
        rows.append({
            "child": c,
            "mandal": c.bal_mandal,
            "branch": c.bal_mandal.branch if c.bal_mandal else None,
            "pres_count": pres_count,
            "rate": min(round((pres_count / max(week["week_number"], 1)) * 100), 100),
        })

    return templates.TemplateResponse(
        "super_admin/children.html",
        _ctx(
            request,
            user,
            active="children",
            rows=rows,
            branches=branches,
            mandals=mandals,
            selected_branch=b_id,
            selected_mandal=m_id,
            search_query=q or "",
        ),
    )


@router.post("/children/promote-standards")
def promote_all_children_standards(
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
):
    children = db.query(Child).filter(Child.is_active.is_(True)).all()
    count = 0
    today = date.today()
    for c in children:
        if c.standard:
            c.standard = promote_standard(c.standard)
            count += 1
        if c.dob:
            c.age = today.year - c.dob.year - ((today.month, today.day) < (c.dob.month, c.dob.day))
    db.commit()
    return RedirectResponse(f"/super-admin/children?promoted={count}", status_code=303)


@router.get("/attendance")
def attendance_scans(
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
    branch_id: str | None = None,
    mandal_id: str | None = None,
    scan_date: str | None = None,
):
    b_id = safe_int(branch_id)
    m_id = safe_int(mandal_id)
    query = (
        db.query(Attendance)
        .options(
            joinedload(Attendance.child),
            joinedload(Attendance.bal_mandal).joinedload(BalMandal.branch),
        )
    )
    if b_id:
        query = query.filter(Attendance.bal_mandal.has(BalMandal.branch_id == b_id))
    if m_id:
        query = query.filter(Attendance.bal_mandal_id == m_id)
    if scan_date and scan_date.strip():
        try:
            d = date.fromisoformat(scan_date.strip())
            query = query.filter(Attendance.attendance_date == d)
        except ValueError:
            pass

    scans = query.order_by(Attendance.scanned_at.desc()).limit(150).all()
    branches = db.query(Branch).order_by(Branch.name).all()
    mandals = (
        db.query(BalMandal).filter(BalMandal.branch_id == b_id).order_by(BalMandal.name).all()
        if b_id
        else db.query(BalMandal).order_by(BalMandal.name).all()
    )

    return templates.TemplateResponse(
        "super_admin/attendance.html",
        _ctx(
            request,
            user,
            active="attendance",
            scans=scans,
            branches=branches,
            mandals=mandals,
            selected_branch=b_id,
            selected_mandal=m_id,
            selected_date=scan_date or "",
        ),
    )


# --- DELETE ENDPOINTS FOR SUPER ADMIN ---

@router.post("/branches/{branch_id}/delete")
def branch_delete(
    branch_id: int,
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
):
    branch = db.get(Branch, branch_id)
    if branch:
        for m in branch.bal_mandals:
            db.query(Attendance).filter(Attendance.bal_mandal_id == m.id).delete()
            for c in db.query(Child).filter(Child.bal_mandal_id == m.id).all():
                if c.face_photo:
                    p = UPLOAD_DIR / c.face_photo
                    if p.exists() and p.is_file():
                        try:
                            p.unlink()
                        except Exception:
                            pass
                db.delete(c)
            db.query(User).filter(User.bal_mandal_id == m.id).update({"bal_mandal_id": None})
            db.delete(m)
        for u in db.query(User).filter(User.branch_id == branch.id).all():
            if u.role != "super_admin":
                db.delete(u)
            else:
                u.branch_id = None
        db.delete(branch)
        db.commit()
    return RedirectResponse("/super-admin/branches", status_code=303)


@router.post("/mandals/{mandal_id}/delete")
def mandal_delete(
    mandal_id: int,
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
):
    mandal = db.get(BalMandal, mandal_id)
    if mandal:
        db.query(Attendance).filter(Attendance.bal_mandal_id == mandal.id).delete()
        for c in db.query(Child).filter(Child.bal_mandal_id == mandal.id).all():
            if c.face_photo:
                p = UPLOAD_DIR / c.face_photo
                if p.exists() and p.is_file():
                    try:
                        p.unlink()
                    except Exception:
                        pass
            db.delete(c)
        db.query(User).filter(User.bal_mandal_id == mandal.id).update({"bal_mandal_id": None})
        db.delete(mandal)
        db.commit()
    return RedirectResponse("/super-admin/mandals", status_code=303)


@router.post("/users/{user_id}/delete")
def user_delete(
    user_id: int,
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
):
    if user_id != user.id:
        target = db.get(User, user_id)
        if target:
            target.bal_mandal_id = None
            target.branch_id = None
            db.delete(target)
            db.commit()
    return RedirectResponse("/super-admin/users", status_code=303)


@router.post("/children/{child_id}/delete")
def child_delete(
    child_id: int,
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
):
    child = db.get(Child, child_id)
    if child:
        if child.face_photo:
            p = UPLOAD_DIR / child.face_photo
            if p.exists() and p.is_file():
                try:
                    p.unlink()
                except Exception:
                    pass
        db.query(Attendance).filter(Attendance.child_id == child.id).delete()
        db.delete(child)
        db.commit()
    return RedirectResponse("/super-admin/children", status_code=303)


@router.post("/attendance/{att_id}/delete")
def attendance_delete(
    att_id: int,
    request: Request,
    user: User = Depends(role_required("super_admin")),
    db: Session = Depends(get_db),
):
    att = db.get(Attendance, att_id)
    if att:
        if att.scan_photo:
            p = UPLOAD_DIR / att.scan_photo
            if p.exists() and p.is_file():
                try:
                    p.unlink()
                except Exception:
                    pass
        db.delete(att)
        db.commit()
    return RedirectResponse("/super-admin/attendance", status_code=303)


