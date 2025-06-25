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
import asyncio
import os
from unittest.mock import MagicMock, patch
import json


@pytest.fixture
async def test_map_id(auth_client):
    map_title = f"Test Zoom Integration Map {uuid.uuid4()}"
    map_data = {
        "title": map_title,
        "description": "Map for testing zoom integration with real OpenAI API",
        "link_accessible": True,
    }
    response = await auth_client.post("/api/maps/create", json=map_data)
    assert response.status_code == 200
    map_id = response.json()["id"]
    return map_id


@pytest.mark.skipif(
    os.environ.get("OPENAI_API_KEY") is None or os.environ.get("OPENAI_API_KEY") == "",
    reason="OpenAI API key not set",
)
@pytest.mark.anyio
async def test_zoom_integration_with_real_openai(auth_client, test_map_id):
    websocket_messages = []

    def capture_websocket_message(payload):
        try:
            data = json.loads(payload)
            websocket_messages.append(data)
            print(f"WebSocket message captured: {data}")
        except Exception as e:
            print(f"Error parsing WebSocket payload: {e}")

    with patch("src.routes.websocket.subscribers_by_map") as mock_subscribers:
        mock_queue = MagicMock()
        mock_queue.put_nowait = capture_websocket_message
        mock_subscribers.get.return_value = [mock_queue]

        with patch("src.routes.websocket.subscribers_lock"):
            user_message = {
                "role": "user",
                "content": "Please zoom to downtown Seattle with bounds [-122.4194, 47.6062, -122.3320, 47.6205]",
            }

            response = await auth_client.post(
                f"/api/maps/{test_map_id}/messages/send",
                json=user_message,
            )

            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "processing_started"

            await asyncio.sleep(8.0)

            # Look for a zoom action message
            zoom_messages = [
                msg
                for msg in websocket_messages
                if msg.get("action") == "zoom_to_bounds"
            ]
            assert len(zoom_messages) > 0, (
                f"Expected zoom message, got {len(websocket_messages)} messages: {websocket_messages}"
            )

            zoom_message = zoom_messages[0]
            assert zoom_message.get("status") == "zoom_action"
            assert "bounds" in zoom_message
