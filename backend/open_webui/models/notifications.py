"""Notification model for user notification inbox."""

from __future__ import annotations

import time
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Text

from open_webui.internal.db import Base


class Notification(Base):
    __tablename__ = 'notification'

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=False, index=True)
    type = Column(Text, nullable=False)  # 'comment', 'mention', 'reply', 'system', 'automation'
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=True)
    data = Column(JSON, nullable=True)  # Additional context (chat_id, message_id, etc.)
    read = Column(BigInteger, default=0)  # 0 = unread, 1 = read
    created_at = Column(BigInteger, nullable=False, default=lambda: int(time.time()))

    def model_dump(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'type': self.type,
            'title': self.title,
            'content': self.content,
            'data': self.data or {},
            'read': bool(self.read),
            'created_at': self.created_at,
        }


class NotificationForm(BaseModel):
    type: str
    title: str
    content: Optional[str] = None
    data: Optional[dict[str, Any]] = None


class NotificationResponse(BaseModel):
    id: str
    user_id: str
    type: str
    title: str
    content: Optional[str] = None
    data: dict[str, Any] = {}
    read: bool = False
    created_at: int

    model_config = ConfigDict(from_attributes=True)
