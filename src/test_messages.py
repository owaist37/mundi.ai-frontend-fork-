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
from unittest.mock import patch, AsyncMock
from openai.types.chat import (
    ChatCompletionMessage,
)


class MockChoice:
    def __init__(self, content: str, tool_calls=None):
        self.message = ChatCompletionMessage(
            content=content, tool_calls=tool_calls, role="assistant"
        )


class MockResponse:
    def __init__(self, content: str, tool_calls=None):
        self.choices = [MockChoice(content, tool_calls)]


@pytest.fixture
def test_map_id(sync_auth_client):
    map_title = f"Test Message Map {uuid.uuid4()}"
    map_data = {
        "title": map_title,
        "description": "Map for testing message API",
        "link_accessible": True,
    }
    response = sync_auth_client.post("/api/maps/create", json=map_data)
    assert response.status_code == 200
    map_id = response.json()["id"]
    return map_id


@pytest.mark.anyio
async def test_send_and_get_messages(
    test_map_id, sync_auth_client, websocket_url_for_map
):
    def create_response_queue():
        return [
            MockResponse(
                "I'll help analyze your map.",
                None,
            ),
        ]

    response_queue = create_response_queue()

    with patch("src.routes.message_routes.get_openai_client") as mock_get_client:
        mock_client = AsyncMock()

        async def mock_create(*args, **kwargs):
            return response_queue.pop(0)

        mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)
        mock_get_client.return_value = mock_client

        response = sync_auth_client.get(f"/api/maps/{test_map_id}/messages")
        assert response.status_code == 200
        data = response.json()
        assert data["map_id"] == test_map_id
        assert len(data["messages"]) == 0

        with sync_auth_client.websocket_connect(
            websocket_url_for_map(test_map_id)
        ) as websocket:
            user_message = {
                "role": "user",
                "content": "Hello, can you help me analyze this map?",
            }
            response = sync_auth_client.post(
                f"/api/maps/{test_map_id}/messages/send",
                json=user_message,
            )
            assert response.status_code == 200
            assert response.json()["status"] == "processing_started"

            sent_msg = websocket.receive_json()
            assert sent_msg["message_json"]["role"] == "user"
            assert "analyze this map" in sent_msg["message_json"]["content"]

            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            msg = websocket.receive_json()
            assert (
                msg["ephemeral"]
                and msg["action"] == "Kue is thinking..."
                and msg["status"] == "completed"
            )

            assistant_msg = websocket.receive_json()
            assert assistant_msg["message_json"]["role"] == "assistant"
            assert "analyze" in assistant_msg["message_json"]["content"]

        response = sync_auth_client.get(f"/api/maps/{test_map_id}/messages")
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["message_json"]["role"] == "user"
        assert data["messages"][1]["message_json"]["role"] == "assistant"
