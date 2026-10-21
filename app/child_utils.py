from __future__ import annotations
import re
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


NAME_REGEX = re.compile(r"^[A-Za-z\s.'-]+$")


def validate_child_form_data(
    first_name: str,
    father_name: str,
    surname: str,
    dob_str: str,
    gender: str,
    standard: str,
    mobile_number: str,
    child_code: str,
    bal_mandal_id: Optional[int],
    uses_bus: bool = False,
    bus_route: str = "",
) -> tuple[bool, str]:
    """Validate all child enrollment/edit fields on server-side. Returns (is_valid, error_msg)."""
    # 1. First Name
    fn = (first_name or "").strip()
    if not fn:
        return False, "First Name is required."
    if len(fn) < 2 or len(fn) > 50:
        return False, "First Name must be between 2 and 50 characters."
    if not NAME_REGEX.match(fn):
        return False, "First Name must contain letters and spaces only."

    # 2. Father's Name
    fath = (father_name or "").strip()
    if not fath:
        return False, "Father's Name is required."
    if len(fath) < 2 or len(fath) > 50:
        return False, "Father's Name must be between 2 and 50 characters."
    if not NAME_REGEX.match(fath):
        return False, "Father's Name must contain letters and spaces only."

    # 3. Surname
    sn = (surname or "").strip()
    if not sn:
        return False, "Surname is required."
    if len(sn) < 2 or len(sn) > 50:
        return False, "Surname must be between 2 and 50 characters."
    if not NAME_REGEX.match(sn):
        return False, "Surname must contain letters and spaces only."

    # 4. Date of Birth
    dob_raw = (dob_str or "").strip()
    if not dob_raw:
        return False, "Date of Birth is compulsory and must be entered strictly in DD/MM/YYYY format."
    dt, clean_dob, age = parse_dob_strict(dob_raw)
    if not dt or not clean_dob:
        return False, "Invalid Date of Birth. Must be in strict DD/MM/YYYY format (e.g. 15/05/2015) and cannot be in the future."
    if age is None or age < 3 or age > 25:
        return False, f"Calculated age ({age} yrs) is outside the permissible range. Child age must be between 3 and 25 years."

    # 5. Gender
    gen = (gender or "").strip()
    if gen not in ("Male", "Female"):
        return False, "Please select a valid Gender (Male or Female)."

    # 6. Standard / Grade
    std = (standard or "").strip()
    if not std or std not in STANDARDS:
        return False, "Please select a valid Annual Grade / Standard from the options."

    # 7. Mobile Number
    mob = re.sub(r"[^0-9]", "", mobile_number or "")
    if not mob:
        return False, "Mobile Number is compulsory."
    if len(mob) < 10 or len(mob) > 15:
        return False, "Mobile Number must be a valid phone number (10 to 15 digits)."

    # 8. Child Code
    code = (child_code or "").strip()
    if not code:
        return False, "Child Code / ID is required."
    if len(code) < 3 or len(code) > 40:
        return False, "Child Code must be between 3 and 40 characters."

    # 9. Bal Mandal
    if not bal_mandal_id or int(bal_mandal_id) <= 0:
        return False, "Please select a valid Bal Mandal."

    # 10. Bus transportation
    if uses_bus and bus_route:
        if len(bus_route.strip()) > 100:
            return False, "Bus Route / Stop name cannot exceed 100 characters."

    return True, ""

