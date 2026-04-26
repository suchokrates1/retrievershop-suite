"""Wspolna baza deklaratywna SQLAlchemy."""

from sqlalchemy.orm import declarative_base

Base = declarative_base()

__all__ = ["Base"]
