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
import os
import random
from pathlib import Path
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


@pytest.fixture
def sync_test_map_with_vector_layers(sync_auth_client):
    map_payload = {
        "title": "Geoprocessing Test Map",
        "description": "Test map for geoprocessing operations with vector layers",
    }
    map_response = sync_auth_client.post("/api/maps/create", json=map_payload)
    assert map_response.status_code == 200, f"Failed to create map: {map_response.text}"
    map_id = map_response.json()["id"]
    layer_ids = {}

    def _upload_layer(file_name, layer_name_in_db):
        file_path = str(Path(__file__).parent.parent / "test_fixtures" / file_name)
        assert os.path.exists(file_path)
        with open(file_path, "rb") as f:
            layer_response = sync_auth_client.post(
                f"/api/maps/{map_id}/layers",
                files={"file": (file_name, f, "application/octet-stream")},
                data={"layer_name": layer_name_in_db},
            )
            assert layer_response.status_code == 200, (
                f"Failed to upload layer {file_name}: {layer_response.text}"
            )
            return layer_response.json()["id"]

    random.seed(42)
    layer_ids["cafes_layer_id"] = _upload_layer(
        "barcelona_cafes.fgb", "Barcelona Cafes"
    )
    return {"map_id": map_id, **layer_ids}


@pytest.mark.anyio
async def test_chat_completions(
    sync_test_map_with_vector_layers,
    auth_client,
    sync_auth_client,
    websocket_url_for_map,
):
    layer_id = sync_test_map_with_vector_layers["cafes_layer_id"]
    map_id = sync_test_map_with_vector_layers["map_id"]

    def create_response_queue():
        return [
            MockResponse(
                "I'll help you count the cafes where name=Starbucks using a SQL query.",
                [
                    ChatCompletionMessageToolCall(
                        id="call_1",
                        type="function",
                        function=Function(
                            name="query_duckdb_sql",
                            arguments=json.dumps(
                                {
                                    "layer_ids": [layer_id],
                                    "sql_query": f"SELECT COUNT(*) as count FROM {layer_id} WHERE name = 'Starbucks'",
                                    "head_n_rows": 20,
                                }
                            ),
                        ),
                    )
                ],
            ),
            MockResponse(
                "Based on the query results, there are 18 cafes where name=Starbucks.",
                None,
            ),
        ]

    response_queue = create_response_queue()

    with patch("src.routes.message_routes.get_openai_client") as mock_get_client:
        mock_client = AsyncMock()

        async def mock_create(*args, **kwargs):
            response = response_queue.pop(0)
            return response

        mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)
        mock_get_client.return_value = mock_client

        with sync_auth_client.websocket_connect(
            websocket_url_for_map(map_id)
        ) as websocket:
            response = sync_auth_client.post(
                f"/api/maps/{map_id}/messages/send",
                json={
                    "role": "user",
                    "content": "Count how many cafes have name=Starbucks",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "processing_started"
            assert "message_id" in data

            sent_msg = websocket.receive_json()
            assert sent_msg["message_json"]["role"] == "user"
            assert (
                sent_msg["message_json"]["content"]
                == "Count how many cafes have name=Starbucks"
            )

            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            assert msg["status"] == "completed"

            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Querying with SQL..."
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Querying with SQL..."
            assert msg["status"] == "completed"

            async with get_async_db_connection() as conn:
                messages = await conn.fetch(
                    "SELECT id, sender_id, message_json, created_at FROM chat_completion_messages WHERE map_id = $1 ORDER BY created_at",
                    map_id,
                )

                tool_response = None
                for m in messages:
                    msg_json = json.loads(dict(m)["message_json"])
                    if (
                        msg_json.get("role") == "tool"
                        and msg_json.get("tool_call_id") == "call_1"
                    ):
                        tool_response = json.loads(msg_json["content"])
                        break

                assert tool_response is not None
                print("DuckDB Tool Response:", json.dumps(tool_response, indent=2))

                assert tool_response["status"] == "success"
                assert "result" in tool_response
                assert "row_count" in tool_response
                assert "query" in tool_response

                result_lines = (
                    tool_response["result"].replace("\r", "").strip().split("\n")
                )
                assert len(result_lines) == 2
                assert result_lines[0] == "count"
                assert result_lines[1] == "18"
                assert tool_response["row_count"] == 1

            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            msg = websocket.receive_json()
            assert msg["ephemeral"] and msg["action"] == "Kue is thinking..."
            assert msg["status"] == "completed"

            assistant_msg = websocket.receive_json()
            print("Assistant response:", assistant_msg)
            assert assistant_msg["message_json"]["role"] == "assistant"
            assert (
                "18 cafes where name=Starbucks"
                in assistant_msg["message_json"]["content"]
            )
