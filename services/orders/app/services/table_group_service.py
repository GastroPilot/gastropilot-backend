from __future__ import annotations

import uuid
from datetime import UTC, date as date_type, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _deduplicate_table_ids(table_ids: list[UUID]) -> list[UUID]:
    deduped: list[UUID] = []
    seen: set[UUID] = set()
    for table_id in table_ids:
        if table_id in seen:
            continue
        seen.add(table_id)
        deduped.append(table_id)
    return deduped


def normalize_order_table_ids(raw_table_ids: Any, table_id: UUID | None) -> list[str]:
    if isinstance(raw_table_ids, list):
        normalized = [str(value) for value in raw_table_ids if value]
        if normalized:
            return normalized
    if table_id is not None:
        return [str(table_id)]
    return []


async def resolve_group_table_ids(
    session: AsyncSession,
    tenant_id: UUID | str,
    table_id: UUID,
    reference_date: date_type | None = None,
) -> list[UUID]:
    tenant_id_str = str(tenant_id)
    target_date = reference_date or datetime.now(UTC).date()

    table_result = await session.execute(
        text("""
            SELECT id, join_group_id
            FROM tables
            WHERE id = :table_id
              AND tenant_id = :tenant_id
            LIMIT 1
            """),
        {"table_id": str(table_id), "tenant_id": tenant_id_str},
    )
    table_row = table_result.first()
    if table_row is None:
        raise ValueError("Table not found")

    configured_group_result = await session.execute(
        text("""
            SELECT join_group_id
            FROM table_day_configs
            WHERE tenant_id = :tenant_id
              AND table_id = :table_id
              AND date = :target_date
            LIMIT 1
            """),
        {
            "tenant_id": tenant_id_str,
            "table_id": str(table_id),
            "target_date": target_date,
        },
    )
    configured_group_row = configured_group_result.first()
    configured_group_id = (
        configured_group_row.join_group_id if configured_group_row is not None else None
    )
    effective_group_id = (
        configured_group_id if configured_group_id is not None else table_row.join_group_id
    )
    if effective_group_id is None:
        return [table_id]

    day_group_result = await session.execute(
        text("""
            SELECT table_id
            FROM table_day_configs
            WHERE tenant_id = :tenant_id
              AND date = :target_date
              AND join_group_id = :join_group_id
              AND table_id IS NOT NULL
              AND is_hidden = FALSE
              AND (is_active IS NULL OR is_active = TRUE)
            """),
        {
            "tenant_id": tenant_id_str,
            "target_date": target_date,
            "join_group_id": effective_group_id,
        },
    )
    day_group_table_ids = [
        uuid.UUID(str(row.table_id)) for row in day_group_result if row.table_id is not None
    ]
    if day_group_table_ids:
        return _deduplicate_table_ids([table_id, *day_group_table_ids])

    permanent_group_result = await session.execute(
        text("""
            SELECT id
            FROM tables
            WHERE tenant_id = :tenant_id
              AND join_group_id = :join_group_id
              AND is_active = TRUE
            """),
        {"tenant_id": tenant_id_str, "join_group_id": effective_group_id},
    )
    permanent_group_table_ids = [uuid.UUID(str(row.id)) for row in permanent_group_result]
    if not permanent_group_table_ids:
        return [table_id]

    return _deduplicate_table_ids([table_id, *permanent_group_table_ids])
