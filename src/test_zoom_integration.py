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
import json
from unittest.mock import patch, AsyncMock
from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageToolCall,
)
from openai.types.chat.chat_completion_message_tool_call import Function


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
    map_title = f"Test Zoom Integration Map {uuid.uuid4()}"
    map_data = {
        "title": map_title,
        "description": "Map for testing zoom integration with mocked OpenAI API",
        "link_accessible": True,
    }
    response = sync_auth_client.post("/api/maps/create", json=map_data)
    assert response.status_code == 200
    map_id = response.json()["id"]
    return map_id


@pytest.mark.anyio
async def test_zoom_integration_with_real_openai(
    auth_client, test_map_id, sync_auth_client, websocket_url_for_map
):
    def create_response_queue():
        return [
            MockResponse(
                "I'll zoom to downtown Seattle for you.",
                [
                    ChatCompletionMessageToolCall(
                        id="call_1",
                        type="function",
                        function=Function(
                            name="zoom_to_bounds",
                            arguments=json.dumps(
                                {
                                    "bounds": [-122.4194, 47.6062, -122.3320, 47.6205],
                                    "zoom_description": "Zooming to downtown Seattle",
                                }
                            ),
                        ),
                    )
                ],
            ),
            MockResponse(
                "I've zoomed to downtown Seattle for you. The map should now show the area with bounds [-122.4194, 47.6062, -122.3320, 47.6205].",
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

        with sync_auth_client.websocket_connect(
            websocket_url_for_map(test_map_id)
        ) as websocket:
            response = sync_auth_client.post(
                f"/api/maps/{test_map_id}/messages/send",
                json={
                    "role": "user",
                    "content": "Please zoom to downtown Seattle with bounds [-122.4194, 47.6062, -122.3320, 47.6205]",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "processing_started"
            assert "message_id" in data

            # our own message
            sent_msg = websocket.receive_json()
            assert sent_msg["message_json"]["role"] == "user"
            assert "zoom to downtown Seattle" in sent_msg["message_json"]["content"]

            # Kue is thinking
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            assert msg["status"] == "completed"

            # Zoom action
            msg = websocket.receive_json()
            assert msg["ephemeral"] and "Zooming to downtown Seattle" in msg["action"]
            assert "bounds" in msg
            assert msg["bounds"] == [-122.4194, 47.6062, -122.3320, 47.6205]
            msg = websocket.receive_json()
            assert msg["ephemeral"] and "Zooming to downtown Seattle" in msg["action"]
            assert msg["status"] == "completed"

            # Kue is thinking again
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            assert msg["status"] == "completed"

            # Assistant's final response
            assistant_msg = websocket.receive_json()
            assert assistant_msg["message_json"]["role"] == "assistant"
            assert (
                "zoomed to downtown Seattle" in assistant_msg["message_json"]["content"]
                or "Seattle" in assistant_msg["message_json"]["content"]
            )
