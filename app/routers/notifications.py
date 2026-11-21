from __future__ import annotations
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from ..deps import current_user, get_db
from ..models import AppNotification, Event, User, UserNotificationRead
from ..weeks import format_dt, ist_now, ist_today

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def create_event_notification(db: Session, event: Event, creator: User, custom_message: str = "") -> AppNotification:
    """
    Creates and dispatches an in-app & device notification whenever an event/program is scheduled.
    """
    title = f"📅 New Event: {event.title}"
    
    # Priority: explicitly provided message > event description > default schedule summary
    desc_text = (event.description or "").strip()
    msg = custom_message.strip() if custom_message else desc_text
    
    details_part = f"Date: {event.event_date.strftime('%d/%m/%Y')}"
    if event.event_time:
        details_part += f" at {event.event_time}"
    if event.attendance_start_time:
        end_part = f" to {event.attendance_end_time}" if event.attendance_end_time else ""
        details_part += f" | Attendance: {event.attendance_start_time}{end_part}"
    if event.location:
        details_part += f" | Venue: {event.location}"

    full_message = f"{msg}\n\n{details_part}" if msg else details_part

    link_url = "/"
    if creator.role == "super_admin":
        link_url = f"/super-admin/attendance"
    elif creator.role == "branch_admin":
        link_url = f"/branch-admin/"
    elif creator.role == "sanchalak":
        link_url = f"/sanchalak/"

    notif = AppNotification(
        title=title,
        message=full_message,
        notification_type="event_created",
        event_id=event.id,
        branch_id=event.branch_id,
        bal_mandal_id=event.bal_mandal_id,
        target_role=event.target_role or "all",
        link_url=link_url,
        created_by_id=creator.id,
        created_at=ist_now(),
        is_active=True,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


def time_ago_str(dt: datetime) -> str:
    """Returns a friendly relative time string (e.g. 'Just now', '5m ago', '2h ago')."""
    if not dt:
        return ""
    now = ist_now()
    diff = now - dt
    secs = int(diff.total_seconds())
    if secs < 45:
        return "Just now"
    elif secs < 3600:
        mins = max(1, secs // 60)
        return f"{mins}m ago"
    elif secs < 86400:
        hours = max(1, secs // 3600)
        return f"{hours}h ago"
    elif secs < 172800:
        return "Yesterday"
    else:
        days = secs // 86400
        return f"{days}d ago"


@router.get("")
def list_notifications(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    if not user:
        return JSONResponse({"unread_count": 0, "notifications": []})

    # Scope notifications based on user role and assigned branch/mandal
    query = db.query(AppNotification).filter(AppNotification.is_active.is_(True))

    if user.role == "super_admin":
        # Super admin sees all event announcements & notifications
        pass
    elif user.role == "branch_admin":
        query = query.filter(
            or_(
                AppNotification.branch_id.is_(None),
                AppNotification.branch_id == user.branch_id,
            ),
            AppNotification.target_role.in_(["all", "branch_admin"]),
        )
    elif user.role == "sanchalak":
        mandal_id = user.bal_mandal_id
        b_id = user.bal_mandal.branch_id if user.bal_mandal else user.branch_id
        query = query.filter(
            or_(AppNotification.branch_id.is_(None), AppNotification.branch_id == b_id),
            or_(AppNotification.bal_mandal_id.is_(None), AppNotification.bal_mandal_id == mandal_id),
            AppNotification.target_role.in_(["all", "sanchalak"]),
        )

    # Latest 25 notifications
    notifs = query.order_by(desc(AppNotification.created_at)).limit(25).all()

    # Query which ones the user has marked read
    notif_ids = [n.id for n in notifs]
    read_ids = set()
    if notif_ids:
        read_records = (
            db.query(UserNotificationRead.notification_id)
            .filter(
                UserNotificationRead.user_id == user.id,
                UserNotificationRead.notification_id.in_(notif_ids),
            )
            .all()
        )
        read_ids = {r[0] for r in read_records}

    unread_count = 0
    items = []
    for n in notifs:
        is_read = n.id in read_ids
        if not is_read:
            unread_count += 1

        creator_name = n.creator.full_name if n.creator else "System Admin"
        event_info = None
        if n.event:
            event_info = {
                "id": n.event.id,
                "title": n.event.title,
                "event_date": n.event.event_date.strftime("%d/%m/%Y"),
                "event_time": n.event.event_time or "",
                "attendance_start_time": n.event.attendance_start_time or "",
                "attendance_end_time": n.event.attendance_end_time or "",
                "location": n.event.location or "",
                "event_type": n.event.event_type or "Special Sabha",
                "is_completed": n.event.is_completed,
            }

        items.append({
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "notification_type": n.notification_type,
            "event_id": n.event_id,
            "link_url": n.link_url or "/",
            "created_at": n.created_at.strftime("%Y-%m-%d %H:%M:%S") if n.created_at else "",
            "time_ago": time_ago_str(n.created_at),
            "creator_name": creator_name,
            "is_read": is_read,
            "event": event_info,
        })

    return JSONResponse({
        "unread_count": unread_count,
        "notifications": items,
        "user_role": user.role,
    })


@router.post("/mark-read")
def mark_notifications_read(
    request: Request,
    notification_id: Optional[int] = Form(None),
    mark_all: bool = Form(False),
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if mark_all:
        # Mark all notifications for this user as read
        notifs = db.query(AppNotification.id).filter(AppNotification.is_active.is_(True)).all()
        existing = {
            r[0]
            for r in db.query(UserNotificationRead.notification_id)
            .filter(UserNotificationRead.user_id == user.id)
            .all()
        }
        for (n_id,) in notifs:
            if n_id not in existing:
                db.add(UserNotificationRead(user_id=user.id, notification_id=n_id))
        db.commit()
    elif notification_id:
        exists = (
            db.query(UserNotificationRead)
            .filter(
                UserNotificationRead.user_id == user.id,
                UserNotificationRead.notification_id == notification_id,
            )
            .first()
        )
        if not exists:
            db.add(UserNotificationRead(user_id=user.id, notification_id=notification_id))
            db.commit()

    return JSONResponse({"ok": True})
