from __future__ import annotations
import base64
import uuid
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import UPLOAD_DIR, get_db
from ..deps import role_required, safe_int
from ..face_matcher import compare_face_photos
from ..models import Attendance, Child, User
from ..weeks import current_week_info, gujarati_month, week_number_for
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
        ),
    )


@router.get("/face-scan")
def face_scan(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
):
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
    client_verified: str | None = Form(None),
    client_score: str | None = Form(None),
):
    week = current_week_info()
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
                threshold=75.0,
            )
            sc = res["confidence"]
            if sc > best_score:
                second_score = best_score
                best_score = sc
                best_match = res
                best_child = cand
            elif sc > second_score:
                second_score = sc

        # Ensure distinct identification: best_score must be >= 75.0 and clearly separated
        is_distinct = (second_score < 40.0) or ((best_score - second_score) >= 8.0)
        if best_match and best_match["is_match"] and best_score >= 75.0 and is_distinct:
            child = best_child
            match_result = best_match
        else:
            msg = "Face does not match any registered child (Unrecognized Child Face)!"
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
            threshold=75.0,
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
            bal_mandal_id=user.bal_mandal_id,
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

    if is_ajax:
        today_total = (
            db.query(Attendance)
            .filter(
                Attendance.bal_mandal_id == user.bal_mandal_id,
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
                "mobile_number": child.mobile_number or "",
                "face_photo": child.face_photo,
            },
            "live_photo": live_photo_name,
            "scanned_at_str": datetime.utcnow().strftime("%I:%M %p"),
            "today_total": today_total,
            "message": "Attendance marked successfully!",
        })

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
            scanned_at=datetime.utcnow(),
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
    standard: str = Form(""),
    address: str = Form(""),
    uses_bus: bool = Form(False),
    bus_route: str = Form(""),
    photo_data: str = Form(""),
):
    form_data = {
        "first_name": first_name,
        "father_name": father_name,
        "surname": surname,
        "dob_str": dob_str,
        "gender": gender,
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
        standard=standard.strip(),
        address=address.strip(),
        guardian_name=fath or None,
        mobile_number=mobile_number.strip(),
        uses_bus=bool(uses_bus),
        bus_route=bus_route.strip() if uses_bus else "",
        child_code=child_code.strip(),
        bal_mandal_id=user.bal_mandal_id,
        face_photo=photo,
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
    standard: str = Form(""),
    address: str = Form(""),
    uses_bus: bool = Form(False),
    bus_route: str = Form(""),
    photo_data: str = Form(""),
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
    today = date.today()
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
):
    child = db.get(Child, child_id)
    if not child or child.bal_mandal_id != user.bal_mandal_id:
        return RedirectResponse("/sanchalak/children", status_code=303)
    photo = _save_data_url(photo_data, prefix=f"enroll_c{child.id}")
    if photo:
        child.face_photo = photo
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

