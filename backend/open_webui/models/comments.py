"""Comment model for threaded comments on chats, notes, models, and other objects."""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Text

from open_webui.internal.db import Base


class Comment(Base):
    __tablename__ = 'comment'

    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Text, nullable=False, index=True)
    object_type = Column(
        Text, nullable=False, index=True
    )  # 'chat', 'note', 'model', 'prompt', 'skill', 'tool', 'knowledge'
    object_id = Column(Text, nullable=False, index=True)
    parent_id = Column(Text, nullable=True, index=True)  # For threaded replies
    message_id = Column(Text, nullable=True, index=True)  # Chat message ID if applicable
    content = Column(Text, nullable=False)
    data = Column(JSON, nullable=True)  # Additional context (selection, position, etc.)
    created_at = Column(BigInteger, nullable=False, default=lambda: int(time.time()))
    updated_at = Column(BigInteger, nullable=False, default=lambda: int(time.time()))

    def model_dump(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'object_type': self.object_type,
            'object_id': self.object_id,
            'parent_id': self.parent_id,
            'message_id': self.message_id,
            'content': self.content,
            'data': self.data or {},
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


class CommentForm(BaseModel):
    object_type: str
    object_id: str
    parent_id: Optional[str] = None
    message_id: Optional[str] = None
    content: str
    data: Optional[dict[str, Any]] = None


class CommentResponse(BaseModel):
    id: str
    user_id: str
    object_type: str
    object_id: str
    parent_id: Optional[str]
    message_id: Optional[str]
    content: str
    data: dict[str, Any] = {}
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)
