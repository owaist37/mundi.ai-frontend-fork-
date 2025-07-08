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
async def test_map_id(auth_client):
    map_title = f"Test Message Loop Map {uuid.uuid4()}"

    map_data = {
        "title": map_title,
        "description": "Map for testing message loop",
        "link_accessible": True,
    }

    response = await auth_client.post("/api/maps/create", json=map_data)

    assert response.status_code == 200
    map_id = response.json()["id"]

    return map_id


@pytest.fixture
async def test_vector_layer(auth_client, test_map_id):
    with open("/app/test_fixtures/UScounties.gpkg", "rb") as f:
        response = await auth_client.post(
            f"/api/maps/{test_map_id}/layers",
            files={"file": ("UScounties.gpkg", f, "application/octet-stream")},
            data={"layer_name": "US Counties", "add_layer_to_map": "true"},
        )

    assert response.status_code == 200
    layer_data = response.json()
    layer_id = layer_data["id"]

    return layer_id


@pytest.mark.anyio
async def test_message_simple_response(
    test_map_id, sync_auth_client, websocket_url_for_map
):
    def create_response_queue():
        return [
            MockResponse(
                "This is a test map without layers.",
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
            user_message = {
                "role": "user",
                "content": "Hello, can you tell me about this map?",
            }

            response = sync_auth_client.post(
                f"/api/maps/{test_map_id}/messages/send",
                json=user_message,
            )

            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "processing_started"

            sent_msg = websocket.receive_json()
            assert sent_msg["message_json"]["role"] == "user"
            assert "tell me about this map" in sent_msg["message_json"]["content"]

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
            assert "test map without layers" in assistant_msg["message_json"]["content"]

        messages_response = sync_auth_client.get(
            f"/api/maps/{test_map_id}/messages",
        )

        assert messages_response.status_code == 200
        messages_data = messages_response.json()

        user_messages = [
            m["message_json"]
            for m in messages_data["messages"]
            if m["message_json"]["role"] == "user"
        ]
        assistant_messages = [
            m["message_json"]
            for m in messages_data["messages"]
            if m["message_json"]["role"] == "assistant"
        ]

        assert len(user_messages) >= 1
        assert len(assistant_messages) >= 1
        assert user_messages[0]["content"] == "Hello, can you tell me about this map?"
        assert "test map without layers" in assistant_messages[0]["content"]
        assert len(assistant_messages[0]["content"]) > 0


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get("OPENAI_API_KEY") is None or os.environ.get("OPENAI_API_KEY") == "",
    reason="OPENAI_API_KEY is required for these tests",
)
async def test_error_recovery(test_map_id, auth_client):
    fail_message = {
        "role": "user",
        "content": "Calculate centroids for a layer with ID 'nonexistent_123'.",
    }

    response = await auth_client.post(
        f"/api/maps/{test_map_id}/messages/send",
        json=fail_message,
    )

    assert response.status_code == 200

    valid_message = {
        "role": "user",
        "content": "What GIS operations are available in this system?",
    }

    response = await auth_client.post(
        f"/api/maps/{test_map_id}/messages/send",
        json=valid_message,
    )

    assert response.status_code == 200
    messages_response = await auth_client.get(
        f"/api/maps/{test_map_id}/messages",
    )

    assert messages_response.status_code == 200
    messages_data = messages_response.json()

    user_messages = [
        m["message_json"]
        for m in messages_data["messages"]
        if m["message_json"]["role"] == "user"
    ]
    assistant_messages = [
        m["message_json"]
        for m in messages_data["messages"]
        if m["message_json"]["role"] == "assistant"
        and "content" in m["message_json"]
        and m["message_json"]["content"]
    ]

    assert len(user_messages) >= 2
    assert len(assistant_messages) >= 2

    last_response = assistant_messages[-1]["content"].lower()
    operation_terms = ["gis", "operation", "analysis", "function", "tool"]
    has_operation_info = any(term in last_response for term in operation_terms)
    assert has_operation_info


@pytest.mark.anyio
async def test_sequential_response_handling(
    test_map_id, sync_auth_client, websocket_url_for_map
):
    def create_response_queue():
        return [
            MockResponse(
                "First, GIS is a system for spatial data. Second, spatial analysis examines location relationships. Third, GIS enables spatial analysis.",
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
            user_message = {
                "role": "user",
                "content": (
                    "First, describe what a GIS is. Second, explain what spatial analysis is. "
                    "Third, tell me about the relationship between them."
                ),
            }

            response = sync_auth_client.post(
                f"/api/maps/{test_map_id}/messages/send",
                json=user_message,
            )

            assert response.status_code == 200

            sent_msg = websocket.receive_json()
            assert sent_msg["message_json"]["role"] == "user"

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
            assert "GIS" in assistant_msg["message_json"]["content"]

        messages_response = sync_auth_client.get(
            f"/api/maps/{test_map_id}/messages",
        )

        assert messages_response.status_code == 200
        messages_data = messages_response.json()

        assistant_messages = [
            m["message_json"]
            for m in messages_data["messages"]
            if m["message_json"]["role"] == "assistant"
            and "content" in m["message_json"]
            and m["message_json"]["content"]
        ]

        assert len(assistant_messages) >= 1

        combined_response = " ".join([m["content"].lower() for m in assistant_messages])

        assert "gis" in combined_response, "Response should mention GIS"
        assert "spatial analysis" in combined_response, (
            "Response should mention spatial analysis"
        )
        assert "relationship" in combined_response or "connect" in combined_response, (
            "Response should discuss the relationship"
        )

        structure_indicators = [
            "first",
            "second",
            "third",
            "1.",
            "2.",
            "3.",
            "what is gis",
            "spatial analysis is",
            "relationship between",
        ]

        has_structure = any(
            indicator in combined_response for indicator in structure_indicators
        )
        assert has_structure, (
            "Response should have a structured format addressing each part"
        )


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get("OPENAI_API_KEY") is None or os.environ.get("OPENAI_API_KEY") == "",
    reason="OPENAI_API_KEY is required for these tests",
)
async def test_map_locking_prevents_concurrent_requests(auth_client):
    import asyncio

    map_data = {
        "title": f"Test Lock Map {uuid.uuid4()}",
        "description": "Map for testing locking",
        "link_accessible": True,
    }

    map_response = await auth_client.post("/api/maps/create", json=map_data)
    assert map_response.status_code == 200
    map_id = map_response.json()["id"]

    user_message = {
        "role": "user",
        "content": "Hi",
    }

    tasks = [
        auth_client.post(
            f"/api/maps/{map_id}/messages/send",
            json=user_message,
        ),
        auth_client.post(
            f"/api/maps/{map_id}/messages/send",
            json=user_message,
        ),
    ]

    response1, response2 = await asyncio.gather(*tasks, return_exceptions=True)

    responses = [response1, response2]
    status_codes = [r.status_code for r in responses]

    assert 200 in status_codes, "At least one request should succeed"
    assert 409 in status_codes, "At least one request should be blocked by locking"

    conflict_response = next(r for r in responses if r.status_code == 409)
    assert "currently being processed" in conflict_response.json()["detail"]
