from __future__ import annotations
from datetime import date, datetime
from typing import Optional

STANDARDS = [
    "Jr KG",
    "Sr KG",
    "1st Standard",
    "2nd Standard",
    "3rd Standard",
    "4th Standard",
    "5th Standard",
    "6th Standard",
    "7th Standard",
    "8th Standard",
    "9th Standard",
    "10th Standard",
    "11th Standard",
    "12th Standard",
    "College / Graduate",
]


def parse_dob_strict(dob_str: Optional[str]) -> tuple[Optional[date], Optional[str], Optional[int]]:
    """Parse strictly DD/MM/YYYY format and return (date_obj, formatted_str, calculated_age)."""
    if not dob_str:
        return None, "", None
    cleaned = dob_str.strip().replace("-", "/")
    try:
        dt = datetime.strptime(cleaned, "%d/%m/%Y").date()
        today = date.today()
        if dt > today:
            return None, "", None
        age = today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
        return dt, cleaned, max(0, age)
    except Exception:
        return None, "", None


def promote_standard(current: Optional[str]) -> str:
    """Promote standard to the next academic level (e.g. 1st -> 2nd, 12th -> College)."""
    if not current:
        return ""
    cur = current.strip()

    # Exact match in list
    for idx, s in enumerate(STANDARDS[:-1]):
        if cur.lower() == s.lower():
            return STANDARDS[idx + 1]

    # Cleaned variations (e.g. "1st", "4th", "10")
    cur_no_std = cur.lower().replace("standard", "").replace("std", "").strip()
    for idx, s in enumerate(STANDARDS[:-1]):
        s_no_std = s.lower().replace("standard", "").strip()
        if cur_no_std == s_no_std:
            return STANDARDS[idx + 1]

    # Numeric standards
    if cur_no_std.isdigit():
        val = int(cur_no_std)
        if val < 12:
            next_val = val + 1
            suffix = "th" if 11 <= next_val <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(next_val % 10, "th")
            return f"{next_val}{suffix} Standard"
        return "College / Graduate"

    return cur
