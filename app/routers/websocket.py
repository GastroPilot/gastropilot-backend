"""
WebSocket endpoints for real-time updates.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from typing import Optional
import json
import logging
import asyncio
from datetime import datetime, timezone

from app.auth import verify_token

router = APIRouter(prefix="/ws", tags=["websocket"])
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""
    
    def __init__(self):
        # Structure: {restaurant_id: {user_id: WebSocket}}
        self.active_connections: dict[int, dict[int, WebSocket]] = {}
        # Track which channels each connection is subscribed to
        self.subscriptions: dict[int, dict[int, set[str]]] = {}
    
    async def connect(self, websocket: WebSocket, restaurant_id: int, user_id: int):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        
        if restaurant_id not in self.active_connections:
            self.active_connections[restaurant_id] = {}
            self.subscriptions[restaurant_id] = {}
        
        self.active_connections[restaurant_id][user_id] = websocket
        self.subscriptions[restaurant_id][user_id] = set()
        
        logger.info(f"WebSocket connected: restaurant={restaurant_id}, user={user_id}")
    
    def disconnect(self, restaurant_id: int, user_id: int):
        """Remove a WebSocket connection."""
        if restaurant_id in self.active_connections:
            if user_id in self.active_connections[restaurant_id]:
                del self.active_connections[restaurant_id][user_id]
                del self.subscriptions[restaurant_id][user_id]
                logger.info(f"WebSocket disconnected: restaurant={restaurant_id}, user={user_id}")
            
            # Clean up empty restaurant entries
            if not self.active_connections[restaurant_id]:
                del self.active_connections[restaurant_id]
                del self.subscriptions[restaurant_id]
    
    def subscribe(self, restaurant_id: int, user_id: int, channel: str):
        """Subscribe a connection to a specific channel."""
        if restaurant_id in self.subscriptions and user_id in self.subscriptions[restaurant_id]:
            self.subscriptions[restaurant_id][user_id].add(channel)
            logger.debug(f"Subscribed: restaurant={restaurant_id}, user={user_id}, channel={channel}")
    
    def unsubscribe(self, restaurant_id: int, user_id: int, channel: str):
        """Unsubscribe a connection from a specific channel."""
        if restaurant_id in self.subscriptions and user_id in self.subscriptions[restaurant_id]:
            self.subscriptions[restaurant_id][user_id].discard(channel)
    
    async def send_personal_message(self, message: dict, restaurant_id: int, user_id: int):
        """Send a message to a specific user."""
        if restaurant_id in self.active_connections:
            if user_id in self.active_connections[restaurant_id]:
                try:
                    await self.active_connections[restaurant_id][user_id].send_json(message)
                except Exception as e:
                    logger.error(f"Error sending personal message: {e}")
    
    async def broadcast_to_restaurant(self, message: dict, restaurant_id: int, channel: Optional[str] = None):
        """Broadcast a message to all users of a restaurant, optionally filtered by channel."""
        if restaurant_id not in self.active_connections:
            return
        
        disconnected = []
        
        for user_id, websocket in self.active_connections[restaurant_id].items():
            # If channel specified, only send to subscribers
            if channel:
                if user_id not in self.subscriptions.get(restaurant_id, {}):
                    continue
                if channel not in self.subscriptions[restaurant_id][user_id]:
                    continue
            
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to user {user_id}: {e}")
                disconnected.append(user_id)
        
        # Clean up disconnected users
        for user_id in disconnected:
            self.disconnect(restaurant_id, user_id)
    
    def get_connection_count(self, restaurant_id: int) -> int:
        """Get the number of active connections for a restaurant."""
        return len(self.active_connections.get(restaurant_id, {}))


# Singleton connection manager
manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    """Dependency to get the connection manager."""
    return manager


@router.websocket("/{restaurant_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    restaurant_id: int,
    token: str = Query(...),
):
    """
    WebSocket endpoint for real-time updates.
    
    Connect with: ws://host/ws/{restaurant_id}?token={access_token}
    
    Message types:
    - subscribe: Subscribe to a channel (orders, reservations, tables, kitchen)
    - unsubscribe: Unsubscribe from a channel
    - ping: Keep-alive ping
    
    Server sends:
    - order_created, order_updated, order_deleted
    - reservation_created, reservation_updated, reservation_deleted
    - table_updated
    - kitchen_order_update
    - pong (response to ping)
    """
    # Verify token
    payload = verify_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    user_id = payload.get("user_id") or payload.get("sub")
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token payload")
        return
    
    user_id = int(user_id)
    
    await manager.connect(websocket, restaurant_id, user_id)
    
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=60.0)
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    await websocket.send_json({"type": "ping"})
                except:
                    break
                continue
            
            message_type = data.get("type")
            
            if message_type == "subscribe":
                channel = data.get("channel")
                if channel in ["orders", "reservations", "tables", "kitchen", "all"]:
                    manager.subscribe(restaurant_id, user_id, channel)
                    await websocket.send_json({
                        "type": "subscribed",
                        "channel": channel,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
            
            elif message_type == "unsubscribe":
                channel = data.get("channel")
                if channel:
                    manager.unsubscribe(restaurant_id, user_id, channel)
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "channel": channel,
                    })
            
            elif message_type == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            
            elif message_type == "get_connections":
                # Admin feature: get connection count
                count = manager.get_connection_count(restaurant_id)
                await websocket.send_json({
                    "type": "connection_count",
                    "count": count,
                })
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: restaurant={restaurant_id}, user={user_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        manager.disconnect(restaurant_id, user_id)


# Helper functions for broadcasting events from other parts of the application

async def broadcast_order_event(restaurant_id: int, event_type: str, order_data: dict):
    """Broadcast an order event to all subscribed clients."""
    message = {
        "type": event_type,
        "channel": "orders",
        "data": order_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await manager.broadcast_to_restaurant(message, restaurant_id, channel="orders")
    await manager.broadcast_to_restaurant(message, restaurant_id, channel="all")
    # Also send to kitchen channel for relevant events
    if event_type in ["order_created", "order_updated"]:
        message["channel"] = "kitchen"
        await manager.broadcast_to_restaurant(message, restaurant_id, channel="kitchen")


async def broadcast_reservation_event(restaurant_id: int, event_type: str, reservation_data: dict):
    """Broadcast a reservation event to all subscribed clients."""
    message = {
        "type": event_type,
        "channel": "reservations",
        "data": reservation_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await manager.broadcast_to_restaurant(message, restaurant_id, channel="reservations")
    await manager.broadcast_to_restaurant(message, restaurant_id, channel="all")


async def broadcast_table_event(restaurant_id: int, event_type: str, table_data: dict):
    """Broadcast a table event to all subscribed clients."""
    message = {
        "type": event_type,
        "channel": "tables",
        "data": table_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await manager.broadcast_to_restaurant(message, restaurant_id, channel="tables")
    await manager.broadcast_to_restaurant(message, restaurant_id, channel="all")
