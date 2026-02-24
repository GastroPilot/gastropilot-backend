from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_staff_or_above
from app.models.block import Block, BlockAssignment
from app.models.user import User

router = APIRouter(prefix="/blocks", tags=["blocks"])


# --- Schemas ---

class BlockCreate(BaseModel):
    start_at: datetime
    end_at: datetime
    reason: str | None = None

class BlockUpdate(BaseModel):
    start_at: datetime | None = None
    end_at: datetime | None = None
    reason: str | None = None

class BlockResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    start_at: datetime
    end_at: datetime
    reason: str | None = None
    created_by_user_id: UUID | None = None
    model_config = {"from_attributes": True}

class BlockAssignmentCreate(BaseModel):
    block_id: UUID
    table_id: UUID

class BlockAssignmentResponse(BaseModel):
    id: UUID
    block_id: UUID
    table_id: UUID
    tenant_id: UUID
    created_at: datetime
    model_config = {"from_attributes": True}


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# --- Block CRUD ---

@router.post("/", response_model=BlockResponse, status_code=status.HTTP_201_CREATED)
async def create_block(
    request: Request,
    body: BlockCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
    start = _normalize_utc(body.start_at)
    end = _normalize_utc(body.end_at)
    if end <= start:
        raise HTTPException(status_code=400, detail="end_at must be after start_at")

    block = Block(
        tenant_id=effective_tenant_id,
        start_at=start,
        end_at=end,
        reason=body.reason,
        created_by_user_id=current_user.id,
    )
    db.add(block)
    try:
        await db.commit()
        await db.refresh(block)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Block conflict")
    return block


@router.get("/", response_model=list[BlockResponse])
async def list_blocks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Block).order_by(Block.start_at))
    return result.scalars().all()


@router.patch("/{block_id}", response_model=BlockResponse)
async def update_block(
    block_id: UUID,
    body: BlockUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Block).where(Block.id == block_id))
    block = result.scalar_one_or_none()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")

    if body.start_at is not None:
        block.start_at = _normalize_utc(body.start_at)
    if body.end_at is not None:
        block.end_at = _normalize_utc(body.end_at)
    if body.reason is not None:
        block.reason = body.reason

    if block.end_at <= block.start_at:
        raise HTTPException(status_code=400, detail="end_at must be after start_at")

    await db.commit()
    await db.refresh(block)
    return block


@router.delete("/{block_id}")
async def delete_block(
    block_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Block).where(Block.id == block_id))
    block = result.scalar_one_or_none()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")
    await db.delete(block)
    await db.commit()
    return {"message": "deleted"}


# --- Block Assignment CRUD ---

@router.post("/assignments", response_model=BlockAssignmentResponse, status_code=status.HTTP_201_CREATED)
async def create_block_assignment(
    request: Request,
    body: BlockAssignmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id

    # Validate block exists
    block_result = await db.execute(select(Block).where(Block.id == body.block_id))
    if not block_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Block not found")

    assignment = BlockAssignment(
        block_id=body.block_id,
        table_id=body.table_id,
        tenant_id=effective_tenant_id,
    )
    db.add(assignment)
    try:
        await db.commit()
        await db.refresh(assignment)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Assignment already exists")
    return assignment


@router.get("/assignments", response_model=list[BlockAssignmentResponse])
async def list_block_assignments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(BlockAssignment))
    return result.scalars().all()


@router.get("/assignments/by-block/{block_id}", response_model=list[BlockAssignmentResponse])
async def list_assignments_by_block(
    block_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(
        select(BlockAssignment).where(BlockAssignment.block_id == block_id)
    )
    return result.scalars().all()


@router.get("/assignments/by-table/{table_id}", response_model=list[BlockAssignmentResponse])
async def list_assignments_by_table(
    table_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(
        select(BlockAssignment).where(BlockAssignment.table_id == table_id)
    )
    return result.scalars().all()


@router.delete("/assignments/{assignment_id}")
async def delete_block_assignment(
    assignment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(BlockAssignment).where(BlockAssignment.id == assignment_id))
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await db.delete(assignment)
    await db.commit()
    return {"message": "deleted"}
