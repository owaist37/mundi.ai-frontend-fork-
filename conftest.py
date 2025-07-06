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
import os

# Set fast timeout for postgres connections in tests
os.environ["MUNDI_POSTGIS_TIMEOUT_SEC"] = "0.1"
from httpx_ws.transport import ASGIWebSocketTransport
from httpx import AsyncClient
from pathlib import Path
import random
import asyncio
from starlette.testclient import TestClient

from src.wsgi import app
from src.database.migrate import run_migrations


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
@pytest.mark.anyio
async def client():
    # Run database migrations before tests
    await run_migrations()

    transport = ASGIWebSocketTransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture(scope="session")
async def auth_client(client):
    assert os.environ.get("MUNDI_AUTH_MODE") == "edit"

    yield client


@pytest.fixture
async def test_map_with_vector_layers(auth_client):
    map_payload = {
        "title": "Geoprocessing Test Map",
        "description": "Test map for geoprocessing operations with vector layers",
    }
    map_response = await auth_client.post("/api/maps/create", json=map_payload)
    assert map_response.status_code == 200, f"Failed to create map: {map_response.text}"
    map_id = map_response.json()["id"]
    layer_ids = {}

    async def _upload_layer(file_name, layer_name_in_db):
        file_path = str(Path(__file__).parent / "test_fixtures" / file_name)
        if not os.path.exists(file_path):
            pytest.skip(f"Test file {file_path} not found")
        with open(file_path, "rb") as f:
            layer_response = await auth_client.post(
                f"/api/maps/{map_id}/layers",
                files={"file": (file_name, f, "application/octet-stream")},
                data={"layer_name": layer_name_in_db},
            )
            assert layer_response.status_code == 200, (
                f"Failed to upload layer {file_name}: {layer_response.text}"
            )
            return layer_response.json()["id"]

    random.seed(42)
    layer_ids["beaches_layer_id"] = await _upload_layer(
        "barcelona_beaches.fgb", "Barcelona Beaches"
    )
    layer_ids["cafes_layer_id"] = await _upload_layer(
        "barcelona_cafes.fgb", "Barcelona Cafes"
    )
    layer_ids["idaho_stations_layer_id"] = await _upload_layer(
        "idaho_weatherstations.geojson", "Idaho Weather Stations"
    )
    return {"map_id": map_id, **layer_ids}


@pytest.fixture(scope="function")
def sync_client():
    # Run database migrations before tests
    asyncio.run(run_migrations())

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="function")
def sync_auth_client(sync_client):
    assert os.environ.get("MUNDI_AUTH_MODE") == "edit"
    yield sync_client


@pytest.fixture
def websocket_url_for_map(sync_auth_client):
    def _get_url(map_id):
        return f"/api/maps/ws/{map_id}/messages/updates"

    return _get_url


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "s3: mark test as requiring S3/MinIO access")
    config.addinivalue_line(
        "markers", "postgres: mark test as requiring PostgreSQL access"
    )
    config.addinivalue_line("markers", "anyio: mark a test as asynchronous using AnyIO")
