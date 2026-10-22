from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import login_required
from ..models import BalMandal, Branch, Child, User

router = APIRouter(prefix="/api", tags=["spotlight"])


@router.get("/spotlight")
def spotlight_search(
    request: Request,
    q: str = "",
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
):
    query_str = (q or "").strip()
    if not query_str:
        return JSONResponse({"query": "", "categories": []})

    term = f"%{query_str}%"
    role = user.role
    categories: list[dict] = []

    # 1. Children Search
    child_query = db.query(Child).options(joinedload(Child.bal_mandal).joinedload(BalMandal.branch))
    if role == "branch_admin":
        mandals = db.query(BalMandal.id).filter(BalMandal.branch_id == user.branch_id).all()
        bm_ids = [m[0] for m in mandals]
        child_query = child_query.filter(Child.bal_mandal_id.in_(bm_ids))
    elif role == "sanchalak":
        child_query = child_query.filter(Child.bal_mandal_id == user.bal_mandal_id)

    child_query = child_query.filter(
        or_(
            Child.name.ilike(term),
            Child.child_code.ilike(term),
            Child.mobile_number.ilike(term),
            Child.standard.ilike(term),
            Child.address.ilike(term),
            Child.guardian_name.ilike(term),
        )
    )
    children = child_query.order_by(Child.is_active.desc(), Child.name).limit(10).all()

    if children:
        child_items = []
        for c in children:
            if role == "super_admin":
                target_url = f"/super-admin/children/{c.id}/edit"
            elif role == "branch_admin":
                target_url = f"/branch-admin/children/{c.id}/edit"
            else:
                target_url = f"/sanchalak/children/{c.id}/edit"

            mandal_name = c.bal_mandal.name if c.bal_mandal else "Mandal"
            branch_name = c.bal_mandal.branch.name if (c.bal_mandal and c.bal_mandal.branch) else ""
            meta_str = f"Mandal: {mandal_name}"
            if branch_name and role == "super_admin":
                meta_str += f" ({branch_name})"
            if c.mobile_number:
                meta_str += f" · 📞 {c.mobile_number}"

            subtitle_parts = [c.child_code]
            if c.standard:
                subtitle_parts.append(c.standard)
            if c.age is not None:
                subtitle_parts.append(f"{c.age} yrs")
            if c.gender:
                subtitle_parts.append(c.gender)

            child_items.append({
                "title": c.name,
                "subtitle": " · ".join(subtitle_parts),
                "badge": "Active" if c.is_active else "Archived",
                "badge_class": "bg-success-subtle text-success border border-success-subtle" if c.is_active else "bg-secondary-subtle text-secondary border",
                "meta": meta_str,
                "url": target_url,
                "photo": f"/static/uploads/{c.face_photo}" if c.face_photo else None,
                "icon": "bi-person-heart",
            })
        categories.append({
            "name": f"Children ({len(children)})",
            "icon": "bi-people-fill",
            "items": child_items,
        })

    # 3. Bal Mandals (for Super Admin & Branch Admin)
    if role in ["super_admin", "branch_admin"]:
        m_query = db.query(BalMandal).options(joinedload(BalMandal.branch))
        if role == "branch_admin":
            m_query = m_query.filter(BalMandal.branch_id == user.branch_id)
        m_query = m_query.filter(
            or_(
                BalMandal.name.ilike(term),
                BalMandal.weekday.ilike(term),
            )
        )
        mandals = m_query.order_by(BalMandal.name).limit(6).all()
        if mandals:
            m_items = []
            for m in mandals:
                url = f"/super-admin/mandals?mandal_id={m.id}" if role == "super_admin" else f"/branch-admin/bal-mandals/{m.id}/edit"
                branch_title = m.branch.name if m.branch else ""
                time_str = m.meeting_time.strftime("%I:%M %p") if m.meeting_time else "Regular time"
                m_items.append({
                    "title": m.name,
                    "subtitle": f"{m.weekday}" + (f" · Branch: {branch_title}" if branch_title else ""),
                    "badge": "Bal Mandal",
                    "badge_class": "bg-info-subtle text-info border border-info-subtle",
                    "meta": f"Meeting Time: {time_str}",
                    "url": url,
                    "icon": "bi-diagram-3-fill",
                })
            categories.append({
                "name": f"Bal Mandals ({len(mandals)})",
                "icon": "bi-diagram-3",
                "items": m_items,
            })

    # 4. Branches (for Super Admin)
    if role == "super_admin":
        b_query = db.query(Branch).filter(
            or_(
                Branch.name.ilike(term),
                Branch.code.ilike(term),
                Branch.city.ilike(term),
            )
        ).order_by(Branch.name).limit(5).all()
        if b_query:
            b_items = []
            for b in b_query:
                b_items.append({
                    "title": b.name,
                    "subtitle": f"Code: {b.code} · City: {b.city}",
                    "badge": "Branch",
                    "badge_class": "bg-primary-subtle text-primary border border-primary-subtle",
                    "meta": f"Statewide Branch · ID: {b.id}",
                    "url": f"/super-admin/branches/{b.id}/summary",
                    "icon": "bi-building-fill",
                })
            categories.append({
                "name": f"Branches ({len(b_query)})",
                "icon": "bi-building",
                "items": b_items,
            })

    # 5. Users / Sanchalaks / Staff
    u_query = db.query(User).options(joinedload(User.branch), joinedload(User.bal_mandal))
    if role == "branch_admin":
        u_query = u_query.filter(User.branch_id == user.branch_id, User.role == "sanchalak")
    elif role == "super_admin":
        pass
    else:
        u_query = None

    if u_query:
        u_query = u_query.filter(
            or_(
                User.full_name.ilike(term),
                User.username.ilike(term),
                User.mobile.ilike(term),
            )
        )
        users = u_query.order_by(User.full_name).limit(6).all()
        if users:
            u_items = []
            for u in users:
                url = "/super-admin/users" if role == "super_admin" else f"/branch-admin/sanchalaks/{u.id}/edit"
                m_info = u.bal_mandal.name if u.bal_mandal else (u.branch.name if u.branch else "")
                role_label = u.role.replace("_", " ").title()
                u_items.append({
                    "title": u.full_name or u.username,
                    "subtitle": f"@{u.username} · {role_label}" + (f" ({m_info})" if m_info else ""),
                    "badge": role_label,
                    "badge_class": "bg-warning-subtle text-warning border border-warning-subtle",
                    "meta": f"Mobile: {u.mobile or '—'}",
                    "url": url,
                    "icon": "bi-person-badge-fill",
                })
            categories.append({
                "name": f"Users & Sanchalaks ({len(users)})",
                "icon": "bi-person-badge",
                "items": u_items,
            })

    return JSONResponse({"query": query_str, "categories": categories})
