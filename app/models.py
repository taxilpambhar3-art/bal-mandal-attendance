from __future__ import annotations
from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    plain_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(120))
    mobile: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    role: Mapped[str] = mapped_column(String(30))  # super_admin | branch_admin | sanchalak
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"), nullable=True)
    bal_mandal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bal_mandals.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    branch = relationship("Branch", back_populates="admins", foreign_keys=[branch_id])
    bal_mandal = relationship("BalMandal", back_populates="sanchalak", foreign_keys=[bal_mandal_id])


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(40), unique=True)
    city: Mapped[str] = mapped_column(String(80))
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    admins = relationship("User", back_populates="branch", foreign_keys="User.branch_id")
    bal_mandals = relationship("BalMandal", back_populates="branch")


class BalMandal(Base):
    __tablename__ = "bal_mandals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    weekday: Mapped[str] = mapped_column(String(20))  # Gujarati day name
    meeting_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    branch = relationship("Branch", back_populates="bal_mandals")
    sanchalak = relationship("User", back_populates="bal_mandal", foreign_keys="User.bal_mandal_id")
    children = relationship("Child", back_populates="bal_mandal")
    attendances = relationship("Attendance", back_populates="bal_mandal")


class Child(Base):
    __tablename__ = "children"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    guardian_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    bal_mandal_id: Mapped[int] = mapped_column(ForeignKey("bal_mandals.id"))
    face_photo: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bal_mandal = relationship("BalMandal", back_populates="children")
    attendances = relationship("Attendance", back_populates="child")


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("child_id", "attendance_date", name="uq_child_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))
    bal_mandal_id: Mapped[int] = mapped_column(ForeignKey("bal_mandals.id"))
    attendance_date: Mapped[date] = mapped_column(Date, index=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)  # 1-12
    week_number: Mapped[int] = mapped_column(Integer)  # 1-5 within month
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    scan_photo: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="present")
    marked_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    child = relationship("Child", back_populates="attendances")
    bal_mandal = relationship("BalMandal", back_populates="attendances")
