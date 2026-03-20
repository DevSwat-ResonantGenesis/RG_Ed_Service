"""WebSocket connection manager for real-time updates."""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from fastapi import WebSocket, WebSocketDisconnect

from ..config import settings


@dataclass
class Connection:
    """A WebSocket connection."""
    websocket: WebSocket
    user_id: Optional[str] = None
    subscriptions: Set[str] = field(default_factory=set)
    connected_at: datetime = field(default_factory=datetime.utcnow)


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.connections: Dict[str, Connection] = {}
        self.channel_subscribers: Dict[str, Set[str]] = {}
        self.max_connections = settings.WS_MAX_CONNECTIONS
        self.ping_interval = settings.WS_PING_INTERVAL

    async def connect(
        self,
        websocket: WebSocket,
        connection_id: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """Accept a new WebSocket connection."""
        if len(self.connections) >= self.max_connections:
            await websocket.close(code=1013, reason="Max connections reached")
            return False

        await websocket.accept()
        
        self.connections[connection_id] = Connection(
            websocket=websocket,
            user_id=user_id,
        )

        # Send welcome message
        await self.send_to_connection(connection_id, {
            "type": "connected",
            "connection_id": connection_id,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return True

    async def disconnect(self, connection_id: str):
        """Handle disconnection."""
        if connection_id in self.connections:
            conn = self.connections[connection_id]
            
            # Unsubscribe from all channels
            for channel in list(conn.subscriptions):
                await self.unsubscribe(connection_id, channel)

            del self.connections[connection_id]

    async def subscribe(self, connection_id: str, channel: str) -> bool:
        """Subscribe a connection to a channel."""
        if connection_id not in self.connections:
            return False

        conn = self.connections[connection_id]
        conn.subscriptions.add(channel)

        if channel not in self.channel_subscribers:
            self.channel_subscribers[channel] = set()
        self.channel_subscribers[channel].add(connection_id)

        await self.send_to_connection(connection_id, {
            "type": "subscribed",
            "channel": channel,
        })

        return True

    async def unsubscribe(self, connection_id: str, channel: str) -> bool:
        """Unsubscribe a connection from a channel."""
        if connection_id not in self.connections:
            return False

        conn = self.connections[connection_id]
        conn.subscriptions.discard(channel)

        if channel in self.channel_subscribers:
            self.channel_subscribers[channel].discard(connection_id)
            if not self.channel_subscribers[channel]:
                del self.channel_subscribers[channel]

        return True

    async def send_to_connection(
        self, connection_id: str, message: Dict[str, Any]
    ) -> bool:
        """Send a message to a specific connection."""
        if connection_id not in self.connections:
            return False

        conn = self.connections[connection_id]
        try:
            await conn.websocket.send_json(message)
            return True
        except Exception:
            # Connection might be closed
            await self.disconnect(connection_id)
            return False

    async def broadcast_to_channel(
        self, channel: str, message: Dict[str, Any]
    ):
        """Broadcast a message to all subscribers of a channel."""
        subscribers = self.channel_subscribers.get(channel, set())
        
        for connection_id in list(subscribers):
            await self.send_to_connection(connection_id, {
                **message,
                "channel": channel,
            })

    async def broadcast_to_user(
        self, user_id: str, message: Dict[str, Any]
    ):
        """Broadcast a message to all connections of a user."""
        for connection_id, conn in list(self.connections.items()):
            if conn.user_id == user_id:
                await self.send_to_connection(connection_id, message)

    async def broadcast_all(self, message: Dict[str, Any]):
        """Broadcast a message to all connections."""
        for connection_id in list(self.connections.keys()):
            await self.send_to_connection(connection_id, message)

    async def handle_message(
        self, connection_id: str, message: Dict[str, Any]
    ):
        """Handle an incoming message from a connection."""
        msg_type = message.get("type")

        if msg_type == "subscribe":
            channel = message.get("channel")
            if channel:
                await self.subscribe(connection_id, channel)

        elif msg_type == "unsubscribe":
            channel = message.get("channel")
            if channel:
                await self.unsubscribe(connection_id, channel)

        elif msg_type == "ping":
            await self.send_to_connection(connection_id, {"type": "pong"})

    def get_connection_count(self) -> int:
        """Get total number of connections."""
        return len(self.connections)

    def get_channel_subscribers(self, channel: str) -> int:
        """Get number of subscribers for a channel."""
        return len(self.channel_subscribers.get(channel, set()))

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        return {
            "total_connections": len(self.connections),
            "channels": {
                channel: len(subs)
                for channel, subs in self.channel_subscribers.items()
            },
        }


ws_manager = ConnectionManager()


# Channel name helpers
def execution_channel(session_id: str) -> str:
    """Get channel name for execution session logs."""
    return f"execution:{session_id}"


def agent_channel(agent_id: str) -> str:
    """Get channel name for agent updates."""
    return f"agent:{agent_id}"


def workspace_channel(workspace_id: str) -> str:
    """Get channel name for workspace file changes."""
    return f"workspace:{workspace_id}"


def user_channel(user_id: str) -> str:
    """Get channel name for user notifications."""
    return f"user:{user_id}"
