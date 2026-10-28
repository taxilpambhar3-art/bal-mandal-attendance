from __future__ import annotations
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import login_required
from ..models import Attendance, BalMandal, Branch, Child, User
from ..weeks import current_week_info, format_dt, gujarati_month

router = APIRouter(tags=["dossier"])
templates: Jinja2Templates | None = None


def _check_scope(user: User, branch_id: Optional[int] = None, bal_mandal_id: Optional[int] = None) -> bool:
    """Validate whether the current user has permission to view this branch or mandal."""
    if user.role == "super_admin":
        return True
    if user.role == "branch_admin":
        if branch_id is not None and user.branch_id != branch_id:
            return False
        return True
    if user.role == "sanchalak":
        if bal_mandal_id is not None and user.bal_mandal_id != bal_mandal_id:
            return False
        return True
    return False


def _extract_sanchalak(mandal: Optional[BalMandal]) -> Optional[User]:
    """Safely retrieve the sanchalak User object regardless of whether relationship is a list or scalar."""
    if not mandal:
        return None
    s = mandal.sanchalak
    if isinstance(s, (list, tuple)) or (hasattr(s, "__iter__") and not isinstance(s, User)):
        return s[0] if len(s) > 0 else None
    return s


# ============================================================================
# 1. API: CHILD DOSSIER
# ============================================================================
@router.get("/api/dossier/child/{child_id}")
def api_child_dossier(
    child_id: int,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
):
    child = (
        db.query(Child)
        .options(
            joinedload(Child.bal_mandal).joinedload(BalMandal.branch),
            joinedload(Child.bal_mandal).joinedload(BalMandal.sanchalak),
        )
        .filter(Child.id == child_id)
        .first()
    )
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    mandal = child.bal_mandal
    branch = mandal.branch if mandal else None

    # Scope check
    if not _check_scope(user, branch_id=branch.id if branch else None, bal_mandal_id=mandal.id if mandal else None):
        raise HTTPException(status_code=403, detail="You do not have access to view this child's dossier")

    # Attendance statistics
    total_records = db.query(func.count(Attendance.id)).filter(Attendance.child_id == child.id).scalar() or 0
    present_count = (
        db.query(func.count(Attendance.id))
        .filter(Attendance.child_id == child.id, Attendance.status == "present")
        .scalar()
        or 0
    )

    # Calculate overall rate (against total sessions in mandal or records)
    mandal_sessions = (
        db.query(func.count(func.distinct(Attendance.attendance_date)))
        .filter(Attendance.bal_mandal_id == child.bal_mandal_id)
        .scalar()
        or 0
    )
    denom = max(mandal_sessions, total_records)
    rate = round((present_count / denom) * 100, 1) if denom > 0 else 0

    # Recent attendance records
    recent_att = (
        db.query(Attendance)
        .filter(Attendance.child_id == child.id)
        .order_by(Attendance.attendance_date.desc(), Attendance.scanned_at.desc())
        .limit(15)
        .all()
    )

    history = []
    for a in recent_att:
        history.append({
            "id": a.id,
            "date": a.attendance_date.strftime("%d %b %Y"),
            "date_iso": a.attendance_date.isoformat(),
            "weekday": a.attendance_date.strftime("%A"),
            "week_number": a.week_number,
            "month_name": gujarati_month(a.month),
            "year": a.year,
            "status": a.status,
            "scan_time": format_dt(a.scanned_at) if a.scanned_at else "—",
            "scan_photo": f"/static/uploads/{a.scan_photo}" if a.scan_photo else None,
        })

    # Edit URL based on role
    role_slug = "super-admin" if user.role == "super_admin" else ("branch-admin" if user.role == "branch_admin" else "sanchalak")
    edit_url = f"/{role_slug}/children/{child.id}/edit"

    sanchalak_user = _extract_sanchalak(mandal)

    # Clean clean phone for WhatsApp
    clean_mob = "".join(ch for ch in (child.mobile_number or "") if ch.isdigit())
    if clean_mob and len(clean_mob) == 10:
        clean_mob = "91" + clean_mob

    return JSONResponse({
        "ok": True,
        "type": "child",
        "data": {
            "id": child.id,
            "child_code": child.child_code,
            "name": child.name,
            "first_name": child.first_name or "",
            "father_name": child.father_name or "",
            "surname": child.surname or "",
            "gender": child.gender or "Male",
            "standard": child.standard or "Not specified",
            "dob": child.dob.strftime("%d/%m/%Y") if child.dob else (child.dob_str or "—"),
            "dob_str": child.dob_str or "",
            "age": child.age if child.age is not None else "—",
            "guardian_name": child.guardian_name or "—",
            "mobile_number": child.mobile_number or "—",
            "call_url": f"tel:{child.mobile_number}" if child.mobile_number else None,
            "whatsapp_url": f"https://wa.me/{clean_mob}?text=Jay%20Swaminarayan,%20regarding%20{child.name}%20attendance" if clean_mob else None,
            "address": child.address or "—",
            "uses_bus": child.uses_bus,
            "bus_route": child.bus_route or "Not Assigned",
            "face_photo": f"/static/uploads/{child.face_photo}" if child.face_photo else None,
            "face_registered": bool(child.face_photo),
            "is_active": child.is_active,
            "created_at": child.created_at.strftime("%d %b %Y") if child.created_at else "—",
            "bal_mandal": {
                "id": mandal.id if mandal else None,
                "name": mandal.name if mandal else "Unassigned",
                "weekday": mandal.weekday if mandal else "—",
                "meeting_time": mandal.meeting_time.strftime("%I:%M %p") if mandal and mandal.meeting_time else "—",
            } if mandal else None,
            "branch": {
                "id": branch.id if branch else None,
                "name": branch.name if branch else "Unassigned",
                "code": branch.code if branch else "—",
                "city": branch.city if branch else "—",
            } if branch else None,
            "sanchalak": {
                "name": sanchalak_user.full_name if sanchalak_user else "Not Assigned",
                "mobile": sanchalak_user.mobile if sanchalak_user else "—",
            } if sanchalak_user else None,
            "stats": {
                "total_records": total_records,
                "present_count": present_count,
                "attendance_rate": rate,
                "total_sessions": mandal_sessions,
            },
            "history": history,
            "edit_url": edit_url,
            "view_url": f"/dossier/child/{child.id}",
        },
    })


# ============================================================================
# 2. API: BAL MANDAL DOSSIER
# ============================================================================
@router.get("/api/dossier/mandal/{mandal_id}")
def api_mandal_dossier(
    mandal_id: int,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
):
    mandal = (
        db.query(BalMandal)
        .options(
            joinedload(BalMandal.branch),
            joinedload(BalMandal.sanchalak),
        )
        .filter(BalMandal.id == mandal_id)
        .first()
    )
    if not mandal:
        raise HTTPException(status_code=404, detail="Bal Mandal not found")

    branch = mandal.branch

    # Scope check
    if not _check_scope(user, branch_id=branch.id if branch else None, bal_mandal_id=mandal.id):
        raise HTTPException(status_code=403, detail="You do not have access to view this Bal Mandal's dossier")

    week = current_week_info()

    # Children list
    children = (
        db.query(Child)
        .filter(Child.bal_mandal_id == mandal.id)
        .order_by(Child.is_active.desc(), Child.name)
        .all()
    )

    total_children = len(children)
    active_children = sum(1 for c in children if c.is_active)
    archived_children = total_children - active_children
    bus_count = sum(1 for c in children if c.uses_bus)
    face_count = sum(1 for c in children if c.face_photo)

    # Present this week
    present_this_week = (
        db.query(func.count(Attendance.id))
        .filter(
            Attendance.bal_mandal_id == mandal.id,
            Attendance.year == week["year"],
            Attendance.month == week["month"],
            Attendance.week_number == week["week_number"],
        )
        .scalar()
        or 0
    )
    att_rate = round((present_this_week / active_children) * 100, 1) if active_children else 0

    # Individual child summary
    children_data = []
    for c in children:
        c_pres = (
            db.query(func.count(Attendance.id))
            .filter(Attendance.child_id == c.id, Attendance.status == "present")
            .scalar()
            or 0
        )
        children_data.append({
            "id": c.id,
            "child_code": c.child_code,
            "name": c.name,
            "standard": c.standard or "—",
            "age": c.age if c.age is not None else "—",
            "gender": c.gender or "Male",
            "guardian_name": c.guardian_name or "—",
            "mobile_number": c.mobile_number or "—",
            "face_photo": f"/static/uploads/{c.face_photo}" if c.face_photo else None,
            "uses_bus": c.uses_bus,
            "is_active": c.is_active,
            "present_count": c_pres,
        })

    # Recent Sessions
    recent_dates = (
        db.query(Attendance.attendance_date, Attendance.week_number, func.count(Attendance.id))
        .filter(Attendance.bal_mandal_id == mandal.id)
        .group_by(Attendance.attendance_date, Attendance.week_number)
        .order_by(Attendance.attendance_date.desc())
        .limit(8)
        .all()
    )
    recent_sessions = []
    for att_date, wk, cnt in recent_dates:
        s_rate = round((cnt / active_children) * 100, 1) if active_children else 0
        recent_sessions.append({
            "date": att_date.strftime("%d %b %Y"),
            "weekday": att_date.strftime("%A"),
            "week_number": wk,
            "present_count": cnt,
            "attendance_rate": s_rate,
        })

    sanch = _extract_sanchalak(mandal)
    clean_mob = "".join(ch for ch in (sanch.mobile or "") if ch.isdigit()) if sanch and sanch.mobile else None
    if clean_mob and len(clean_mob) == 10:
        clean_mob = "91" + clean_mob

    edit_url = None
    if user.role == "super_admin":
        edit_url = f"/super-admin/mandals"
    elif user.role == "branch_admin":
        edit_url = f"/branch-admin/bal-mandals/{mandal.id}/edit"

    return JSONResponse({
        "ok": True,
        "type": "mandal",
        "data": {
            "id": mandal.id,
            "name": mandal.name,
            "weekday": mandal.weekday,
            "meeting_time": mandal.meeting_time.strftime("%I:%M %p") if mandal.meeting_time else "—",
            "is_active": mandal.is_active,
            "created_at": mandal.created_at.strftime("%d %b %Y") if mandal.created_at else "—",
            "branch": {
                "id": branch.id if branch else None,
                "name": branch.name if branch else "Unassigned",
                "code": branch.code if branch else "—",
                "city": branch.city if branch else "—",
            } if branch else None,
            "sanchalak": {
                "id": sanch.id if sanch else None,
                "name": sanch.full_name if sanch else "Not Assigned",
                "username": sanch.username if sanch else "—",
                "mobile": sanch.mobile if sanch else "—",
                "call_url": f"tel:{sanch.mobile}" if sanch and sanch.mobile else None,
                "whatsapp_url": f"https://wa.me/{clean_mob}?text=Jay%20Swaminarayan" if clean_mob else None,
            } if sanch else None,
            "stats": {
                "total_children": total_children,
                "active_children": active_children,
                "archived_children": archived_children,
                "bus_count": bus_count,
                "face_registered": face_count,
                "present_this_week": present_this_week,
                "attendance_rate": att_rate,
            },
            "children": children_data,
            "recent_sessions": recent_sessions,
            "edit_url": edit_url,
            "view_url": f"/dossier/mandal/{mandal.id}",
        },
    })


# ============================================================================
# 3. API: BRANCH DOSSIER
# ============================================================================
@router.get("/api/dossier/branch/{branch_id}")
def api_branch_dossier(
    branch_id: int,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
):
    branch = (
        db.query(Branch)
        .options(
            joinedload(Branch.bal_mandals).joinedload(BalMandal.sanchalak),
            joinedload(Branch.admins),
        )
        .filter(Branch.id == branch_id)
        .first()
    )
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    # Scope check
    if not _check_scope(user, branch_id=branch.id):
        raise HTTPException(status_code=403, detail="You do not have access to view this Branch's dossier")

    week = current_week_info()
    bm_ids = [m.id for m in branch.bal_mandals]

    kids = (
        db.query(Child)
        .filter(Child.bal_mandal_id.in_(bm_ids), Child.is_active.is_(True))
        .count()
        if bm_ids
        else 0
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
    rate = min(round((present_b / kids) * 100, 1), 100.0) if kids else 0

    # Admins list
    admins_data = []
    for a in branch.admins:
        admins_data.append({
            "id": a.id,
            "name": a.full_name,
            "username": a.username,
            "role": a.role,
            "mobile": a.mobile or "—",
            "is_active": a.is_active,
        })

    # Mandals breakdown
    mandals_data = []
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
        m_rate = min(round((m_pres / m_kids) * 100, 1), 100.0) if m_kids else 0
        sanch = _extract_sanchalak(m)

        mandals_data.append({
            "id": m.id,
            "name": m.name,
            "weekday": m.weekday,
            "meeting_time": m.meeting_time.strftime("%I:%M %p") if m.meeting_time else "—",
            "is_active": m.is_active,
            "sanchalak_name": sanch.full_name if sanch else "Not Assigned",
            "sanchalak_mobile": sanch.mobile if sanch else "—",
            "children_count": m_kids,
            "present_count": m_pres,
            "attendance_rate": m_rate,
        })

    edit_url = f"/super-admin/branches/{branch.id}/edit" if user.role == "super_admin" else None

    return JSONResponse({
        "ok": True,
        "type": "branch",
        "data": {
            "id": branch.id,
            "name": branch.name,
            "code": branch.code,
            "city": branch.city,
            "phone": branch.phone or "—",
            "address": branch.address or "—",
            "is_active": branch.is_active,
            "created_at": branch.created_at.strftime("%d %b %Y") if branch.created_at else "—",
            "admins": admins_data,
            "stats": {
                "total_mandals": len(branch.bal_mandals),
                "total_children": kids,
                "present_this_week": present_b,
                "attendance_rate": rate,
            },
            "mandals": mandals_data,
            "edit_url": edit_url,
            "view_url": f"/dossier/branch/{branch.id}",
        },
    })


# ============================================================================
# 4. FULL-PAGE DOSSIER VIEWS (STANDALONE & PRINTABLE)
# ============================================================================
@router.get("/dossier/child/{child_id}")
def child_dossier_view(
    child_id: int,
    request: Request,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
):
    child = (
        db.query(Child)
        .options(
            joinedload(Child.bal_mandal).joinedload(BalMandal.branch),
            joinedload(Child.bal_mandal).joinedload(BalMandal.sanchalak),
        )
        .filter(Child.id == child_id)
        .first()
    )
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    mandal = child.bal_mandal
    branch = mandal.branch if mandal else None
    if not _check_scope(user, branch_id=branch.id if branch else None, bal_mandal_id=mandal.id if mandal else None):
        raise HTTPException(status_code=403, detail="You do not have permission to view this child's dossier")

    # Attendance records
    total_records = db.query(func.count(Attendance.id)).filter(Attendance.child_id == child.id).scalar() or 0
    present_count = (
        db.query(func.count(Attendance.id))
        .filter(Attendance.child_id == child.id, Attendance.status == "present")
        .scalar()
        or 0
    )
    mandal_sessions = (
        db.query(func.count(func.distinct(Attendance.attendance_date)))
        .filter(Attendance.bal_mandal_id == child.bal_mandal_id)
        .scalar()
        or 0
    )
    denom = max(mandal_sessions, total_records)
    rate = round((present_count / denom) * 100, 1) if denom > 0 else 0

    recent_att = (
        db.query(Attendance)
        .filter(Attendance.child_id == child.id)
        .order_by(Attendance.attendance_date.desc(), Attendance.scanned_at.desc())
        .limit(25)
        .all()
    )

    return templates.TemplateResponse(
        "dossier/child.html",
        {
            "request": request,
            "user": user,
            "child": child,
            "mandal": mandal,
            "branch": branch,
            "sanchalak": _extract_sanchalak(mandal),
            "stats": {
                "total_records": total_records,
                "present_count": present_count,
                "attendance_rate": rate,
                "total_sessions": mandal_sessions,
            },
            "history": recent_att,
            "week": current_week_info(),
            "active": "dossier",
        },
    )


@router.get("/dossier/mandal/{mandal_id}")
def mandal_dossier_view(
    mandal_id: int,
    request: Request,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
):
    mandal = (
        db.query(BalMandal)
        .options(
            joinedload(BalMandal.branch),
            joinedload(BalMandal.sanchalak),
            joinedload(BalMandal.children),
        )
        .filter(BalMandal.id == mandal_id)
        .first()
    )
    if not mandal:
        raise HTTPException(status_code=404, detail="Bal Mandal not found")

    branch = mandal.branch
    if not _check_scope(user, branch_id=branch.id if branch else None, bal_mandal_id=mandal.id):
        raise HTTPException(status_code=403, detail="You do not have permission to view this Bal Mandal's dossier")

    week = current_week_info()
    children = sorted(mandal.children, key=lambda c: (not c.is_active, c.name))
    total_children = len(children)
    active_children = sum(1 for c in children if c.is_active)
    present_this_week = (
        db.query(func.count(Attendance.id))
        .filter(
            Attendance.bal_mandal_id == mandal.id,
            Attendance.year == week["year"],
            Attendance.month == week["month"],
            Attendance.week_number == week["week_number"],
        )
        .scalar()
        or 0
    )
    att_rate = round((present_this_week / active_children) * 100, 1) if active_children else 0

    recent_sessions = (
        db.query(Attendance.attendance_date, Attendance.week_number, func.count(Attendance.id))
        .filter(Attendance.bal_mandal_id == mandal.id)
        .group_by(Attendance.attendance_date, Attendance.week_number)
        .order_by(Attendance.attendance_date.desc())
        .limit(10)
        .all()
    )

    return templates.TemplateResponse(
        "dossier/mandal.html",
        {
            "request": request,
            "user": user,
            "mandal": mandal,
            "branch": branch,
            "sanchalak": _extract_sanchalak(mandal),
            "children": children,
            "stats": {
                "total_children": total_children,
                "active_children": active_children,
                "archived_children": total_children - active_children,
                "bus_count": sum(1 for c in children if c.uses_bus),
                "face_registered": sum(1 for c in children if c.face_photo),
                "present_this_week": present_this_week,
                "attendance_rate": att_rate,
            },
            "recent_sessions": recent_sessions,
            "week": current_week_info(),
            "active": "dossier",
        },
    )


@router.get("/dossier/branch/{branch_id}")
def branch_dossier_view(
    branch_id: int,
    request: Request,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
):
    branch = (
        db.query(Branch)
        .options(
            joinedload(Branch.bal_mandals).joinedload(BalMandal.sanchalak),
            joinedload(Branch.admins),
        )
        .filter(Branch.id == branch_id)
        .first()
    )
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    if not _check_scope(user, branch_id=branch.id):
        raise HTTPException(status_code=403, detail="You do not have permission to view this Branch's dossier")

    week = current_week_info()
    bm_ids = [m.id for m in branch.bal_mandals]
    kids = (
        db.query(Child)
        .filter(Child.bal_mandal_id.in_(bm_ids), Child.is_active.is_(True))
        .count()
        if bm_ids
        else 0
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
    rate = min(round((present_b / kids) * 100, 1), 100.0) if kids else 0

    mandals_data = []
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
        mandals_data.append({
            "mandal": m,
            "children_count": m_kids,
            "present_count": m_pres,
            "rate": min(round((m_pres / m_kids) * 100, 1), 100.0) if m_kids else 0,
        })

    return templates.TemplateResponse(
        "dossier/branch.html",
        {
            "request": request,
            "user": user,
            "branch": branch,
            "mandals_data": mandals_data,
            "stats": {
                "total_mandals": len(branch.bal_mandals),
                "total_children": kids,
                "present_this_week": present_b,
                "attendance_rate": rate,
            },
            "week": current_week_info(),
            "active": "dossier",
        },
    )
