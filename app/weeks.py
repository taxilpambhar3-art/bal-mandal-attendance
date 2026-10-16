from __future__ import annotations
"""Month-local week numbering: Week 1–5 resets every month."""

from datetime import date, datetime
from calendar import monthrange


def week_number_for(d: date) -> int:
    """Day 1–7 → Week 1, 8–14 → Week 2, ... up to Week 5."""
    return ((d.day - 1) // 7) + 1


def week_date_range(year: int, month: int, week: int) -> tuple[date, date]:
    start_day = (week - 1) * 7 + 1
    end_day = min(week * 7, monthrange(year, month)[1])
    return date(year, month, start_day), date(year, month, end_day)


def current_week_info(today: date | None = None) -> dict:
    today = today or date.today()
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
    if not dt:
        return "—"
    return dt.strftime("%I:%M %p").lstrip("0")
