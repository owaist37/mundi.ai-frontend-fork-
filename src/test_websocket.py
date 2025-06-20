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
from httpx_ws import aconnect_ws, WebSocketDisconnect


@pytest.fixture
async def test_map_id(auth_client):
    map_title = f"Test WebSocket Map {uuid.uuid4()}"

    map_data = {
        "title": map_title,
        "description": "Map for testing WebSocket functionality",
        "link_accessible": True,
    }

    response = await auth_client.post("/api/maps/create", json=map_data)
    assert response.status_code == 200
    map_id = response.json()["id"]

    return map_id


@pytest.mark.anyio
async def test_websocket_successful_connection(test_map_id, auth_client):
    try:
        async with aconnect_ws(
            f"/api/maps/ws/{test_map_id}/messages/updates",
            auth_client,
        ) as websocket:
            await websocket.close()
    except Exception as e:
        pytest.fail(f"WebSocket connection should have succeeded but failed with: {e}")


@pytest.mark.anyio
async def test_websocket_no_token_in_view_mode(auth_client):
    test_map_id = "test-map-id"

    with pytest.raises(WebSocketDisconnect):
        async with aconnect_ws(
            f"/api/maps/ws/{test_map_id}/messages/updates", auth_client
        ):
            pytest.fail("WebSocket connection should have failed without token")
