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
import uuid
import os


@pytest.fixture
async def test_map_id(auth_client):
    map_title = f"Test Message Map {uuid.uuid4()}"
    map_data = {
        "title": map_title,
        "description": "Map for testing message API",
        "link_accessible": True,
    }
    response = await auth_client.post("/api/maps/create", json=map_data)
    assert response.status_code == 200
    map_id = response.json()["id"]
    yield map_id


@pytest.mark.skipif(
    os.environ.get("OPENAI_API_KEY") is None or os.environ.get("OPENAI_API_KEY") == "",
    reason="OpenAI API key not set",
)
@pytest.mark.anyio
async def test_send_and_get_messages(test_map_id, auth_client):
    response = await auth_client.get(f"/api/maps/{test_map_id}/messages")
    assert response.status_code == 200
    data = response.json()
    assert data["map_id"] == test_map_id
    assert len(data["messages"]) == 0

    user_message = {
        "role": "user",
        "content": "Hello, can you help me analyze this map?",
    }
    response = await auth_client.post(
        f"/api/maps/{test_map_id}/messages/send",
        json=user_message,
    )
    assert response.status_code == 200
