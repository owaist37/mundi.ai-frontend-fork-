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
from starlette.testclient import WebSocketDenialResponse


@pytest.fixture
async def test_map_id(auth_client):
    map_title = f"Test Room Map {uuid.uuid4()}"

    map_data = {
        "title": map_title,
        "description": "Map for testing room functionality",
        "link_accessible": True,
    }

    response = await auth_client.post("/api/maps/create", json=map_data)
    assert response.status_code == 200
    map_id = response.json()["id"]

    return map_id


@pytest.fixture
async def private_test_map_id(auth_client):
    map_title = f"Private Test Room Map {uuid.uuid4()}"

    map_data = {
        "title": map_title,
        "description": "Private map for testing room access",
        "link_accessible": False,
    }

    response = await auth_client.post("/api/maps/create", json=map_data)
    assert response.status_code == 200
    map_id = response.json()["id"]

    return map_id


@pytest.mark.anyio
async def test_get_same_room_twice(test_map_id, auth_client):
    # First request for the room
    response1 = await auth_client.get(f"/api/maps/{test_map_id}/room")
    assert response1.status_code == 200
    room_data1 = response1.json()
    assert "room_id" in room_data1
    room_id1 = room_data1["room_id"]
    assert room_id1

    # Second request for the same room
    response2 = await auth_client.get(f"/api/maps/{test_map_id}/room")
    assert response2.status_code == 200
    room_data2 = response2.json()
    assert "room_id" in room_data2
    room_id2 = room_data2["room_id"]

    # Verify both requests returned the same room ID
    assert room_id1 == room_id2


@pytest.mark.anyio
async def test_nonexistent_map_returns_404(auth_client):
    response = await auth_client.get("/api/maps/M1234567890/room")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_private_map_access_in_edit_mode(private_test_map_id, auth_client):
    # In edit mode, all maps should be accessible
    response = await auth_client.get(f"/api/maps/{private_test_map_id}/room")
    assert response.status_code == 200
    room_data = response.json()
    assert "room_id" in room_data
    assert room_data["room_id"]


@pytest.mark.anyio
async def test_websocket_expired_room_connection(sync_auth_client):
    # Test connecting to a websocket room
    room_id = "3a03d05f-92a1-4df4-8dcb-2ea608233886"

    with pytest.raises(WebSocketDenialResponse):
        with sync_auth_client.websocket_connect(f"/room/{room_id}/connect"):
            pytest.fail("WebSocket connection should not proxy connect to random room")
