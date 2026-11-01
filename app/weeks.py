from __future__ import annotations
"""Month-local week numbering and Indian Standard Time (IST) utilities: Week 1–5 resets every month."""

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

# Indian Standard Time (IST) is UTC+05:30
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def ist_now() -> datetime:
    """Current naive datetime in Indian Standard Time (IST, UTC+05:30) for DB storage."""
    return datetime.now(IST).replace(tzinfo=None)


def ist_today() -> date:
    """Current date in Indian Standard Time (IST)."""
    return datetime.now(IST).date()


def week_number_for(d: date) -> int:
    """Day 1–7 → Week 1, 8–14 → Week 2, ... up to Week 5."""
    return ((d.day - 1) // 7) + 1


def week_date_range(year: int, month: int, week: int) -> tuple[date, date]:
    max_days = monthrange(year, month)[1]
    start_day = min((week - 1) * 7 + 1, max_days)
    end_day = min(week * 7, max_days)
    if start_day > end_day:
        start_day = end_day
    return date(year, month, start_day), date(year, month, end_day)


def current_week_info(today: date | None = None) -> dict:
    today = today or ist_today()
    week = week_number_for(today)
    start, end = week_date_range(today.year, today.month, week)
    return {
        "date": today,
        "year": today.year,
        "month": today.month,
        "week_number": week,
        "week_label": f"Week {week}",
        "week_start": start,
        "week_end": end,
        "month_name": today.strftime("%B %Y"),
    }


def gujarati_month(month: int) -> str:
    names = {
        1: "January",
        2: "February",
        3: "March",
        4: "April",
        5: "May",
        6: "June",
        7: "July",
        8: "August",
        9: "September",
        10: "October",
        11: "November",
        12: "December",
    }
    return names.get(month, str(month))


def format_dt(dt: datetime | None) -> str:
    """Format datetime as IST time (e.g. '11:45 AM')."""
    if not dt:
        return "—"
    if dt.tzinfo is not None:
        dt = dt.astimezone(IST)
    return dt.strftime("%I:%M %p").lstrip("0")


def format_dt_full(dt: datetime | None) -> str:
    """Format datetime as IST date & time (e.g. '01 Nov 2026, 11:45 AM')."""
    if not dt:
        return "—"
    if dt.tzinfo is not None:
        dt = dt.astimezone(IST)
    return dt.strftime("%d %b %Y, ") + dt.strftime("%I:%M %p").lstrip("0")

