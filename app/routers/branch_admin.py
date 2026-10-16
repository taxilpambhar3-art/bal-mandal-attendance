from __future__ import annotations
import base64
import uuid
from datetime import date, datetime
from datetime import time as time_cls

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..auth import hash_password
from ..database import UPLOAD_DIR, get_db
from ..deps import role_required, safe_int
from ..face_matcher import compare_face_photos
from ..models import Attendance, BalMandal, Child, User
from ..weeks import current_week_info, gujarati_month

router = APIRouter(prefix="/branch-admin", tags=["branch-admin"])
templates: Jinja2Templates | None = None

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _ctx(request: Request, user: User, **extra):
    return {
        "request": request,
        "user": user,
        "branch": user.branch,
        "active": extra.pop("active", "dashboard"),
        "week": current_week_info(),
        **extra,
    }


def _save_data_url(data_url: str, prefix: str = "scan") -> str | None:
    if not data_url or "," not in data_url:
        return None
    try:
        header, b64 = data_url.split(",", 1)
        ext = "jpg" if "jpeg" in header or "jpg" in header else "png"
        name = f"{prefix}_{uuid.uuid4().hex[:12]}.{ext}"
        path = UPLOAD_DIR / name
        b64_clean = b64.strip()
        missing_padding = len(b64_clean) % 4
        if missing_padding:
            b64_clean += "=" * (4 - missing_padding)
        data = base64.b64decode(b64_clean)
        if not data:
            return None
        path.write_bytes(data)
        return name
    except Exception as e:
        print(f"Error saving data URL: {e}")
        return None


@router.get("/")
@router.get("/dashboard")
def dashboard(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
):
    mandals = db.query(BalMandal).filter(BalMandal.branch_id == user.branch_id).all()
    bm_ids = [m.id for m in mandals]
    total_children = (
        db.query(Child).filter(Child.bal_mandal_id.in_(bm_ids), Child.is_active.is_(True)).count()
        if bm_ids
        else 0
    )
    total_sanchalaks = (
        db.query(User).filter(User.branch_id == user.branch_id, User.role == "sanchalak").count()
    )
    week = current_week_info()
    present = (
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
    rate = round((present / total_children) * 100) if total_children else 0

    mandal_rows = []
    for m in mandals:
        kids = db.query(Child).filter(Child.bal_mandal_id == m.id, Child.is_active.is_(True)).count()
        p = (
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
        mandal_rows.append(
            {
                "mandal": m,
                "sanchalak": sanch,
                "children": kids,
                "present": p,
                "rate": round((p / kids) * 100, 1) if kids else 0,
            }
        )

    today_scans = (
        db.query(Attendance)
        .options(
            joinedload(Attendance.child),
            joinedload(Attendance.bal_mandal),
        )
        .filter(
            Attendance.bal_mandal_id.in_(bm_ids),
            Attendance.attendance_date == week["date"],
        )
        .order_by(Attendance.scanned_at.desc())
        .limit(10)
        .all()
        if bm_ids
        else []
    )

    return templates.TemplateResponse(
        "branch_admin/dashboard.html",
        _ctx(
            request,
            user,
            active="dashboard",
            total_mandals=len(mandals),
            total_sanchalaks=total_sanchalaks,
            total_children=total_children,
            present=present,
            rate=rate,
            mandal_rows=mandal_rows,
            today_scans=today_scans,
        ),
    )


@router.get("/bal-mandals")
def bal_mandals_list(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
):
    mandals = (
        db.query(BalMandal)
        .filter(BalMandal.branch_id == user.branch_id)
        .order_by(BalMandal.name)
        .all()
    )
    rows = []
    for m in mandals:
        sanch = (
            db.query(User)
            .filter(User.bal_mandal_id == m.id, User.role == "sanchalak")
            .first()
        )
        kids = db.query(Child).filter(Child.bal_mandal_id == m.id, Child.is_active.is_(True)).count()
        rows.append({"mandal": m, "sanchalak": sanch, "children": kids})
    return templates.TemplateResponse(
        "branch_admin/bal_mandals.html",
        _ctx(request, user, active="bal_mandals", rows=rows),
    )


@router.get("/bal-mandals/add")
def bal_mandal_add_form(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
):
    return templates.TemplateResponse(
        "branch_admin/bal_mandal_form.html",
        _ctx(request, user, active="bal_mandals", mandal=None, sanchalak=None, weekdays=WEEKDAYS),
    )


@router.post("/bal-mandals/add")
def bal_mandal_add(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
    name: str = Form(...),
    weekday: str = Form(...),
    meeting_time: str = Form(""),
    status: str = Form("Active"),
    sanchalak_name: str = Form(""),
    sanchalak_mobile: str = Form(""),
    sanchalak_username: str = Form(""),
    sanchalak_password: str = Form("scan123"),
):
    mt = None
    if meeting_time:
        hh, mm = meeting_time.split(":")
        mt = time_cls(int(hh), int(mm))
    mandal = BalMandal(
        name=name.strip(),
        branch_id=user.branch_id,
        weekday=weekday,
        meeting_time=mt,
        is_active=status == "Active",
    )
    db.add(mandal)
    db.flush()
    if sanchalak_username.strip():
        db.add(
            User(
                username=sanchalak_username.strip(),
                password_hash=hash_password(sanchalak_password or "scan123"),
                plain_password=sanchalak_password.strip() if sanchalak_password.strip() else "scan123",
                full_name=sanchalak_name.strip() or sanchalak_username.strip(),
                mobile=sanchalak_mobile.strip() or None,
                role="sanchalak",
                branch_id=user.branch_id,
                bal_mandal_id=mandal.id,
            )
        )
    db.commit()
    return RedirectResponse("/branch-admin/bal-mandals", status_code=303)


@router.get("/bal-mandals/{mandal_id}/edit")
def bal_mandal_edit_form(
    mandal_id: int,
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
):
    mandal = db.get(BalMandal, mandal_id)
    if not mandal or mandal.branch_id != user.branch_id:
        return RedirectResponse("/branch-admin/bal-mandals", status_code=303)
    sanch = (
        db.query(User)
        .filter(User.bal_mandal_id == mandal_id, User.role == "sanchalak")
        .first()
    )
    return templates.TemplateResponse(
        "branch_admin/bal_mandal_form.html",
        _ctx(request, user, active="bal_mandals", mandal=mandal, sanchalak=sanch, weekdays=WEEKDAYS),
    )


@router.post("/bal-mandals/{mandal_id}/edit")
def bal_mandal_edit(
    mandal_id: int,
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
    name: str = Form(...),
    weekday: str = Form(...),
    meeting_time: str = Form(""),
    status: str = Form("Active"),
    sanchalak_name: str = Form(""),
    sanchalak_mobile: str = Form(""),
    sanchalak_username: str = Form(""),
    sanchalak_password: str = Form(""),
):
    mandal = db.get(BalMandal, mandal_id)
    if not mandal or mandal.branch_id != user.branch_id:
        return RedirectResponse("/branch-admin/bal-mandals", status_code=303)
    mandal.name = name.strip()
    mandal.weekday = weekday
    mandal.is_active = status == "Active"
    if meeting_time:
        hh, mm = meeting_time.split(":")
        mandal.meeting_time = time_cls(int(hh), int(mm))

    sanch = (
        db.query(User)
        .filter(User.bal_mandal_id == mandal_id, User.role == "sanchalak")
        .first()
    )
    if sanch:
        if sanchalak_name.strip():
            sanch.full_name = sanchalak_name.strip()
        if sanchalak_mobile.strip():
            sanch.mobile = sanchalak_mobile.strip()
        if sanchalak_username.strip():
            sanch.username = sanchalak_username.strip()
        if sanchalak_password.strip():
            sanch.password_hash = hash_password(sanchalak_password.strip())
            sanch.plain_password = sanchalak_password.strip()
    elif sanchalak_username.strip():
        db.add(
            User(
                username=sanchalak_username.strip(),
                password_hash=hash_password(sanchalak_password or "scan123"),
                plain_password=sanchalak_password.strip() if sanchalak_password.strip() else "scan123",
                full_name=sanchalak_name.strip() or sanchalak_username.strip(),
                mobile=sanchalak_mobile.strip() or None,
                role="sanchalak",
                branch_id=user.branch_id,
                bal_mandal_id=mandal.id,
            )
        )
    db.commit()
    return RedirectResponse("/branch-admin/bal-mandals", status_code=303)


# --- SANCHALAK STAFF MANAGEMENT ---
@router.get("/sanchalaks")
def sanchalaks_list(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
    mandal_id: str | None = None,
    q: str | None = None,
):
    m_id = safe_int(mandal_id)
    query = (
        db.query(User)
        .options(joinedload(User.bal_mandal))
        .filter(User.branch_id == user.branch_id, User.role == "sanchalak")
    )
    if m_id:
        query = query.filter(User.bal_mandal_id == m_id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter((User.full_name.ilike(term)) | (User.username.ilike(term)) | (User.mobile.ilike(term)))
    sanchalaks = query.order_by(User.full_name).all()

    week = current_week_info()
    rows = []
    for s in sanchalaks:
        m = s.bal_mandal
        kids_count = db.query(Child).filter(Child.bal_mandal_id == m.id, Child.is_active.is_(True)).count() if m else 0
        present_count = (
            db.query(func.count(Attendance.id))
            .filter(
                Attendance.bal_mandal_id == m.id,
                Attendance.year == week["year"],
                Attendance.month == week["month"],
                Attendance.week_number == week["week_number"],
            )
            .scalar()
            if m
            else 0
        ) or 0
        last_scan = (
            db.query(Attendance)
            .filter(Attendance.bal_mandal_id == m.id)
            .order_by(Attendance.scanned_at.desc())
            .first()
            if m
            else None
        )
        rows.append({
            "sanchalak": s,
            "mandal": m,
            "children_count": kids_count,
            "present_count": present_count,
            "rate": min(round((present_count / kids_count) * 100, 1), 100.0) if kids_count else 0,
            "last_scan": last_scan,
        })
    all_mandals = db.query(BalMandal).filter(BalMandal.branch_id == user.branch_id).all()
    return templates.TemplateResponse(
        "branch_admin/sanchalaks.html",
        _ctx(
            request,
            user,
            active="sanchalaks",
            rows=rows,
            mandals=all_mandals,
            selected_mandal=m_id,
            search_query=q or "",
        ),
    )


# --- CHILDREN DIRECTORY & ENROLLMENT ---
@router.get("/children")
def children_list(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
    mandal_id: str | None = None,
    q: str | None = None,
):
    m_id = safe_int(mandal_id)
    mandals = db.query(BalMandal).filter(BalMandal.branch_id == user.branch_id).all()
    bm_ids = [m.id for m in mandals]

    query = (
        db.query(Child)
        .options(joinedload(Child.bal_mandal))
        .filter(Child.bal_mandal_id.in_(bm_ids), Child.is_active.is_(True))
    )
    if m_id and m_id in bm_ids:
        query = query.filter(Child.bal_mandal_id == m_id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter((Child.name.ilike(term)) | (Child.child_code.ilike(term)))
    children = query.order_by(Child.name).all()

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
        sanch = db.query(User).filter(User.bal_mandal_id == c.bal_mandal_id, User.role == "sanchalak").first()
        rows.append({
            "child": c,
            "mandal": c.bal_mandal,
            "sanchalak": sanch,
            "pres_count": pres_count,
            "rate": min(round((pres_count / max(week["week_number"], 1)) * 100), 100),
        })

    return templates.TemplateResponse(
        "branch_admin/children.html",
        _ctx(
            request,
            user,
            active="children",
            rows=rows,
            mandals=mandals,
            selected_mandal=m_id,
            search_query=q or "",
        ),
    )


@router.get("/children/add")
def child_add_form(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
    mandal_id: str | None = None,
):
    m_id = safe_int(mandal_id)
    mandals = db.query(BalMandal).filter(BalMandal.branch_id == user.branch_id, BalMandal.is_active.is_(True)).all()
    return templates.TemplateResponse(
        "branch_admin/child_form.html",
        _ctx(request, user, active="children", mandals=mandals, selected_mandal_id=m_id),
    )


@router.post("/children/add")
def child_add_submit(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
    name: str = Form(...),
    child_code: str = Form(...),
    bal_mandal_id: str = Form(...),
    age: str | None = Form(None),
    guardian_name: str = Form(""),
    photo_data: str = Form(""),
):
    m_id = safe_int(bal_mandal_id)
    mandal = db.get(BalMandal, m_id) if m_id else None
    if not mandal or mandal.branch_id != user.branch_id:
        return RedirectResponse("/branch-admin/children", status_code=303)

    photo = _save_data_url(photo_data, prefix="enroll")
    child = Child(
        name=name.strip(),
        child_code=child_code.strip(),
        age=safe_int(age),
        guardian_name=guardian_name.strip() or None,
        bal_mandal_id=mandal.id,
        face_photo=photo,
    )
    db.add(child)
    db.commit()
    return RedirectResponse(f"/branch-admin/children?mandal_id={mandal.id}", status_code=303)


@router.post("/children/{child_id}/face")
def update_child_face(
    child_id: int,
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
    photo_data: str = Form(...),
):
    child = db.get(Child, child_id)
    mandals = db.query(BalMandal).filter(BalMandal.branch_id == user.branch_id).all()
    bm_ids = [m.id for m in mandals]
    if not child or child.bal_mandal_id not in bm_ids:
        return RedirectResponse("/branch-admin/children", status_code=303)

    photo = _save_data_url(photo_data, prefix=f"enroll_c{child.id}")
    if photo:
        child.face_photo = photo
        db.commit()
    return RedirectResponse("/branch-admin/children", status_code=303)


# --- FACE SCAN KIOSK ---
@router.get("/face-scan")
def face_scan_view(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
    mandal_id: str | None = None,
):
    m_id = safe_int(mandal_id)
    mandals = db.query(BalMandal).filter(BalMandal.branch_id == user.branch_id, BalMandal.is_active.is_(True)).all()
    bm_ids = [m.id for m in mandals]

    active_bm_ids = [m_id] if m_id and m_id in bm_ids else bm_ids
    week = current_week_info()

    today_list = (
        db.query(Attendance)
        .options(joinedload(Attendance.child), joinedload(Attendance.bal_mandal))
        .filter(
            Attendance.bal_mandal_id.in_(active_bm_ids),
            Attendance.attendance_date == week["date"],
        )
        .order_by(Attendance.scanned_at.desc())
        .all()
        if active_bm_ids
        else []
    )

    children = (
        db.query(Child)
        .options(joinedload(Child.bal_mandal))
        .filter(Child.bal_mandal_id.in_(active_bm_ids), Child.is_active.is_(True))
        .order_by(Child.name)
        .all()
        if active_bm_ids
        else []
    )
    present_ids = {a.child_id for a in today_list}
    pending = [c for c in children if c.id not in present_ids]
    selected_mandal = db.get(BalMandal, m_id) if m_id else None

    return templates.TemplateResponse(
        "branch_admin/face_scan.html",
        _ctx(
            request,
            user,
            active="face_scan",
            mandals=mandals,
            selected_mandal=selected_mandal,
            today_list=today_list,
            children=children,
            pending=pending,
        ),
    )


@router.post("/face-scan")
def face_scan_submit(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
    photo_data: str = Form(""),
    child_id: str = Form(...),
    mandal_id: str | None = Form(None),
    client_verified: str | None = Form(None),
    client_score: str | None = Form(None),
):
    week = current_week_info()
    mandals = db.query(BalMandal).filter(BalMandal.branch_id == user.branch_id).all()
    bm_ids = [m.id for m in mandals]

    m_id = safe_int(mandal_id)
    active_bm_ids = [m_id] if m_id and m_id in bm_ids else bm_ids

    live_photo_name = _save_data_url(photo_data, prefix="scan_live")
    live_path = UPLOAD_DIR / (live_photo_name or "")

    if not live_photo_name:
        msg = "Photo could not be captured. Please face the camera and try again."
        return JSONResponse({"success": False, "is_match": False, "confidence": 0.0, "message": msg})

    if child_id == "auto":
        candidates = (
            db.query(Child)
            .options(joinedload(Child.bal_mandal))
            .filter(
                Child.bal_mandal_id.in_(active_bm_ids),
                Child.face_photo.isnot(None),
                Child.is_active.is_(True),
            )
            .all()
        )
        if not candidates:
            msg = "No registered child face photos found in this Bal Mandal! Please upload face photos first."
            return JSONResponse({"success": False, "is_match": False, "confidence": 0.0, "message": msg})

        best_child = None
        best_match = None
        best_score = -1.0

        for cand in candidates:
            enrolled_p = UPLOAD_DIR / cand.face_photo
            res = compare_face_photos(
                live_img_path=live_path,
                enrolled_img_path=enrolled_p,
                threshold=60.0,
            )
            if res["confidence"] > best_score:
                best_score = res["confidence"]
                best_match = res
                best_child = cand

        if best_match and best_match["is_match"]:
            child = best_child
            match_result = best_match
        else:
            msg = "Face does not match any registered child (Unrecognized Child Face)!"
            return JSONResponse({
                "success": False,
                "is_match": False,
                "confidence": best_score if best_score > 0 else 0.0,
                "child": {
                    "id": best_child.id,
                    "name": best_child.name,
                    "child_code": best_child.child_code,
                    "face_photo": best_child.face_photo,
                } if best_child else None,
                "live_photo": live_photo_name,
                "message": msg,
            })
    else:
        cid = safe_int(child_id)
        if not cid:
            return JSONResponse({"success": False, "message": "Invalid child ID"})
        child = db.get(Child, cid)
        if not child or child.bal_mandal_id not in bm_ids:
            return JSONResponse({"success": False, "message": "Child does not belong to this branch!"})
        if not child.face_photo:
            return JSONResponse({"success": False, "message": "Child face photo is not registered!"})

        enrolled_p = UPLOAD_DIR / child.face_photo
        match_result = compare_face_photos(
            live_img_path=live_path,
            enrolled_img_path=enrolled_p,
            threshold=60.0,
        )
        if not match_result["is_match"]:
            return JSONResponse({
                "success": False,
                "is_match": False,
                "confidence": match_result["confidence"],
                "child": {
                    "id": child.id,
                    "name": child.name,
                    "child_code": child.child_code,
                    "face_photo": child.face_photo,
                },
                "live_photo": live_photo_name,
                "message": match_result["message"],
            })

    # Record attendance
    existing = (
        db.query(Attendance)
        .filter(Attendance.child_id == child.id, Attendance.attendance_date == week["date"])
        .first()
    )
    if existing:
        att = existing
        att.scanned_at = datetime.utcnow()
        if live_photo_name:
            att.scan_photo = live_photo_name
        att.status = "present"
        att.marked_by = user.id
    else:
        att = Attendance(
            child_id=child.id,
            bal_mandal_id=child.bal_mandal_id,
            attendance_date=week["date"],
            year=week["year"],
            month=week["month"],
            week_number=week["week_number"],
            scanned_at=datetime.utcnow(),
            scan_photo=live_photo_name,
            status="present",
            marked_by=user.id,
        )
        db.add(att)
    db.commit()

    today_total = (
        db.query(Attendance)
        .filter(
            Attendance.bal_mandal_id.in_(active_bm_ids),
            Attendance.attendance_date == week["date"],
        )
        .count()
    )
    return JSONResponse({
        "success": True,
        "is_match": True,
        "confidence": match_result["confidence"],
        "attendance_id": att.id,
        "child": {
            "id": child.id,
            "name": child.name,
            "child_code": child.child_code,
            "age": child.age,
            "guardian_name": child.guardian_name,
            "face_photo": child.face_photo,
            "mandal_name": child.bal_mandal.name if child.bal_mandal else "",
        },
        "live_photo": live_photo_name,
        "scanned_at_str": datetime.utcnow().strftime("%I:%M %p"),
        "today_total": today_total,
        "message": "Attendance marked successfully!",
    })


@router.post("/manual-attendance")
def manual_attendance_submit(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
    child_id: str = Form(...),
):
    cid = safe_int(child_id)
    if not cid:
        return RedirectResponse("/branch-admin/face-scan", status_code=303)
    mandals = db.query(BalMandal).filter(BalMandal.branch_id == user.branch_id).all()
    bm_ids = [m.id for m in mandals]
    child = db.get(Child, cid)
    if not child or child.bal_mandal_id not in bm_ids:
        return RedirectResponse("/branch-admin/face-scan", status_code=303)

    week = current_week_info()
    existing = (
        db.query(Attendance)
        .filter(Attendance.child_id == child.id, Attendance.attendance_date == week["date"])
        .first()
    )
    if not existing:
        att = Attendance(
            child_id=child.id,
            bal_mandal_id=child.bal_mandal_id,
            attendance_date=week["date"],
            year=week["year"],
            month=week["month"],
            week_number=week["week_number"],
            scanned_at=datetime.utcnow(),
            status="present",
            marked_by=user.id,
        )
        db.add(att)
        db.commit()
    return RedirectResponse("/branch-admin/face-scan", status_code=303)


# --- LIVE ATTENDANCE SCANS LOG ---
@router.get("/attendance")
def attendance_history(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
    mandal_id: str | None = None,
    scan_date: str | None = None,
):
    m_id = safe_int(mandal_id)
    mandals = db.query(BalMandal).filter(BalMandal.branch_id == user.branch_id).all()
    bm_ids = [m.id for m in mandals]

    query = (
        db.query(Attendance)
        .options(
            joinedload(Attendance.child),
            joinedload(Attendance.bal_mandal),
        )
        .filter(Attendance.bal_mandal_id.in_(bm_ids))
    )
    if m_id and m_id in bm_ids:
        query = query.filter(Attendance.bal_mandal_id == m_id)
    if scan_date and scan_date.strip():
        try:
            d = date.fromisoformat(scan_date.strip())
            query = query.filter(Attendance.attendance_date == d)
        except ValueError:
            pass

    scans = query.order_by(Attendance.scanned_at.desc()).limit(150).all()
    return templates.TemplateResponse(
        "branch_admin/attendance.html",
        _ctx(
            request,
            user,
            active="attendance",
            scans=scans,
            mandals=mandals,
            selected_mandal=m_id,
            selected_date=scan_date or "",
        ),
    )


@router.post("/attendance/{att_id}/delete")
def delete_attendance(
    att_id: int,
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
):
    mandals = db.query(BalMandal).filter(BalMandal.branch_id == user.branch_id).all()
    bm_ids = [m.id for m in mandals]
    att = db.get(Attendance, att_id)
    if att and att.bal_mandal_id in bm_ids:
        db.delete(att)
        db.commit()
    return RedirectResponse("/branch-admin/attendance", status_code=303)


# --- TOP ATTENDEES ---
@router.get("/top-attendees")
def top_attendees(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
    mandal_id: str | None = None,
    year: str | None = None,
    month: str | None = None,
):
    info = current_week_info()
    year_val = safe_int(year) or info["year"]
    month_val = safe_int(month) or info["month"]
    m_id = safe_int(mandal_id)

    mandals = db.query(BalMandal).filter(BalMandal.branch_id == user.branch_id).all()
    bm_ids = [m.id for m in mandals]
    active_bm_ids = [m_id] if m_id and m_id in bm_ids else bm_ids

    children = (
        db.query(Child)
        .options(joinedload(Child.bal_mandal))
        .filter(Child.bal_mandal_id.in_(active_bm_ids), Child.is_active.is_(True))
        .all()
        if active_bm_ids
        else []
    )
    ranking = []
    for c in children:
        count = (
            db.query(func.count(Attendance.id))
            .filter(
                Attendance.child_id == c.id,
                Attendance.year == year_val,
                Attendance.month == month_val,
            )
            .scalar()
            or 0
        )
        ranking.append({"child": c, "count": count, "mandal": c.bal_mandal})
    ranking.sort(key=lambda r: r["count"], reverse=True)

    return templates.TemplateResponse(
        "branch_admin/top_attendees.html",
        _ctx(
            request,
            user,
            active="top",
            ranking=ranking,
            mandals=mandals,
            selected_mandal=m_id,
            year=year_val,
            month=month_val,
            month_label=f"{gujarati_month(month_val)} {year_val}",
        ),
    )


# --- REPORTS ---
@router.get("/reports")
def reports(
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
    year: str | None = None,
    month: str | None = None,
    week: str | None = None,
    mandal_id: str | None = None,
):
    info = current_week_info()
    year_val = safe_int(year) or info["year"]
    month_val = safe_int(month) or info["month"]
    week_val = safe_int(week)
    m_id = safe_int(mandal_id)

    mandals = db.query(BalMandal).filter(BalMandal.branch_id == user.branch_id).all()
    bm_ids = [m.id for m in mandals]
    active_bm_ids = [m_id] if m_id and m_id in bm_ids else bm_ids

    total_children = (
        db.query(Child).filter(Child.bal_mandal_id.in_(active_bm_ids), Child.is_active.is_(True)).count()
        if active_bm_ids
        else 0
    )

    week_rows = []
    for w in range(1, 6):
        p = (
            db.query(func.count(Attendance.id))
            .filter(
                Attendance.bal_mandal_id.in_(active_bm_ids),
                Attendance.year == year_val,
                Attendance.month == month_val,
                Attendance.week_number == w,
            )
            .scalar()
            if active_bm_ids
            else 0
        ) or 0
        week_rows.append(
            {
                "week": w,
                "present": p,
                "absent": max(total_children - p, 0),
                "rate": round((p / total_children) * 100, 1) if total_children else 0,
                "mandals": len(active_bm_ids),
                "children": total_children,
            }
        )

    comparison = []
    target_mandals = [m for m in mandals if m.id in active_bm_ids]
    for m in target_mandals:
        kids = db.query(Child).filter(Child.bal_mandal_id == m.id, Child.is_active.is_(True)).count()
        pq = db.query(func.count(Attendance.id)).filter(
            Attendance.bal_mandal_id == m.id,
            Attendance.year == year_val,
            Attendance.month == month_val,
        )
        if week_val:
            pq = pq.filter(Attendance.week_number == week_val)
        p = pq.scalar() or 0
        comparison.append(
            {
                "mandal": m,
                "children": kids,
                "present": p,
                "rate": round((p / kids) * 100, 1) if kids else 0,
            }
        )

    return templates.TemplateResponse(
        "branch_admin/reports.html",
        _ctx(
            request,
            user,
            active="reports",
            year=year_val,
            month=month_val,
            week_filter=week_val,
            month_label=f"{gujarati_month(month_val)} {year_val}",
            week_rows=week_rows,
            comparison=comparison,
            mandals=mandals,
            selected_mandal=m_id,
        ),
    )


# --- DELETE ENDPOINTS FOR BRANCH ADMIN ---

@router.post("/bal-mandals/{mandal_id}/delete")
def bal_mandal_delete(
    mandal_id: int,
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
):
    mandal = db.get(BalMandal, mandal_id)
    if mandal and mandal.branch_id == user.branch_id:
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
    return RedirectResponse("/branch-admin/bal-mandals", status_code=303)


@router.post("/sanchalaks/{user_id}/delete")
def sanchalak_delete(
    user_id: int,
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target and target.branch_id == user.branch_id and target.role == "sanchalak":
        target.bal_mandal_id = None
        target.branch_id = None
        db.delete(target)
        db.commit()
    return RedirectResponse("/branch-admin/sanchalaks", status_code=303)


@router.post("/children/{child_id}/delete")
def child_delete(
    child_id: int,
    request: Request,
    user: User = Depends(role_required("branch_admin")),
    db: Session = Depends(get_db),
):
    child = db.get(Child, child_id)
    mandals = db.query(BalMandal).filter(BalMandal.branch_id == user.branch_id).all()
    bm_ids = [m.id for m in mandals]
    if child and child.bal_mandal_id in bm_ids:
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
    return RedirectResponse("/branch-admin/children", status_code=303)


