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
            threshold=60.0,
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
        .order_by(Child.name)
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
        _ctx(request, user, active="children", child=None),
    )


@router.post("/children/add")
def child_add(
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
    name: str = Form(...),
    child_code: str = Form(...),
    age: str | None = Form(None),
    guardian_name: str = Form(""),
    photo_data: str = Form(""),
):
    photo = _save_data_url(photo_data, prefix="enroll")
    child = Child(
        name=name.strip(),
        child_code=child_code.strip(),
        age=safe_int(age),
        guardian_name=guardian_name.strip() or None,
        bal_mandal_id=user.bal_mandal_id,
        face_photo=photo,
    )
    db.add(child)
    db.commit()
    return RedirectResponse("/sanchalak/children", status_code=303)


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
    year: str | None = None,
    month: str | None = None,
    week: str | None = None,
):
    info = current_week_info()
    year_val = safe_int(year) or info["year"]
    month_val = safe_int(month) or info["month"]
    week_val = safe_int(week)

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

    return templates.TemplateResponse(
        "sanchalak/reports.html",
        _ctx(
            request,
            user,
            active="reports",
            year=year_val,
            month=month_val,
            week_filter=week_val,
            month_label=f"{gujarati_month(month_val)} {year_val}",
            total=total,
            total_present_sum=total_present_sum,
            avg=avg,
            week_rows=week_rows,
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
    return reports(request, user, db, year, month, week)


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
def child_delete(
    child_id: int,
    request: Request,
    user: User = Depends(role_required("sanchalak")),
    db: Session = Depends(get_db),
):
    child = db.get(Child, child_id)
    if child and child.bal_mandal_id == user.bal_mandal_id:
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
    return RedirectResponse("/sanchalak/children", status_code=303)


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

