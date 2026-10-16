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
        1: "જાન્યુઆરી",
        2: "ફેબ્રુઆરી",
        3: "માર્ચ",
        4: "એપ્રિલ",
        5: "મે",
        6: "જૂન",
        7: "જુલાઈ",
        8: "ઓગસ્ટ",
        9: "સપ્ટેમ્બર",
        10: "ઓક્ટોબર",
        11: "નવેમ્બર",
        12: "ડિસેમ્બર",
    }
    return names.get(month, str(month))


def format_dt(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.strftime("%I:%M %p").lstrip("0")
