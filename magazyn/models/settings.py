"""Modele ustawien i kosztow stalych."""

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text, func

from .base import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class FixedCost(Base):
    """Koszt staly odejmowany od miesiecznego wyniku."""

    __tablename__ = "fixed_costs"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<FixedCost {self.name}: {self.amount} PLN>"


__all__ = ["AppSetting", "FixedCost"]
