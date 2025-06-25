# Copyright (C) 2025 Bunting Labs, Inc.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import asyncio
import json
import logging
import os
import time
import traceback
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

import asyncpg
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends

from src.dependencies.session import UserContext, verify_websocket
from src.structures import get_async_db_connection

logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# Subscriber registry for WebSocket notifications by map_id
subscribers_by_map = defaultdict(set)
subscribers_lock = asyncio.Lock()

# Track recently disconnected users and their missed messages per map
# (user_id, map_id) -> {"disconnect_time": float, "missed_messages": deque[(timestamp, payload)]}
recently_disconnected_users: Dict[Tuple[str, str], Dict[str, Any]] = {}
DISCONNECT_TTL = 30.0  # Keep disconnected user data for 30 seconds
MAX_MISSED_MESSAGES = 100  # Limit buffer size per user per map

CHAT_CH = "chat_completion_messages_notify"
chat_q: asyncio.Queue[str] = asyncio.Queue()
# Initialize listener task at module level
listener_task = None


def start_chat_listener():
    global listener_task

    if listener_task is None or listener_task.done():
        user = os.environ["POSTGRES_USER"]
        password = os.environ["POSTGRES_PASSWORD"]
        host = os.environ["POSTGRES_HOST"]
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ["POSTGRES_DB"]
        dsn = f"postgresql://{user}:{password}@{host}:{port}/{db}"
        listener_task = asyncio.create_task(_chat_pg_listener(dsn=dsn))

    return listener_task


@router.on_event("startup")
async def startup_listener():
    start_chat_listener()
    # Start cleanup task for recently disconnected users
    asyncio.create_task(cleanup_recently_disconnected_users())


async def _chat_pg_listener(dsn: str):
    try:
        conn = await asyncpg.connect(dsn)

        await conn.add_listener(
            CHAT_CH,
            lambda _conn, _pid, _channel, payload: asyncio.create_task(
                _broadcast_payload(payload)
            ),
        )

        while True:
            await asyncio.sleep(3600)
    except Exception:
        traceback.print_exc()
    finally:
        try:
            await conn.close()
        except Exception:
            pass


async def cleanup_recently_disconnected_users():
    """Periodically clean up expired disconnected users"""
    while True:
        try:
            await asyncio.sleep(60)  # Run cleanup every minute
            now = time.time()

            # Clean up users who disconnected too long ago
            users_to_remove = []
            for (user_id, map_id), user_data in recently_disconnected_users.items():
                if now - user_data["disconnect_time"] > DISCONNECT_TTL:
                    users_to_remove.append((user_id, map_id))

            # Remove expired users
            for user_key in users_to_remove:
                del recently_disconnected_users[user_key]

        except Exception:
            logger.exception("Error in cleanup_recently_disconnected_users")


@router.websocket("/ws/{map_id}/messages/updates")
async def ws_map_chat(
    ws: WebSocket, map_id: str, user_context: UserContext = Depends(verify_websocket)
):
    # In edit mode, we don't require tokens for WebSocket connections
    auth_mode = os.environ.get("MUNDI_AUTH_MODE")
    token = ws.query_params.get("token")

    if not token and auth_mode != "edit":
        await ws.close(code=4401, reason="No token")
        return

    user_id = user_context.get_user_id()

    # Check if user owns the map (skip in edit mode since all maps are accessible)
    async with get_async_db_connection() as conn:
        map_result = await conn.fetchrow(
            """
            SELECT owner_uuid FROM user_mundiai_maps
            WHERE id = $1 AND soft_deleted_at IS NULL
            """,
            map_id,
        )

        # Only enforce ownership when running in view_only or production mode
        if not map_result or str(map_result["owner_uuid"]) != user_id:
            await ws.close(code=4403, reason="Unauthorized")
            return

    await ws.accept()
    queue = asyncio.Queue()
    async with subscribers_lock:
        subscribers_by_map[map_id].add(queue)

    # Check if this user recently disconnected from this specific map and replay their missed messages
    user_map_key = (user_id, map_id)
    if user_map_key in recently_disconnected_users:
        user_data = recently_disconnected_users[user_map_key]
        missed_messages = user_data["missed_messages"]

        # Replay all missed messages for this specific user on this specific map
        for ts, missed_payload in missed_messages:
            queue.put_nowait(missed_payload)

        # Remove user from recently disconnected since they've reconnected to this map
        del recently_disconnected_users[user_map_key]
    try:
        while True:
            queue_task = asyncio.create_task(queue.get())
            recv_task = asyncio.create_task(ws.receive())

            done, pending = await asyncio.wait(
                {queue_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
            )

            # client closed
            if recv_task in done:
                for task in pending:
                    task.cancel()
                break

            # got a payload
            payload = queue_task.result()
            recv_task.cancel()

            notification = json.loads(payload)

            # Check if this is an ephemeral message
            if notification.get("ephemeral"):
                # Send ephemeral message directly without DB lookup
                await ws.send_json(notification)
                continue
            # Get the full message from the database using the id from notification
            async with get_async_db_connection() as conn:
                message = await conn.fetchrow(
                    """
                    SELECT * FROM chat_completion_messages
                    WHERE id = $1 AND map_id = $2
                    """,
                    notification["id"],
                    notification["map_id"],
                )

                if message:
                    # Convert datetime and UUID objects to JSON serializable format
                    message_dict = dict(message)
                    for key, value in message_dict.items():
                        if isinstance(value, datetime):
                            message_dict[key] = value.isoformat()
                        elif (
                            hasattr(value, "__class__")
                            and value.__class__.__name__ == "UUID"
                        ):
                            message_dict[key] = str(value)
                        elif key == "message_json":
                            message_dict[key] = json.loads(value)

                    # Only send if message_json role is user or assistant and no tool_calls
                    message_json = message_dict.get("message_json", {})
                    role = message_json.get("role")
                    tool_calls = message_json.get("tool_calls")
                    if role in ("user", "assistant") and not tool_calls:
                        await ws.send_json(message_dict)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Unexpected WebSocket error for map {map_id}: {e}")
    finally:
        # Track this user as recently disconnected from this specific map
        user_map_key = (user_id, map_id)
        recently_disconnected_users[user_map_key] = {
            "disconnect_time": time.time(),
            "missed_messages": deque(),
        }

        async with subscribers_lock:
            subscribers_by_map[map_id].discard(queue)
            if not subscribers_by_map[map_id]:
                del subscribers_by_map[map_id]


async def _broadcast_payload(payload: str):
    try:
        record = json.loads(payload)
        map_id = record.get("map_id")
        now = time.time()

        # Store messages for recently disconnected users who might reconnect to this specific map
        users_to_remove = []
        for (
            user_id,
            disconnected_map_id,
        ), user_data in recently_disconnected_users.items():
            # Clean up users who disconnected too long ago
            if now - user_data["disconnect_time"] > DISCONNECT_TTL:
                users_to_remove.append((user_id, disconnected_map_id))
                continue

            # Only store messages for users who were disconnected from this specific map
            if disconnected_map_id == map_id:
                # Add message to their missed messages buffer
                missed_messages = user_data["missed_messages"]
                missed_messages.append((now, payload))

                # Limit buffer size
                while len(missed_messages) > MAX_MISSED_MESSAGES:
                    missed_messages.popleft()

        # Remove expired users
        for user_key in users_to_remove:
            del recently_disconnected_users[user_key]

        # Broadcast to live subscribers
        async with subscribers_lock:
            queues = list(subscribers_by_map.get(map_id, []))
        for q in queues:
            q.put_nowait(payload)
    except Exception:
        logger.exception("Error broadcasting payload")


@asynccontextmanager
async def kue_ephemeral_action(
    map_id: str,
    action_description: str,
    layer_id: str | None = None,
    update_style_json: bool = False,
):
    """
    Async context manager for ephemeral actions.
    Sends a websocket message with the action when entering,
    and automatically removes it when exiting the context.
    """
    action_id = str(uuid.uuid4())
    payload = {
        "map_id": map_id,
        "ephemeral": True,
        "action_id": action_id,
        "layer_id": layer_id,
        "action": action_description,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "status": "active",
        "updates": {
            "style_json": update_style_json,
        },
    }

    try:
        # Send the action started message
        payload_str = json.dumps(payload)

        # Store for recently disconnected users from this specific map
        now = time.time()
        users_to_remove = []
        for (
            user_id,
            disconnected_map_id,
        ), user_data in recently_disconnected_users.items():
            # Clean up users who disconnected too long ago
            if now - user_data["disconnect_time"] > DISCONNECT_TTL:
                users_to_remove.append((user_id, disconnected_map_id))
                continue

            # Only store messages for users who were disconnected from this specific map
            if disconnected_map_id == map_id:
                # Add message to their missed messages buffer
                missed_messages = user_data["missed_messages"]
                missed_messages.append((now, payload_str))

                # Limit buffer size
                while len(missed_messages) > MAX_MISSED_MESSAGES:
                    missed_messages.popleft()

        # Remove expired users
        for user_key in users_to_remove:
            del recently_disconnected_users[user_key]

        # Broadcast to live subscribers
        async with subscribers_lock:
            queues = list(subscribers_by_map.get(map_id, []))
        for q in queues:
            q.put_nowait(payload_str)

        # Yield control back to the caller
        yield payload

    finally:
        # Always send the action completed message
        payload["status"] = "completed"
        payload["completed_at"] = datetime.now(timezone.utc).isoformat()

        payload_str = json.dumps(payload)

        # Store completion for recently disconnected users from this specific map
        now = time.time()
        users_to_remove = []
        for (
            user_id,
            disconnected_map_id,
        ), user_data in recently_disconnected_users.items():
            # Clean up users who disconnected too long ago
            if now - user_data["disconnect_time"] > DISCONNECT_TTL:
                users_to_remove.append((user_id, disconnected_map_id))
                continue

            # Only store messages for users who were disconnected from this specific map
            if disconnected_map_id == map_id:
                # Add message to their missed messages buffer
                missed_messages = user_data["missed_messages"]
                missed_messages.append((now, payload_str))

                # Limit buffer size
                while len(missed_messages) > MAX_MISSED_MESSAGES:
                    missed_messages.popleft()

        # Remove expired users
        for user_key in users_to_remove:
            del recently_disconnected_users[user_key]

        # Broadcast to live subscribers
        async with subscribers_lock:
            queues = list(subscribers_by_map.get(map_id, []))
        for q in queues:
            q.put_nowait(payload_str)
