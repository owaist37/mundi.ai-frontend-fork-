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
from unittest.mock import patch, AsyncMock
from src.structures import get_async_db_connection
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


@pytest.mark.anyio
async def test_chat_completions(
    test_map_with_vector_layers, auth_client, sync_auth_client, websocket_url_for_map
):
    layer_id = test_map_with_vector_layers["beaches_layer_id"]
    map_id = test_map_with_vector_layers["map_id"]

    def create_response_queue():
        return [
            MockResponse(
                "I'll help you buffer the beaches layer with a 100-unit distance.",
                [
                    ChatCompletionMessageToolCall(
                        id="call_1",
                        type="function",
                        function=Function(
                            name="native_buffer",
                            arguments=json.dumps({"INPUT": layer_id, "DISTANCE": 100}),
                        ),
                    )
                ],
            ),
            MockResponse(
                "Now I'll add the buffered layer to your map.",
                [
                    ChatCompletionMessageToolCall(
                        id="call_2",
                        type="function",
                        function=Function(
                            name="add_layer_to_map",
                            arguments=json.dumps(
                                {
                                    "layer_id": "$LAST_LAYER_ID",
                                    "new_name": "Buffered Beaches",
                                }
                            ),
                        ),
                    )
                ],
            ),
            MockResponse(
                "I've successfully created a buffer around the beaches with a 100-unit distance. The buffered layer has been added to your map.",
                None,
            ),
        ]

    response_queue = create_response_queue()

    with patch("src.routes.message_routes.get_openai_client") as mock_get_client:
        mock_client = AsyncMock()

        async def mock_create(*args, **kwargs):
            response = response_queue.pop(0)
            for tool_call in response.choices[0].message.tool_calls or []:
                if "$LAST_LAYER_ID" in tool_call.function.arguments:
                    async with get_async_db_connection() as conn:
                        layers = await conn.fetch(
                            "SELECT layer_id FROM map_layers ORDER by created_on desc limit 1"
                        )
                        assert layers is not None
                    actual_layer_id = layers[0]["layer_id"]
                    tool_call.function.arguments = tool_call.function.arguments.replace(
                        "$LAST_LAYER_ID", actual_layer_id
                    )
            return response

        mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)
        mock_get_client.return_value = mock_client

        with sync_auth_client.websocket_connect(
            websocket_url_for_map(map_id)
        ) as websocket:
            response = await auth_client.post(
                f"/api/maps/{map_id}/messages/send",
                json={
                    "role": "user",
                    "content": "Buffer the beaches layer with a distance of 100",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "processing_started"
            assert "message_id" in data

            # our own message
            sent_msg = websocket.receive_json()
            assert sent_msg["message_json"]["role"] == "user"
            assert (
                sent_msg["message_json"]["content"]
                == "Buffer the beaches layer with a distance of 100"
            )

            # Kue is thinking
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            assert msg["status"] == "completed"

            # Execute geoprocessing
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "QGIS running native:buffer..."
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "QGIS running native:buffer..."
            assert msg["status"] == "completed"

            # loops once
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            assert msg["status"] == "completed"

            # Adding layer to map
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Adding layer to map..."
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Adding layer to map..."
            assert msg["status"] == "completed"

            async with get_async_db_connection() as conn:
                layers = await conn.fetch(
                    "SELECT layer_id, metadata FROM map_layers ORDER by created_on desc limit 1"
                )
                layer_metadata = json.loads(layers[0]["metadata"])
                created_layer_id = layers[0]["layer_id"]

                assert layer_metadata["feature_count"] == 37
                assert layer_metadata["geometry_type"] == "multipolygon"

            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            assert msg["status"] == "completed"

            assistant_msg = websocket.receive_json()
            print("assistant", assistant_msg)
            assert assistant_msg["message_json"]["role"] == "assistant"
            assert (
                "successfully created a buffer around the beaches with a 100-unit distance"
                in assistant_msg["message_json"]["content"]
            )

            async with get_async_db_connection() as conn:
                map_with_layer = await conn.fetchrow(
                    "SELECT id FROM user_mundiai_maps WHERE $1 = ANY(layers)",
                    created_layer_id,
                )
                assert map_with_layer is not None
                assert map_with_layer["id"] == map_id
