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

import os
import logging
import httpx
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Request, Depends
from pydantic import BaseModel
from redis import Redis
from ..dependencies.session import (
    verify_session_optional,
    UserContext,
)
from ..structures import get_async_db_connection

router = APIRouter()

redis = Redis(
    host=os.environ["REDIS_HOST"],
    port=int(os.environ["REDIS_PORT"]),
    decode_responses=True,
)

logger = logging.getLogger(__name__)

DRIFTDB_SERVER_URL = os.environ["DRIFTDB_SERVER_URL"]


class RoomResponse(BaseModel):
    room_id: str


@router.get("/{map_id}/room", response_model=RoomResponse)
async def get_map_room(
    map_id: str,
    request: Request,
    session: Optional[UserContext] = Depends(verify_session_optional),
):
    async with get_async_db_connection() as conn:
        map_result = await conn.fetchrow(
            """
            SELECT m.id, m.owner_uuid, p.link_accessible
            FROM user_mundiai_maps m
            JOIN user_mundiai_projects p ON m.project_id = p.id
            WHERE m.id = $1 AND m.soft_deleted_at IS NULL
            """,
            map_id,
        )

        if not map_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Map not found",
            )

        if not map_result["link_accessible"]:
            if session is None or session.get_user_id() != str(
                map_result["owner_uuid"]
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required to access this map",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    redis_key = f"map:{map_id}:room_id"
    room_id = redis.get(redis_key)

    if room_id:
        # Validate the room exists before returning it
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(f"{DRIFTDB_SERVER_URL}/room/{room_id}")
                if response.status_code == 200:
                    return RoomResponse(room_id=room_id)
                else:
                    redis.delete(redis_key)
            except Exception:
                redis.delete(redis_key)

    async with httpx.AsyncClient() as client:
        response = await client.post(f"{DRIFTDB_SERVER_URL}/new")

        if response.status_code != 200:
            logger.error(f"Failed to create room: {response.text}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create room",
            )

        response_data = response.json()
        room_id = response_data.get("room")

    if not room_id:
        logger.error(f"Invalid response from DriftDB: {response_data}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid response from room creation service",
        )

    redis.setex(redis_key, 1800, room_id)  # 30 minutes TTL
    logger.info(f"Created and stored new room {room_id} for map {map_id}")

    return RoomResponse(room_id=room_id)
