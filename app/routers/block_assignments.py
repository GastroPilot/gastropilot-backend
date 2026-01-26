from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Block, BlockAssignment, Restaurant, Table, User
from app.dependencies import get_session, require_mitarbeiter_role
from app.schemas import BlockAssignmentCreate, BlockAssignmentRead

router = APIRouter(
    prefix="/restaurants/{restaurant_id}/block-assignments", tags=["block_assignments"]
)


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_block_or_404(block_id: int, restaurant_id: int, session: AsyncSession) -> Block:
    blk = await session.get(Block, block_id)
    if not blk or blk.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Block not found")
    return blk


@router.post("/", response_model=BlockAssignmentRead, status_code=status.HTTP_201_CREATED)
async def create_block_assignment(
    restaurant_id: int,
    body: BlockAssignmentCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    blk = await _get_block_or_404(body.block_id, restaurant_id, session)

    table = await session.get(Table, body.table_id)
    if not table or table.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")

    assignment = BlockAssignment(
        block_id=blk.id,
        table_id=body.table_id,
    )
    session.add(assignment)

    try:
        await session.commit()
        await session.refresh(assignment)
        return assignment
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Block assignment conflict"
        )


@router.get("/", response_model=list[BlockAssignmentRead])
async def list_block_assignments(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    result = await session.execute(
        select(BlockAssignment)
        .join(Block, Block.id == BlockAssignment.block_id)
        .where(Block.restaurant_id == restaurant_id)
    )
    return result.scalars().all()


@router.get("/by-block/{block_id}", response_model=list[BlockAssignmentRead])
async def list_block_assignments_by_block(
    restaurant_id: int,
    block_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    await _get_block_or_404(block_id, restaurant_id, session)
    result = await session.execute(
        select(BlockAssignment).where(BlockAssignment.block_id == block_id)
    )
    return result.scalars().all()


@router.get("/by-table/{table_id}", response_model=list[BlockAssignmentRead])
async def list_block_assignments_by_table(
    restaurant_id: int,
    table_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    table = await session.get(Table, table_id)
    if not table or table.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")

    result = await session.execute(
        select(BlockAssignment)
        .join(Block, Block.id == BlockAssignment.block_id)
        .where(
            Block.restaurant_id == restaurant_id,
            BlockAssignment.table_id == table_id,
        )
    )
    return result.scalars().all()


@router.delete("/{assignment_id}", status_code=status.HTTP_200_OK)
async def delete_block_assignment(
    restaurant_id: int,
    assignment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    assignment = await session.get(BlockAssignment, assignment_id)
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Block assignment not found"
        )

    blk = await session.get(Block, assignment.block_id)
    if not blk or blk.restaurant_id != restaurant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Block assignment not found"
        )

    await session.delete(assignment)
    try:
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise
    return {"message": "deleted"}
