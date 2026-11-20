from __future__ import annotations
import base64
import uuid
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from ..database import UPLOAD_DIR, get_db
from ..deps import role_required, safe_int
from ..face_matcher import compare_face_photos
from ..models import Attendance, BalMandal, Child, Event, User
from ..weeks import current_week_info, format_dt, gujarati_month, ist_now, ist_today, week_number_for
from ..child_utils import STANDARDS, parse_dob_strict, promote_standard, validate_child_form_data

router = APIRouter(prefix="/sanchalak", tags=["sanchalak"])
templates: Jinja2Templates | None = None


def _ctx(request: Request, user: User, **extra):
    return {
        "request": request,
        "user": user,
        "mandal": user.bal_mandal,
        "active": extra.pop("active", "dashboard"),
        "week": current_week_info(),
        **extra,
    }


from ..child_utils import parse_dob_strict, validate_child_form_data, STANDARDS, save_normalized_face_photo


def _save_data_url(data_url: str, prefix: str = "scan") -> str | None:
    return save_normalized_face_photo(data_url, prefix)


@router.get("/")
@router.get("/dashboard")
def dashboard(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
):
    mandal_id = user.bal_mandal_id
    week = current_week_info()
    children = (
        db.query(Child)
        .filter(Child.bal_mandal_id == mandal_id, Child.is_active.is_(True))
        .order_by(Child.name)
        .all()
    )
    total = len(children)
    present_ids = {
        a.child_id
        for a in db.query(Attendance)
        .filter(
            Attendance.bal_mandal_id == mandal_id,
            Attendance.year == week["year"],
            Attendance.month == week["month"],
            Attendance.week_number == week["week_number"],
        )
        .all()
    }
    present = len(present_ids)
    absent = max(total - present, 0)
    rate = round((present / total) * 100) if total else 0

    week_stats = []
    for w in range(1, 6):
        p = (
            db.query(func.count(Attendance.id))
            .filter(
                Attendance.bal_mandal_id == mandal_id,
                Attendance.year == week["year"],
                Attendance.month == week["month"],
                Attendance.week_number == w,
            )
            .scalar()
            or 0
        )
        week_stats.append({"week": w, "present": p, "rate": round((p / total) * 100) if total else 0})

    today_present = (
        db.query(Attendance)
        .filter(
            Attendance.bal_mandal_id == mandal_id,
            Attendance.attendance_date == week["date"],
        )
        .count()
    )

    mandal = user.bal_mandal
    branch_id = mandal.branch_id if mandal else None

    try:
        upcoming_events = (
            db.query(Event)
            .options(joinedload(Event.creator))
            .filter(
                Event.is_active.is_(True),
                Event.is_completed.is_(False),
                Event.event_date >= ist_today(),
                or_(
                    Event.branch_id.is_(None),
                    (Event.branch_id == branch_id) & (or_(Event.bal_mandal_id.is_(None), Event.bal_mandal_id == user.bal_mandal_id)),
                ),
            )
            .order_by(Event.event_date.asc(), Event.event_time.asc())
            .limit(6)
            .all()
        )
    except Exception as e:
        print("Sanchalak upcoming events query warning:", e)
        db.rollback()
        upcoming_events = []

    # Top Featured Event (Super Admin or Mandal Special Event)
    try:
        featured_event = (
            db.query(Event)
            .options(joinedload(Event.creator), joinedload(Event.branch))
            .filter(
                Event.is_active.is_(True),
                Event.is_completed.is_(False),
                Event.event_date >= ist_today(),
                or_(
                    Event.branch_id.is_(None),
                    (Event.branch_id == branch_id) & (or_(Event.bal_mandal_id.is_(None), Event.bal_mandal_id == user.bal_mandal_id)),
                ),
            )
            .order_by(Event.event_date.asc(), Event.event_time.asc())
            .first()
        )
    except Exception as e:
        print("Sanchalak featured event query warning:", e)
        db.rollback()
        featured_event = None

    featured_event_stats = None
    if featured_event:
        try:
            evt_present_count = (
                db.query(func.count(Attendance.id))
                .filter(
                    Attendance.bal_mandal_id == user.bal_mandal_id,
                    Attendance.event_id == featured_event.id,
                    Attendance.status == "present",
                )
                .scalar()
                or 0
            )
            featured_event_stats = {
                "present_count": evt_present_count,
                "total_children": total,
                "rate": min(round((evt_present_count / total) * 100, 1), 100.0) if total else 0,
            }
        except Exception as e:
            print("Sanchalak featured event stats query warning:", e)
            db.rollback()
            featured_event_stats = None

    return templates.TemplateResponse(
        "sanchalak/dashboard.html",
        _ctx(
            request,
            user,
            active="dashboard",
            total=total,
            present=present,
            absent=absent,
            rate=rate,
            week_stats=week_stats,
            today_present=today_present,
            upcoming_events=upcoming_events,
            featured_event=featured_event,
            featured_event_stats=featured_event_stats,
        ),
    )


@router.get("/face-scan")
def face_scan(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    event_id: str | None = None,
):
    e_id = safe_int(event_id)
    event = db.get(Event, e_id) if e_id else None

    if event:
        target_date = event.event_date
        week = current_week_info(target_date)
        today_list = (
            db.query(Attendance)
            .filter(
                Attendance.bal_mandal_id == user.bal_mandal_id,
                Attendance.event_id == event.id,
            )
            .order_by(Attendance.scanned_at.desc())
            .all()
        )
    else:
        week = current_week_info()
        today_list = (
            db.query(Attendance)
            .filter(
                Attendance.bal_mandal_id == user.bal_mandal_id,
                Attendance.attendance_date == week["date"],
            )
            .order_by(Attendance.scanned_at.desc())
            .all()
        )

    children = (
        db.query(Child)
        .filter(Child.bal_mandal_id == user.bal_mandal_id, Child.is_active.is_(True))
        .order_by(Child.name)
        .all()
    )
    present_ids = {a.child_id for a in today_list}
    pending = [c for c in children if c.id not in present_ids]
    return templates.TemplateResponse(
        "sanchalak/face_scan.html",
        _ctx(
            request,
            user,
            active="face_scan",
            today_list=today_list,
            children=children,
            pending=pending,
            event=event,
            result=None,
            error=None,
        ),
    )


@router.post("/face-scan")
def face_scan_submit(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    photo_data: str = Form(""),
    child_id: str = Form(...),
    event_id: str | None = Form(None),
    client_verified: str | None = Form(None),
    client_score: str | None = Form(None),
):
    e_id = safe_int(event_id) or safe_int(request.query_params.get("event_id"))
    event = db.get(Event, e_id) if e_id else None

    if event:
        target_date = event.event_date
        week = current_week_info(target_date)
    else:
        target_date = ist_today()
        week = current_week_info(target_date)

    live_photo_name = _save_data_url(photo_data, prefix="scan_live")
    live_path = UPLOAD_DIR / (live_photo_name or "")

    c_ver: bool | None = None
    if client_verified and client_verified.strip():
        c_ver = client_verified.strip().lower() in ("true", "1", "yes")

    parsed_client_score: float | None = None
    if client_score and client_score.strip():
        try:
            parsed_client_score = float(client_score.strip())
        except ValueError:
            parsed_client_score = None

    is_ajax = (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in request.headers.get("accept", "")
        or request.query_params.get("ajax") == "1"
    )

    if not live_photo_name:
        msg = "Photo could not be captured. Please face the camera and try again."
        if is_ajax:
            return JSONResponse({"success": False, "is_match": False, "confidence": 0.0, "message": msg})
        return templates.TemplateResponse(
            "sanchalak/face_fail.html",
            _ctx(
                request,
                user,
                active="face_scan",
                child=None,
                live_photo=None,
                confidence=0.0,
                message=msg,
            ),
        )

    # Option A: Auto-Detect mode across all enrolled children in this Bal Mandal
    if child_id == "auto":
        candidates = (
            db.query(Child)
            .filter(
                Child.bal_mandal_id == user.bal_mandal_id,
                Child.face_photo.isnot(None),
                Child.is_active.is_(True),
            )
            .all()
        )
        if not candidates:
            msg = "No registered child face photos found in this Bal Mandal! Please upload face photos first."
            if is_ajax:
                return JSONResponse({"success": False, "is_match": False, "confidence": 0.0, "message": msg})
            return templates.TemplateResponse(
                "sanchalak/face_fail.html",
                _ctx(
                    request,
                    user,
                    active="face_scan",
                    child=None,
                    live_photo=live_photo_name,
                    confidence=0.0,
                    message=msg,
                ),
            )

        best_child = None
        best_match = None
        best_score = -1.0
        second_score = -1.0

        for cand in candidates:
            enrolled_p = UPLOAD_DIR / cand.face_photo
            res = compare_face_photos(
                live_img_path=live_path,
                enrolled_img_path=enrolled_p,
                threshold=58.0,
            )
            sc = res["confidence"]
            if sc > best_score:
                second_score = best_score
                best_score = sc
                best_match = res
                best_child = cand
            elif sc > second_score:
                second_score = sc

        if best_match and best_match["is_match"] and best_score >= 58.0:
            child = best_child
            match_result = best_match
        else:
            msg = "Face does not match any registered child in this Bal Mandal (Unrecognized Child Face)!"
            if is_ajax:
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
            return templates.TemplateResponse(
                "sanchalak/face_fail.html",
                _ctx(
                    request,
                    user,
                    active="face_scan",
                    child=best_child,
                    live_photo=live_photo_name,
                    confidence=best_score if best_score > 0 else 0.0,
                    message=msg,
                ),
            )

    # Option B: Specific Child Verification
    else:
        try:
            cid = int(child_id)
        except ValueError:
            if is_ajax:
                return JSONResponse({"success": False, "message": "Invalid child ID"})
            return RedirectResponse("/sanchalak/face-scan", status_code=303)

        child = db.get(Child, cid)
        if not child or child.bal_mandal_id != user.bal_mandal_id:
            if is_ajax:
                return JSONResponse({"success": False, "message": "Child not found"})
            return RedirectResponse("/sanchalak/face-scan", status_code=303)

        if not child.face_photo:
            msg = "Child face photo is not registered in the system! Please upload a photo in child profile first."
            if is_ajax:
                return JSONResponse({
                    "success": False,
                    "is_match": False,
                    "confidence": 0.0,
                    "child": {"id": child.id, "name": child.name, "child_code": child.child_code, "face_photo": None},
                    "live_photo": live_photo_name,
                    "message": msg,
                })
            return templates.TemplateResponse(
                "sanchalak/face_fail.html",
                _ctx(
                    request,
                    user,
                    active="face_scan",
                    child=child,
                    live_photo=live_photo_name,
                    confidence=0.0,
                    message=msg,
                ),
            )

        enrolled_path = UPLOAD_DIR / child.face_photo
        match_result = compare_face_photos(
            live_img_path=live_path,
            enrolled_img_path=enrolled_path,
            threshold=58.0,
            client_verified=c_ver,
            client_score=parsed_client_score,
        )

        if not match_result["is_match"]:
            if is_ajax:
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
            return templates.TemplateResponse(
                "sanchalak/face_fail.html",
                _ctx(
                    request,
                    user,
                    active="face_scan",
                    child=child,
                    live_photo=live_photo_name,
                    confidence=match_result["confidence"],
                    message=match_result["message"],
                ),
            )

    # If MATCHED -> Mark attendance as PRESENT
    if event:
        existing = (
            db.query(Attendance)
            .filter(
                Attendance.child_id == child.id,
                Attendance.event_id == event.id,
            )
            .first()
        )
    else:
        existing = (
            db.query(Attendance)
            .filter(
                Attendance.child_id == child.id,
                Attendance.attendance_date == week["date"],
                Attendance.event_id.is_(None),
            )
            .first()
        )

    if existing:
        att = existing
        att.scanned_at = ist_now()
        if live_photo_name:
            att.scan_photo = live_photo_name
        att.status = "present"
        att.marked_by = user.id
        if event:
            att.event_id = event.id
            att.attendance_date = target_date
            att.year = week["year"]
            att.month = week["month"]
            att.week_number = week["week_number"]
    else:
        att = Attendance(
            child_id=child.id,
            bal_mandal_id=child.bal_mandal_id or user.bal_mandal_id,
            event_id=event.id if event else None,
            attendance_date=target_date,
            year=week["year"],
            month=week["month"],
            week_number=week["week_number"],
            scanned_at=ist_now(),
            scan_photo=live_photo_name,
            status="present",
            marked_by=user.id,
        )
        db.add(att)
    db.commit()

    if is_ajax:
        if event:
            today_total = (
                db.query(Attendance)
                .filter(
                    Attendance.bal_mandal_id == user.bal_mandal_id,
                    Attendance.event_id == event.id,
                    Attendance.status == "present",
                )
                .count()
            )
        else:
            today_total = (
                db.query(Attendance)
                .filter(
                    Attendance.bal_mandal_id == user.bal_mandal_id,
                    Attendance.attendance_date == week["date"],
                    Attendance.status == "present",
                )
                .count()
            )
        return JSONResponse({
            "success": True,
            "is_match": True,
            "confidence": match_result["confidence"],
            "attendance_id": att.id,
            "event_id": event.id if event else None,
            "child": {
                "id": child.id,
                "name": child.name,
                "child_code": child.child_code,
                "age": child.age,
                "guardian_name": child.guardian_name,
                "mobile_number": child.mobile_number or "",
                "face_photo": child.face_photo,
            },
            "live_photo": live_photo_name,
            "scanned_at_str": format_dt(att.scanned_at),
            "today_total": today_total,
            "message": f"Attendance marked for {child.name}!" + (f" ({event.title})" if event else ""),
        })

    if event:
        return RedirectResponse(f"/sanchalak/face-scan?event_id={event.id}", status_code=303)

    return templates.TemplateResponse(
        "sanchalak/face_result.html",
        _ctx(
            request,
            user,
            active="face_scan",
            att=att,
            child=child,
            confidence=match_result["confidence"],
        ),
    )


@router.post("/manual-attendance")
def manual_attendance_submit(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    child_id: int = Form(...),
    live_photo: str = Form(""),
):
    week = current_week_info()
    child = db.get(Child, child_id)
    if not child or child.bal_mandal_id != user.bal_mandal_id:
        return RedirectResponse("/sanchalak/face-scan", status_code=303)

    existing = (
        db.query(Attendance)
        .filter(Attendance.child_id == child.id, Attendance.attendance_date == week["date"])
        .first()
    )
    if not existing:
        att = Attendance(
            child_id=child.id,
            bal_mandal_id=user.bal_mandal_id,
            attendance_date=week["date"],
            year=week["year"],
            month=week["month"],
            week_number=week["week_number"],
            scanned_at=ist_now(),
            scan_photo=live_photo or None,
            status="present",
            marked_by=user.id,
        )
        db.add(att)
        db.commit()
        att_id = att.id
    else:
        att_id = existing.id

    return RedirectResponse(f"/sanchalak/face-scan/result/{att_id}?manual=1", status_code=303)


@router.get("/face-scan/result")
def face_scan_result_latest(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
):
    att = (
        db.query(Attendance)
        .filter(Attendance.bal_mandal_id == user.bal_mandal_id)
        .order_by(Attendance.scanned_at.desc())
        .first()
    )
    if not att:
        return RedirectResponse("/sanchalak/face-scan", status_code=303)
    return face_scan_result(att.id, request, user, db)


@router.get("/face-scan/result/{attendance_id}")
def face_scan_result(
    attendance_id: int,
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
):
    att = db.get(Attendance, attendance_id)
    if not att or att.bal_mandal_id != user.bal_mandal_id:
        return RedirectResponse("/sanchalak/face-scan", status_code=303)
    return templates.TemplateResponse(
        "sanchalak/face_result.html",
        _ctx(request, user, active="face_scan", att=att, child=att.child, confidence=95.0),
    )


@router.get("/children")
def children_list(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
):
    children = (
        db.query(Child)
        .filter(Child.bal_mandal_id == user.bal_mandal_id)
        .order_by(Child.is_active.desc(), Child.name)
        .all()
    )
    return templates.TemplateResponse(
        "sanchalak/children.html",
        _ctx(request, user, active="children", children=children),
    )


@router.get("/children/add")
def child_add_form(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
):
    return templates.TemplateResponse(
        "sanchalak/child_form.html",
        _ctx(request, user, active="children", child=None, standards=STANDARDS),
    )


@router.post("/children/add")
def child_add(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    first_name: str = Form(""),
    father_name: str = Form(""),
    surname: str = Form(""),
    name: str = Form(""),
    dob_str: str = Form(""),
    child_code: str = Form(...),
    mobile_number: str = Form(...),
    gender: str = Form("Male"),
    position: str = Form("Student"),
    standard: str = Form(""),
    address: str = Form(""),
    uses_bus: bool = Form(False),
    bus_route: str = Form(""),
    photo_data: str = Form(""),
    face_descriptor: str = Form(""),
):
    form_data = {
        "first_name": first_name,
        "father_name": father_name,
        "surname": surname,
        "dob_str": dob_str,
        "gender": gender,
        "position": position,
        "standard": standard,
        "address": address,
        "mobile_number": mobile_number,
        "uses_bus": uses_bus,
        "bus_route": bus_route,
        "child_code": child_code,
        "bal_mandal_id": user.bal_mandal_id,
    }

    # 1. Server-side validation
    is_valid, err = validate_child_form_data(
        first_name=first_name,
        father_name=father_name,
        surname=surname,
        dob_str=dob_str,
        gender=gender,
        standard=standard,
        mobile_number=mobile_number,
        child_code=child_code,
        bal_mandal_id=user.bal_mandal_id,
        uses_bus=uses_bus,
        bus_route=bus_route,
        position=position,
    )
    if not is_valid:
        return templates.TemplateResponse(
            "sanchalak/child_form.html",
            _ctx(request, user, active="children", child=None, form_data=form_data, standards=STANDARDS, error_msg=err),
        )

    # 2. Check unique child code
    existing = db.query(Child).filter(Child.child_code == child_code.strip()).first()
    if existing:
        return templates.TemplateResponse(
            "sanchalak/child_form.html",
            _ctx(request, user, active="children", child=None, form_data=form_data, standards=STANDARDS, error_msg=f"Child ID '{child_code}' is already registered. Please generate a unique ID."),
        )

    fn = first_name.strip()
    fath = father_name.strip()
    sn = surname.strip()
    full_name = f"{fn} {fath} {sn}".strip() if (fn or sn) else name.strip()
    dob_dt, dob_clean, calculated_age = parse_dob_strict(dob_str)

    photo = _save_data_url(photo_data, prefix="enroll")
    child = Child(
        name=full_name,
        first_name=fn,
        father_name=fath,
        surname=sn,
        dob=dob_dt,
        dob_str=dob_clean or dob_str.strip(),
        age=calculated_age,
        gender=gender.strip() or "Male",
        position=position.strip() if position else "Student",
        standard=standard.strip(),
        address=address.strip(),
        guardian_name=fath or None,
        mobile_number=mobile_number.strip(),
        uses_bus=bool(uses_bus),
        bus_route=bus_route.strip() if uses_bus else "",
        child_code=child_code.strip(),
        bal_mandal_id=user.bal_mandal_id,
        face_photo=photo,
        face_descriptor=face_descriptor.strip() if face_descriptor and face_descriptor.strip().startswith("[") else None,
    )
    db.add(child)
    db.commit()
    return RedirectResponse("/sanchalak/children?enrolled=1", status_code=303)


@router.get("/children/{child_id}/edit")
def child_edit_form(
    child_id: int,
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
):
    child = db.get(Child, child_id)
    if not child or child.bal_mandal_id != user.bal_mandal_id:
        return RedirectResponse("/sanchalak/children", status_code=303)

    return templates.TemplateResponse(
        "sanchalak/child_form.html",
        _ctx(request, user, active="children", child=child, standards=STANDARDS),
    )


@router.post("/children/{child_id}/edit")
def child_edit_submit(
    child_id: int,
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    first_name: str = Form(""),
    father_name: str = Form(""),
    surname: str = Form(""),
    dob_str: str = Form(""),
    child_code: str = Form(...),
    mobile_number: str = Form(...),
    gender: str = Form("Male"),
    position: str = Form("Student"),
    standard: str = Form(""),
    address: str = Form(""),
    uses_bus: bool = Form(False),
    bus_route: str = Form(""),
    photo_data: str = Form(""),
    face_descriptor: str = Form(""),
):
    child = db.get(Child, child_id)
    if not child or child.bal_mandal_id != user.bal_mandal_id:
        return RedirectResponse("/sanchalak/children", status_code=303)

    is_valid, err = validate_child_form_data(
        first_name=first_name,
        father_name=father_name,
        surname=surname,
        dob_str=dob_str,
        gender=gender,
        standard=standard,
        mobile_number=mobile_number,
        child_code=child_code,
        bal_mandal_id=user.bal_mandal_id,
        uses_bus=uses_bus,
        bus_route=bus_route,
        position=position,
    )
    if not is_valid:
        return templates.TemplateResponse(
            "sanchalak/child_form.html",
            _ctx(request, user, active="children", child=child, standards=STANDARDS, error_msg=err),
        )

    # Check child_code uniqueness against other records
    existing = db.query(Child).filter(Child.child_code == child_code.strip(), Child.id != child.id).first()
    if existing:
        return templates.TemplateResponse(
            "sanchalak/child_form.html",
            _ctx(request, user, active="children", child=child, standards=STANDARDS, error_msg=f"Child ID '{child_code}' is already assigned to another child."),
        )

    fn = first_name.strip()
    fath = father_name.strip()
    sn = surname.strip()
    dob_dt, dob_clean, calculated_age = parse_dob_strict(dob_str)

    child.first_name = fn
    child.father_name = fath
    child.surname = sn
    child.name = f"{fn} {fath} {sn}".strip()
    child.dob = dob_dt
    child.dob_str = dob_clean or dob_str.strip()
    child.age = calculated_age
    child.gender = gender.strip() or "Male"
    child.position = position.strip() if position else "Student"
    child.standard = standard.strip()
    child.address = address.strip()
    child.guardian_name = fath or None
    child.mobile_number = mobile_number.strip()
    child.uses_bus = bool(uses_bus)
    child.bus_route = bus_route.strip() if uses_bus else ""
    child.child_code = child_code.strip()

    # If new photo captured during edit, update photo
    if photo_data and "," in photo_data:
        new_photo = _save_data_url(photo_data, prefix=f"enroll_c{child.id}")
        if new_photo:
            child.face_photo = new_photo
            if face_descriptor and face_descriptor.strip().startswith("["):
                child.face_descriptor = face_descriptor.strip()
            else:
                child.face_descriptor = None
    elif face_descriptor and face_descriptor.strip().startswith("["):
        child.face_descriptor = face_descriptor.strip()

    db.commit()
    # HISTORY IS PRESERVED: attendance table is untouched!
    return RedirectResponse("/sanchalak/children?updated=1", status_code=303)


@router.post("/children/promote-standards")
def promote_sanchalak_children_standards(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
):
    children = db.query(Child).filter(Child.bal_mandal_id == user.bal_mandal_id, Child.is_active.is_(True)).all()
    count = 0
    today = ist_today()
    for c in children:
        if c.standard:
            c.standard = promote_standard(c.standard)
            count += 1
        if c.dob:
            c.age = today.year - c.dob.year - ((today.month, today.day) < (c.dob.month, c.dob.day))
    db.commit()
    return RedirectResponse(f"/sanchalak/children?promoted={count}", status_code=303)


@router.post("/children/{child_id}/face")
def update_child_face(
    child_id: int,
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    photo_data: str = Form(...),
    face_descriptor: str = Form(""),
):
    child = db.get(Child, child_id)
    if not child or child.bal_mandal_id != user.bal_mandal_id:
        return RedirectResponse("/sanchalak/children", status_code=303)
    photo = _save_data_url(photo_data, prefix=f"enroll_c{child.id}")
    if photo:
        child.face_photo = photo
        if face_descriptor and face_descriptor.strip().startswith("["):
            child.face_descriptor = face_descriptor.strip()
        else:
            child.face_descriptor = None
        db.commit()
    return RedirectResponse("/sanchalak/children", status_code=303)


@router.get("/reports")
def reports(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    type: str | None = None,
    year: str | None = None,
    month: str | None = None,
    week: str | None = None,
):
    info = current_week_info()
    year_val = safe_int(year) or info["year"]
    month_val = safe_int(month) or info["month"]
    week_val = safe_int(week)
    report_type = type or request.query_params.get("type") or ("weekly" if week_val else "monthly")

    # If weekly view selected but no week number passed, default to current week
    if report_type in ("weekly", "week") and not week_val:
        week_val = info["week_number"] if month_val == info["month"] and year_val == info["year"] else 1

    total = (
        db.query(Child)
        .filter(Child.bal_mandal_id == user.bal_mandal_id, Child.is_active.is_(True))
        .count()
    )
    week_rows = []
    total_present_sum = 0
    for w in range(1, 6):
        p = (
            db.query(func.count(Attendance.id))
            .filter(
                Attendance.bal_mandal_id == user.bal_mandal_id,
                Attendance.year == year_val,
                Attendance.month == month_val,
                Attendance.week_number == w,
            )
            .scalar()
            or 0
        )
        total_present_sum += p
        week_rows.append(
            {
                "week": w,
                "present": p,
                "absent": max(total - p, 0),
                "rate": round((p / total) * 100, 1) if total else 0,
            }
        )
    avg = round((total_present_sum / (total * 5)) * 100, 1) if total else 0

    week_attendees = []
    if week_val:
        atts = (
            db.query(Attendance)
            .filter(
                Attendance.bal_mandal_id == user.bal_mandal_id,
                Attendance.year == year_val,
                Attendance.month == month_val,
                Attendance.week_number == week_val,
            )
            .all()
        )
        att_map = {a.child_id: a for a in atts}
        children_list = (
            db.query(Child)
            .filter(Child.bal_mandal_id == user.bal_mandal_id, Child.is_active.is_(True))
            .order_by(Child.name)
            .all()
        )
        for c in children_list:
            a = att_map.get(c.id)
            week_attendees.append({
                "child": c,
                "status": "present" if a else "absent",
                "scanned_at": a.scanned_at if a else None,
                "scan_photo": a.scan_photo if a else None,
            })

    return templates.TemplateResponse(
        "sanchalak/reports.html",
        _ctx(
            request,
            user,
            active="reports",
            year=year_val,
            month=month_val,
            week_filter=week_val,
            report_type=report_type,
            month_label=f"{gujarati_month(month_val)} {year_val}",
            total=total,
            total_present_sum=total_present_sum,
            avg=avg,
            week_rows=week_rows,
            week_attendees=week_attendees,
        ),
    )


@router.get("/attendance-report")
def attendance_report_alias(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    type: str | None = None,
    year: str | None = None,
    month: str | None = None,
    week: str | None = None,
):
    if type == "custom":
        return RedirectResponse("/sanchalak/reports/custom", status_code=303)
    return reports(request, user, db, type, year, month, week)


@router.get("/reports/custom")
def custom_report(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    start: str | None = None,
    end: str | None = None,
):
    rows = []
    start_d = end_d = None
    if start and end:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
        rows = (
            db.query(Attendance)
            .filter(
                Attendance.bal_mandal_id == user.bal_mandal_id,
                Attendance.attendance_date >= start_d,
                Attendance.attendance_date <= end_d,
            )
            .order_by(Attendance.attendance_date.desc(), Attendance.scanned_at.desc())
            .all()
        )
    return templates.TemplateResponse(
        "sanchalak/custom_report.html",
        _ctx(
            request,
            user,
            active="reports",
            rows=rows,
            start=start,
            end=end,
        ),
    )


@router.get("/top-attendees")
def top_attendees(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    year: str | None = None,
    month: str | None = None,
):
    info = current_week_info()
    year_val = safe_int(year) or info["year"]
    month_val = safe_int(month) or info["month"]
    children = (
        db.query(Child)
        .filter(Child.bal_mandal_id == user.bal_mandal_id, Child.is_active.is_(True))
        .all()
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
        ranking.append({"child": c, "count": count})
    ranking.sort(key=lambda r: r["count"], reverse=True)
    return templates.TemplateResponse(
        "sanchalak/top_attendees.html",
        _ctx(
            request,
            user,
            active="top",
            ranking=ranking,
            year=year_val,
            month=month_val,
            month_label=f"{gujarati_month(month_val)} {year_val}",
        ),
    )


@router.get("/child-report")
def child_report_alias(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    year: str | None = None,
    month: str | None = None,
):
    return top_attendees(request, user, db, year, month)


@router.get("/history")
def history(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Attendance)
        .filter(Attendance.bal_mandal_id == user.bal_mandal_id)
        .order_by(Attendance.attendance_date.desc(), Attendance.scanned_at.desc())
        .limit(100)
        .all()
    )
    return templates.TemplateResponse(
        "sanchalak/history.html",
        _ctx(request, user, active="history", rows=rows),
    )


# --- DELETE ENDPOINTS FOR SANCHALAK ---

@router.post("/children/{child_id}/delete")
@router.post("/children/{child_id}/deactivate")
def child_deactivate(
    child_id: int,
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
):
    child = db.get(Child, child_id)
    if child and child.bal_mandal_id == user.bal_mandal_id:
        # REQUIREMENT: History must not be deleted!
        # Soft-deactivate child. NEVER delete Attendance records.
        child.is_active = False
        db.commit()
    return RedirectResponse("/sanchalak/children?archived=1", status_code=303)


@router.post("/children/{child_id}/reactivate")
def child_reactivate(
    child_id: int,
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
):
    child = db.get(Child, child_id)
    if child and child.bal_mandal_id == user.bal_mandal_id:
        child.is_active = True
        db.commit()
    return RedirectResponse("/sanchalak/children?reactivated=1", status_code=303)


@router.post("/attendance/{att_id}/delete")
def attendance_delete(
    att_id: int,
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
):
    att = db.get(Attendance, att_id)
    if att and att.bal_mandal_id == user.bal_mandal_id:
        if att.scan_photo:
            p = UPLOAD_DIR / att.scan_photo
            if p.exists() and p.is_file():
                try:
                    p.unlink()
                except Exception:
                    pass
        db.delete(att)
        db.commit()
    return RedirectResponse("/sanchalak/history", status_code=303)


# --- EVENTS & SCHEDULES MANAGEMENT ---
@router.get("/events")
def events_list(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    filter_type: str | None = None,
):
    mandal = user.bal_mandal
    branch_id = mandal.branch_id if mandal else None
    today = ist_today()
    query = (
        db.query(Event)
        .options(joinedload(Event.creator))
        .filter(
            Event.is_active.is_(True),
            or_(
                Event.branch_id.is_(None),
                (Event.branch_id == branch_id) & (or_(Event.bal_mandal_id.is_(None), Event.bal_mandal_id == user.bal_mandal_id)),
            ),
        )
    )

    if filter_type == "past":
        query = query.filter(Event.event_date < today).order_by(Event.event_date.desc(), Event.event_time.desc())
    elif filter_type == "all":
        query = query.order_by(Event.event_date.desc(), Event.event_time.desc())
    else:
        query = query.filter(Event.event_date >= today).order_by(Event.event_date.asc(), Event.event_time.asc())

    events = query.all()
    return templates.TemplateResponse(
        "sanchalak/events.html",
        _ctx(
            request,
            user,
            active="events",
            events=events,
            filter_type=filter_type or "upcoming",
            today=today,
        ),
    )


@router.post("/events/add")
def event_add(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    title: str = Form(...),
    event_date: str = Form(...),
    event_time: str = Form(""),
    attendance_start_time: str = Form(""),
    attendance_end_time: str = Form(""),
    event_type: str = Form("Special Sabha"),
    location: str = Form(""),
    description: str = Form(""),
    next_url: str = Form("/sanchalak/events"),
):
    try:
        e_date = date.fromisoformat(event_date.strip())
    except (ValueError, TypeError):
        e_date = ist_today()

    mandal = user.bal_mandal
    branch_id = mandal.branch_id if mandal else None
    a_start = attendance_start_time.strip() if attendance_start_time else (event_time.strip() if event_time else "")
    a_end = attendance_end_time.strip() if attendance_end_time else ""

    new_event = Event(
        title=title.strip(),
        description=description.strip() if description else "",
        event_date=e_date,
        event_time=event_time.strip() if event_time else "",
        attendance_start_time=a_start,
        attendance_end_time=a_end,
        event_type=event_type.strip() if event_type else "Special Sabha",
        location=location.strip() if location else "",
        branch_id=branch_id,
        bal_mandal_id=user.bal_mandal_id,
        target_role="all",
        created_by_id=user.id,
        is_active=True,
    )
    db.add(new_event)
    db.commit()
    redirect_to = next_url if next_url and next_url.startswith("/") else "/sanchalak/events"
    sep = "&" if "?" in redirect_to else "?"
    return RedirectResponse(f"{redirect_to}{sep}event_created=1", status_code=303)


@router.post("/events/{event_id}/delete")
def event_delete(
    event_id: int,
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    next_url: str = Form("/sanchalak/events"),
):
    evt = db.get(Event, event_id)
    if evt and (evt.created_by_id == user.id or evt.bal_mandal_id == user.bal_mandal_id):
        db.delete(evt)
        db.commit()
    redirect_to = next_url if next_url and next_url.startswith("/") else "/sanchalak/events"
    sep = "&" if "?" in redirect_to else "?"
    return RedirectResponse(f"{redirect_to}{sep}event_deleted=1", status_code=303)


@router.post("/events/{event_id}/complete")
def event_complete(
    event_id: int,
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    next_url: str = Form("/sanchalak/dashboard"),
):
    evt = db.get(Event, event_id)
    if evt:
        evt.is_completed = True
        evt.completed_at = ist_now()
        evt.completed_by_id = user.id
        db.commit()
    redirect_to = next_url if next_url and next_url.startswith("/") else "/sanchalak/dashboard"
    sep = "&" if "?" in redirect_to else "?"
    return RedirectResponse(f"{redirect_to}{sep}event_completed=1", status_code=303)


@router.post("/events/{event_id}/uncomplete")
def event_uncomplete(
    event_id: int,
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    next_url: str = Form("/sanchalak/dashboard"),
):
    evt = db.get(Event, event_id)
    if evt:
        evt.is_completed = False
        evt.completed_at = None
        db.commit()
    redirect_to = next_url if next_url and next_url.startswith("/") else "/sanchalak/dashboard"
    sep = "&" if "?" in redirect_to else "?"
    return RedirectResponse(f"{redirect_to}{sep}event_reopened=1", status_code=303)


@router.get("/events/{event_id}/attendance")
def event_attendance_view(
    event_id: int,
    user: User = Depends(role_required("sanchalak")),
):
    return RedirectResponse(f"/sanchalak/face-scan?event_id={event_id}", status_code=303)


@router.post("/events/{event_id}/attendance")
async def event_attendance_submit(
    event_id: int,
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
):
    evt = db.get(Event, event_id)
    if not evt:
        return RedirectResponse("/sanchalak/dashboard", status_code=303)

    form_data = await request.form()
    submitted_child_ids = set()
    for key, val in form_data.multi_items():
        if key == "child_ids":
            try:
                submitted_child_ids.add(int(val))
            except (ValueError, TypeError):
                pass

    all_children = (
        db.query(Child)
        .filter(Child.bal_mandal_id == user.bal_mandal_id, Child.is_active.is_(True))
        .all()
    )

    target_date = evt.event_date
    w_num = week_number_for(target_date)

    for child in all_children:
        existing = (
            db.query(Attendance)
            .filter(Attendance.child_id == child.id, Attendance.event_id == evt.id)
            .first()
        )
        if child.id in submitted_child_ids:
            if existing:
                existing.status = "present"
                existing.marked_by = user.id
            else:
                att = Attendance(
                    child_id=child.id,
                    bal_mandal_id=user.bal_mandal_id,
                    attendance_date=target_date,
                    year=target_date.year,
                    month=target_date.month,
                    week_number=w_num,
                    status="present",
                    event_id=evt.id,
                    marked_by=user.id,
                )
                db.add(att)
        else:
            if existing:
                db.delete(existing)

    db.commit()
    return RedirectResponse(f"/sanchalak/events/{event_id}/attendance?saved=1", status_code=303)



