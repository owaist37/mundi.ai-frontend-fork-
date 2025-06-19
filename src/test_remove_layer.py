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
from pathlib import Path


@pytest.fixture
async def test_setup(auth_client):
    project_data = {
        "title": "Test Remove Layer Map",
        "description": "A test map for removing layers",
    }
    response = await auth_client.post("/api/maps/create", json=project_data)
    assert response.status_code == 200, f"Failed to create map: {response.text}"
    map_data = response.json()
    map_id = map_data["id"]
    return {"map_id": map_id}


@pytest.mark.anyio
async def test_remove_layer_from_map(test_setup, auth_client):
    map_id = test_setup["map_id"]

    file_path = Path(__file__).parent.parent / "test_fixtures" / "airports.fgb"

    with open(file_path, "rb") as f:
        upload_response = await auth_client.post(
            f"/api/maps/{map_id}/layers",
            files={"file": (file_path.name, f, "application/octet-stream")},
            data={"layer_name": "Vector Layer"},
        )
        assert upload_response.status_code == 200
        layer_id = upload_response.json()["id"]

    layers_response = await auth_client.get(f"/api/maps/{map_id}/layers")
    assert layers_response.status_code == 200
    layers_data = layers_response.json()
    assert "layers" in layers_data
    assert len(layers_data["layers"]) == 1

    remove_response = await auth_client.delete(f"/api/maps/{map_id}/layer/{layer_id}")

    assert remove_response.status_code == 200
    remove_data = remove_response.json()
    assert "message" in remove_data
    assert "layer_id" in remove_data
    assert remove_data["layer_id"] == layer_id
    assert "successfully removed" in remove_data["message"].lower()

    layers_response_after = await auth_client.get(f"/api/maps/{map_id}/layers")
    assert layers_response_after.status_code == 200

    layers_data_after = layers_response_after.json()
    assert len(layers_data_after["layers"]) == 0


@pytest.mark.anyio
async def test_remove_nonexistent_layer(test_setup, auth_client):
    map_id = test_setup["map_id"]
    fake_layer_id = "nonexistentid123"
    remove_response = await auth_client.delete(
        f"/api/maps/{map_id}/layer/{fake_layer_id}"
    )
    assert remove_response.status_code == 404
