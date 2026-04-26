"""Modele watkow i wiadomosci Allegro."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import relationship

from .base import Base


class Thread(Base):
    __tablename__ = "threads"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    author = Column(String, nullable=False)
    last_message_at = Column(DateTime, nullable=False, server_default=func.now())
    type = Column(String, nullable=False)
    read = Column(Boolean, default=False, nullable=False)
    messages = relationship("Message", back_populates="thread", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True)
    thread_id = Column(String, ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    author = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    thread = relationship("Thread", back_populates="messages")


__all__ = ["Message", "Thread"]
