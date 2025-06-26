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
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import asyncpg
from fastapi import HTTPException, status
import logging

from ..structures import get_async_db_connection

logger = logging.getLogger(__name__)


class PostgresConnectionManager:
    def __init__(self):
        pass

    async def get_connection(self, connection_id: str) -> Dict[str, Any]:
        """Get connection details by ID. Returns dict with connection data."""
        async with get_async_db_connection() as conn:
            connection = await conn.fetchrow(
                """
                SELECT id, project_id, user_id, connection_uri, connection_name,
                       created_at, updated_at, last_error_text, last_error_timestamp,
                       soft_deleted_at
                FROM project_postgres_connections
                WHERE id = $1
                """,
                connection_id,
            )
            if not connection:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Postgres connection {connection_id} not found",
                )
            return dict(connection)

    async def update_error_status(
        self, connection_id: str, error_text: Optional[str] = None
    ) -> None:
        """Update error status for a connection."""
        async with get_async_db_connection() as conn:
            if error_text:
                await conn.execute(
                    """
                    UPDATE project_postgres_connections
                    SET last_error_text = $1, last_error_timestamp = $2
                    WHERE id = $3
                    """,
                    error_text,
                    datetime.now(timezone.utc),
                    connection_id,
                )
            else:
                await conn.execute(
                    """
                    UPDATE project_postgres_connections
                    SET last_error_text = NULL, last_error_timestamp = NULL
                    WHERE id = $1
                    """,
                    connection_id,
                )

    async def connect_to_postgres(
        self, connection_id: str, timeout: float = 10.0
    ) -> asyncpg.Connection:
        """Connect to a PostgreSQL database using the stored connection details."""
        pg_connection = await self.get_connection(connection_id)

        try:
            conn = await asyncio.wait_for(
                asyncpg.connect(pg_connection["connection_uri"]), timeout=timeout
            )
            await self.update_error_status(connection_id, error_text=None)
            return conn
        except asyncio.TimeoutError:
            error_msg = f"Connection timeout after {timeout}s"
            await self.update_error_status(connection_id, error_msg)
            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail=f"Failed to connect to postgres: {error_msg}",
            )
        except asyncpg.PostgresError as e:
            error_msg = f"Postgres error: {str(e)}"
            await self.update_error_status(connection_id, error_msg)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to connect to postgres: {error_msg}",
            )
        except Exception as e:
            logger.error(f"Unexpected third-party asyncpg error: {str(e)}")
            error_msg = f"Unexpected error: {str(e)}"
            await self.update_error_status(connection_id, error_msg)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to connect to postgres: {error_msg}",
            )


async def get_postgres_connection_manager() -> PostgresConnectionManager:
    """Get a PostgresConnectionManager instance."""
    return PostgresConnectionManager()
