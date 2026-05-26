from __future__ import annotations

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Patient(Base):
    __tablename__ = "patient"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    status = Column(String, nullable=True)
    deleted_at = Column(String, nullable=True)
