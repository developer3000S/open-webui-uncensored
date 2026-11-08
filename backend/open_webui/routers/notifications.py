"""Notification inbox API endpoints."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from open_webui.internal.db import get_async_session
from open_webui.models.notifications import Notification, NotificationForm, NotificationResponse
from open_webui.utils.auth import get_verified_user

router = APIRouter()


class MarkReadForm(BaseModel):
    notification_id: str


class MarkAllReadForm(BaseModel):
    pass


@router.get('/api/v1/notifications', response_model=list[NotificationResponse])
async def get_notifications(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
    unread_only: bool = False,
    limit: int = 50,
):
    """Get notifications for the current user."""
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read == 0)
    query = query.order_by(Notification.created_at.desc()).limit(limit)

    result = await db.execute(query)
    notifications = result.scalars().all()

    return [n.model_dump() for n in notifications]


@router.get('/api/v1/notifications/unread-count', response_model=dict[str, int])
async def get_unread_count(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get count of unread notifications."""
    result = await db.execute(select(Notification).where(Notification.user_id == user.id, Notification.read == 0))
    count = len(result.scalars().all())
    return {'count': count}


@router.post('/api/v1/notifications', response_model=NotificationResponse)
async def create_notification(
    request: Request,
    form: NotificationForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Create a new notification (admin/system only)."""
    notification_id = str(uuid.uuid4())

    notification = Notification(
        id=notification_id,
        user_id=user.id,
        type=form.type,
        title=form.title,
        content=form.content,
        data=form.data or {},
        read=0,
        created_at=int(time.time()),
    )

    db.add(notification)
    await db.commit()
    await db.refresh(notification)

    return notification.model_dump()


@router.post('/api/v1/notifications/mark-read')
async def mark_notification_read(
    request: Request,
    form: MarkReadForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Mark a notification as read."""
    result = await db.execute(
        select(Notification).where(
            Notification.id == form.notification_id,
            Notification.user_id == user.id,
        )
    )
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Notification not found',
        )

    notification.read = 1
    await db.commit()

    return {'status': 'ok'}


@router.post('/api/v1/notifications/mark-all-read')
async def mark_all_notifications_read(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Mark all notifications as read."""
    await db.execute(
        Notification.__table__.update().where(Notification.user_id == user.id, Notification.read == 0).values(read=1)
    )
    await db.commit()

    return {'status': 'ok'}
