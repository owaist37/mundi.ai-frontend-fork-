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

import pytest
import json
from src.structures import async_conn


@pytest.mark.anyio
async def test_chat_completion_message_json_migration(
    auth_client, run_alembic_operation
):
    # First, downgrade to the revision before our migration
    await run_alembic_operation("downgrade", "71c52d9a8344")

    # Create a test map first
    response = await auth_client.post(
        "/api/maps/create",
        json={
            "title": "Migration Test Map",
            "description": "Test map for migration testing",
        },
    )
    assert response.status_code == 200
    map_id = response.json()["id"]

    # Insert test data with message_json as TEXT (JSON string) - old format
    test_message = {
        "role": "user",
        "content": "Hello, this is a test message before migration",
    }

    async with async_conn("test_migration") as conn:
        # Insert directly into database with JSON as string (old format)
        await conn.execute(
            """
            INSERT INTO chat_completion_messages (map_id, sender_id, message_json)
            VALUES ($1, $2, $3)
            """,
            map_id,
            "12345678-1234-1234-1234-123456789012",
            json.dumps(test_message),
        )

        # Verify it's stored as TEXT (string)
        result = await conn.fetchrow(
            """
            SELECT message_json, pg_typeof(message_json) as column_type
            FROM chat_completion_messages
            WHERE map_id = $1
            """,
            map_id,
        )

        assert result["column_type"] == "text"  # Should be TEXT type
        assert isinstance(result["message_json"], str)  # Should be a string
        assert (
            json.loads(result["message_json"]) == test_message
        )  # Should be valid JSON

    # Run the actual alembic migration
    await run_alembic_operation("upgrade", "07c7ae795a24")

    # Verify the migration worked
    async with async_conn("test_migration_verify") as conn:
        result = await conn.fetchrow(
            """
            SELECT message_json, pg_typeof(message_json) as column_type
            FROM chat_completion_messages
            WHERE map_id = $1
            """,
            map_id,
        )

        assert result["column_type"] == "jsonb"  # Should now be JSONB type
        # The data should be the same but now as JSONB
        # asyncpg returns JSONB as string, so we need to parse it
        parsed_json = (
            json.loads(result["message_json"])
            if isinstance(result["message_json"], str)
            else result["message_json"]
        )
        assert parsed_json == test_message

    # Test that the API endpoint works correctly
    response = await auth_client.get(f"/api/maps/{map_id}/messages")
    assert response.status_code == 200

    data = response.json()
    assert data["map_id"] == map_id
    assert len(data["messages"]) == 1

    # Verify the message content is correctly parsed
    message = data["messages"][0]
    assert message["message_json"]["role"] == "user"
    assert (
        message["message_json"]["content"]
        == "Hello, this is a test message before migration"
    )
