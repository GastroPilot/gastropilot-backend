from __future__ import annotations
import json
import logging
from collections import defaultdict
from typing import Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket connection manager with tenant-scoped rooms."""

    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, tenant_id: str) -> None:
        await websocket.accept()
        self._connections[tenant_id].add(websocket)
        logger.info(f"WebSocket connected: tenant={tenant_id}, total={len(self._connections[tenant_id])}")

    def disconnect(self, websocket: WebSocket, tenant_id: str) -> None:
        self._connections[tenant_id].discard(websocket)
        if not self._connections[tenant_id]:
            del self._connections[tenant_id]

    async def broadcast_to_tenant(self, tenant_id: str, message: dict[str, Any]) -> None:
        connections = list(self._connections.get(tenant_id, set()))
        if not connections:
            return
        payload = json.dumps(message)
        disconnected = []
        for ws in connections:
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws, tenant_id)

    async def send_personal(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        await websocket.send_text(json.dumps(message))

    def get_tenant_connection_count(self, tenant_id: str) -> int:
        return len(self._connections.get(tenant_id, set()))


manager = ConnectionManager()
