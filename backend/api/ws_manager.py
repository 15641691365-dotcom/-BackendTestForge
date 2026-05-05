"""
WebSocket manager for real-time task progress updates.
Fallback: client can also poll GET /api/tasks/{id}.
"""

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Manages WebSocket connections per task_id.
    Supports multiple clients connected to the same task.
    """

    def __init__(self):
        self._connections: dict[int, list[WebSocket]] = {}

    async def connect(self, task_id: int, websocket: WebSocket):
        """Accept and register a WebSocket connection for a task."""
        await websocket.accept()
        if task_id not in self._connections:
            self._connections[task_id] = []
        self._connections[task_id].append(websocket)
        logger.info(f"WebSocket connected: task={task_id} total={len(self._connections[task_id])}")

    def disconnect(self, task_id: int, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if task_id in self._connections:
            self._connections[task_id] = [
                ws for ws in self._connections[task_id] if ws != websocket
            ]
            if not self._connections[task_id]:
                del self._connections[task_id]

    async def broadcast(self, task_id: int, message: dict[str, Any]):
        """Send a message to all connections for a task."""
        if task_id not in self._connections:
            return
        disconnected = []
        for ws in self._connections[task_id]:
            try:
                await ws.send_json(message)
            except WebSocketDisconnect:
                disconnected.append(ws)
            except Exception as e:
                logger.warning(f"WebSocket send error task={task_id}: {e}")
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(task_id, ws)

    async def send_agent_event(self, task_id: int, agent: str, event_type: str, **kwargs):
        """
        Send a structured agent event to all connected clients.

        Event types: agent_start, agent_progress, agent_done, agent_failed, task_done
        """
        message = {
            "type": event_type,
            "agent": agent,
            "task_id": task_id,
            **kwargs,
        }
        await self.broadcast(task_id, message)

    async def send_task_done(self, task_id: int, status: str, report_id: int | None = None):
        """Signal that the entire task has completed."""
        await self.send_agent_event(
            task_id, "orchestrator", "task_done",
            status=status,
            report_id=report_id,
        )


# Singleton instance
ws_manager = WebSocketManager()
