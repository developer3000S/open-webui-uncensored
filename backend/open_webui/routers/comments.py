"""Comment API endpoints for threaded comments."""

from __future__ import annotations

import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from open_webui.internal.db import get_async_session
from open_webui.models.comments import Comment, CommentForm, CommentResponse
from open_webui.utils.auth import get_verified_user

router = APIRouter()


class CommentListResponse(BaseModel):
    comments: list[CommentResponse]


@router.get('/api/v1/comments', response_model=CommentListResponse)
async def list_comments(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
    object_type: Optional[str] = None,
    object_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    limit: int = 100,
):
    """List comments for an object or thread."""
    query = select(Comment)

    if object_type:
        query = query.where(Comment.object_type == object_type)
    if object_id:
        query = query.where(Comment.object_id == object_id)
    if parent_id is not None:
        query = query.where(Comment.parent_id == parent_id)

    query = query.order_by(Comment.created_at.asc()).limit(limit)

    result = await db.execute(query)
    comments = result.scalars().all()

    return {'comments': [c.model_dump() for c in comments]}


@router.post('/api/v1/comments', response_model=CommentResponse)
async def create_comment(
    request: Request,
    form: CommentForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Create a new comment."""
    comment = Comment(
        id=str(uuid.uuid4()),
        user_id=user.id,
        object_type=form.object_type,
        object_id=form.object_id,
        parent_id=form.parent_id,
        message_id=form.message_id,
        content=form.content,
        data=form.data or {},
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )

    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    return comment.model_dump()


@router.get('/api/v1/comments/{comment_id}', response_model=CommentResponse)
async def get_comment(
    comment_id: str,
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a single comment by ID."""
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalar_one_or_none()

    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Comment not found',
        )

    return comment.model_dump()


@router.patch('/api/v1/comments/{comment_id}', response_model=CommentResponse)
async def update_comment(
    comment_id: str,
    request: Request,
    form: CommentForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Update an existing comment (owner only)."""
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalar_one_or_none()

    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Comment not found',
        )

    if comment.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Not authorized to edit this comment',
        )

    comment.content = form.content
    comment.data = form.data or {}
    comment.updated_at = int(time.time())

    await db.commit()
    await db.refresh(comment)

    return comment.model_dump()


@router.delete('/api/v1/comments/{comment_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: str,
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Delete a comment (owner or admin only)."""
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalar_one_or_none()

    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Comment not found',
        )

    if comment.user_id != user.id and user.role != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Not authorized to delete this comment',
        )

    # Delete all replies first
    await db.execute(Comment.__table__.delete().where(Comment.parent_id == comment_id))

    await db.execute(Comment.__table__.delete().where(Comment.id == comment_id))
    await db.commit()
