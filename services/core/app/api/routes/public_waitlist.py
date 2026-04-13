"""Public waitlist live tracking endpoints."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.waitlist import Waitlist

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/waitlist", tags=["public-waitlist"])


@router.get("/{token}")
async def get_waitlist_position(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Get waitlist position and estimated wait time."""
    result = await db.execute(select(Waitlist).where(Waitlist.tracking_token == token))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(
            status_code=404,
            detail="Waitlist entry not found",
        )

    if entry.status != "waiting":
        return {
            "status": entry.status,
            "position": 0,
            "estimated_wait_minutes": 0,
            "party_size": entry.party_size,
        }

    # Count entries ahead of this one
    ahead_result = await db.execute(
        select(func.count(Waitlist.id)).where(
            and_(
                Waitlist.tenant_id == entry.tenant_id,
                Waitlist.status == "waiting",
                Waitlist.created_at < entry.created_at,
            )
        )
    )
    position = (ahead_result.scalar() or 0) + 1

    # Rough estimate: 15 minutes per party ahead
    estimated_wait = position * 15

    return {
        "status": entry.status,
        "position": position,
        "estimated_wait_minutes": estimated_wait,
        "party_size": entry.party_size,
    }


@router.get("/{token}/stream")
async def waitlist_position_stream(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint for live waitlist position updates."""
    # Validate token exists
    result = await db.execute(select(Waitlist).where(Waitlist.tracking_token == token))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(
            status_code=404,
            detail="Waitlist entry not found",
        )

    async def event_generator():
        """Generate SSE events for position updates."""
        while True:
            try:
                # Re-query to get fresh data
                from app.core.database import (
                    get_session_factories,
                )

                factory, _ = get_session_factories()
                async with factory() as session:
                    res = await session.execute(
                        select(Waitlist).where(Waitlist.tracking_token == token)
                    )
                    current = res.scalar_one_or_none()

                    if not current:
                        yield ('data: {"status": "removed"}\n\n')
                        break

                    if current.status != "waiting":
                        yield (f'data: {{"status": "{current.status}", "position": 0}}\n\n')
                        break

                    ahead = await session.execute(
                        select(func.count(Waitlist.id)).where(
                            and_(
                                Waitlist.tenant_id == current.tenant_id,
                                Waitlist.status == "waiting",
                                Waitlist.created_at < current.created_at,
                            )
                        )
                    )
                    position = (ahead.scalar() or 0) + 1
                    wait_min = position * 15

                    yield (
                        f"data: "
                        f'{{"status": "waiting",'
                        f' "position": {position},'
                        f' "estimated_wait_minutes":'
                        f" {wait_min}}}\n\n"
                    )

                await asyncio.sleep(10)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in waitlist SSE stream")
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
