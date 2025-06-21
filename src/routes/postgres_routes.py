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

import os
import uuid
import psycopg2
import math
import secrets
from psycopg2.extras import RealDictCursor
from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Request,
    Depends,
    BackgroundTasks,
)
import asyncpg
from fastapi.responses import StreamingResponse, Response
from ..dependencies.db_pool import get_pooled_connection
from pydantic import BaseModel
from ..dependencies.session import (
    verify_session_required,
    verify_session_optional,
    UserContext,
)
from ..utils import get_openai_client
from typing import List, Optional
import logging
import difflib
from datetime import datetime
from pyproj import Transformer
from osgeo import osr
import re
from fastapi import File, UploadFile, Form
from PIL import Image
from redis import Redis
import httpx
import tempfile
import json
from starlette.responses import (
    JSONResponse as StarletteJSONResponse,
)
import asyncio
import botocore

from src.utils import (
    get_s3_client,
    get_bucket_name,
    process_zip_with_shapefile,
    get_async_s3_client,
)
import fiona
import duckdb
from osgeo import gdal
import io
import subprocess
from src.symbology.llm import generate_maplibre_layers_for_layer_id
from src.duckdb import execute_duckdb_query
from ..structures import get_db_connection, get_async_db_connection
from ..dependencies.base_map import BaseMapProvider, get_base_map_provider
from ..dependencies.postgis import get_postgis_provider
from ..dependencies.layer_describer import LayerDescriber, get_layer_describer
from ..dependencies.chat_completions import ChatArgsProvider, get_chat_args_provider
from ..dependencies.database_documenter import (
    DatabaseDocumenter,
    get_database_documenter,
)
from typing import Callable

# Global semaphore to limit concurrent social image renderings
# This prevents OOM issues when many maps load simultaneously
SOCIAL_RENDER_SEMAPHORE = asyncio.Semaphore(2)  # Max 2 concurrent renders

logger = logging.getLogger(__name__)

redis = Redis(
    host=os.environ["REDIS_HOST"],
    port=int(os.environ["REDIS_PORT"]),
    decode_responses=True,
)


# Create router
router = APIRouter()


def generate_id(length=12, prefix=""):
    """Generate a unique ID for the map or layer.

    Using characters [1-9A-HJ-NP-Za-km-z] (excluding 0, O, I, l)
    to avoid ambiguity in IDs.
    """
    assert len(prefix) in [0, 1], "Prefix must be at most 1 character"

    valid_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    result = "".join(secrets.choice(valid_chars) for _ in range(length - len(prefix)))
    return prefix + result


class MapCreateRequest(BaseModel):
    title: str = "Untitled Map"
    description: str = ""


class MapResponse(BaseModel):
    id: str  # map id
    project_id: str
    title: str
    description: str
    created_on: str
    last_edited: str


class UserMapsResponse(BaseModel):
    maps: List[MapResponse]


class LayerResponse(BaseModel):
    id: str
    name: str
    path: str
    type: str
    raster_cog_url: Optional[str] = None
    metadata: Optional[dict] = None
    bounds: Optional[List[float]] = (
        None  # [xmin, ymin, xmax, ymax] in WGS84 coordinates
    )
    geometry_type: Optional[str] = None  # point, multipoint, line, polygon, etc.
    feature_count: Optional[int] = None  # number of features in the layer


class LayersListResponse(BaseModel):
    map_id: str
    layers: List[LayerResponse]


class LayerUploadResponse(BaseModel):
    id: str
    name: str
    type: str
    url: str  # Direct URL to the layer
    message: str = "Layer added successfully"


class PresignedUrlResponse(BaseModel):
    url: str
    expires_in_seconds: int = 3600 * 24  # Default 24 hours
    format: str


@router.post("/create", response_model=MapResponse, operation_id="create_map")
async def create_map(
    request: Request,
    map_request: MapCreateRequest,
    session: UserContext = Depends(verify_session_required),
):
    owner_id = session.get_user_id()

    # Generate unique IDs for project and map
    project_id = generate_id(prefix="P")
    map_id = generate_id(prefix="M")

    # Connect to database
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # First create a project
        cursor.execute(
            """
            INSERT INTO user_mundiai_projects
            (id, owner_uuid, link_accessible, maps)
            VALUES (%s, %s, FALSE, ARRAY[%s])
            """,
            (
                project_id,
                owner_id,
                map_id,
            ),
        )

        # Then insert map with data including project_id and layer_ids
        cursor.execute(
            """
            INSERT INTO user_mundiai_maps
            (id, project_id, owner_uuid, title, description, display_as_diff)
            VALUES (%s, %s, %s, %s, %s, TRUE)
            RETURNING id, title, description, created_on, last_edited
            """,
            (
                map_id,
                project_id,
                owner_id,
                map_request.title,
                map_request.description,
            ),
        )

        # Get the created map data
        result = cursor.fetchone()

        # Validate the result
        if not result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database operation returned no result",
            )

        # Return the created map data
        return MapResponse(
            id=map_id,
            project_id=project_id,
            title=result["title"],
            description=result["description"],
            created_on=result["created_on"].isoformat(),
            last_edited=result["last_edited"].isoformat(),
        )


class ForkResponse(BaseModel):
    map_id: str
    project_id: str


@router.post(
    "/{map_id}/save_fork", response_model=ForkResponse, operation_id="save_and_fork_map"
)
async def save_and_fork_map(
    request: Request,
    map_id: str,
    session: UserContext = Depends(verify_session_required),
):
    """
    Create a fork of an existing map with a new map ID.
    The new map is added to the project's list of maps.
    """
    owner_id = session.get_user_id()

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Check if source map exists and user has access
        cursor.execute(
            """
            SELECT m.id, m.project_id, m.title, m.description, p.link_accessible, m.owner_uuid, m.layers
            FROM user_mundiai_maps m
            JOIN user_mundiai_projects p ON m.project_id = p.id
            WHERE m.id = %s AND m.soft_deleted_at IS NULL
            """,
            (map_id,),
        )

        source_map = cursor.fetchone()
        if not source_map:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Source map not found"
            )

        # Check access permissions
        if not source_map["link_accessible"] and owner_id != source_map["owner_uuid"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to fork this map",
            )

        # Get the project's current maps to find the previous map for diff
        cursor.execute(
            """
            SELECT maps
            FROM user_mundiai_projects
            WHERE id = %s AND soft_deleted_at IS NULL
            """,
            (source_map["project_id"],),
        )
        project = cursor.fetchone()
        proj_maps = project["maps"] or [] if project else []

        # Find the previous map for diff calculation
        prev_map_id = None
        try:
            current_index = proj_maps.index(map_id)
            if current_index > 0:
                prev_map_id = proj_maps[current_index - 1]
        except ValueError:
            pass  # map_id not found in project maps

        # Generate new map ID
        new_map_id = generate_id(prefix="M")

        # Create new map as a copy of the source map, including layers
        cursor.execute(
            """
            INSERT INTO user_mundiai_maps
            (id, project_id, owner_uuid, title, description, layers, display_as_diff)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id, title, description, created_on, last_edited
            """,
            (
                new_map_id,
                source_map["project_id"],
                owner_id,
                source_map["title"],
                source_map["description"],
                source_map["layers"],
            ),
        )
        cursor.fetchone()
        conn.commit()

        # Copy over all map_layer_styles to the new map
        if source_map["layers"]:
            cursor.execute(
                """
                INSERT INTO map_layer_styles (map_id, layer_id, style_id)
                SELECT %s, layer_id, style_id
                FROM map_layer_styles
                WHERE map_id = %s
                """,
                (new_map_id, map_id),
            )
            conn.commit()

        # Get a summary of the changes from the previous map to the source map
        diff_summary = {"diff_summary": "first map"}
        if prev_map_id:
            diff_summary = await summarize_map_diff(
                request, prev_map_id, map_id, session
            )

        # Update project to include the new map
        cursor.execute(
            """
            UPDATE user_mundiai_projects
            SET maps = array_append(maps, %s),
                map_diff_messages = array_append(map_diff_messages, %s)
            WHERE id = %s
            """,
            (new_map_id, diff_summary["diff_summary"], source_map["project_id"]),
        )

        return {
            "map_id": new_map_id,
            "project_id": source_map["project_id"],
        }


@router.get(
    "/{map_id}",
    operation_id="get_map",
)
async def get_map(
    request: Request,
    map_id: str,
    diff_map_id: Optional[str] = None,
    session: UserContext = Depends(verify_session_optional),
):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Retrieve the map and check access
        cursor.execute(
            """
            SELECT m.id, m.project_id, p.link_accessible, m.owner_uuid, m.layers, m.display_as_diff
            FROM user_mundiai_maps m
            JOIN user_mundiai_projects p ON m.project_id = p.id
            WHERE m.id = %s AND m.soft_deleted_at IS NULL
            """,
            (map_id,),
        )
        map_rec = cursor.fetchone()
        if not map_rec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
            )
        if not map_rec["link_accessible"]:
            if session is None or session.get_user_id() != map_rec["owner_uuid"]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        # Ensure map is part of a project
        project_id = map_rec.get("project_id")
        if not project_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Map is not part of a project",
            )

        # Load project and its changelog
        cursor.execute(
            """
            SELECT maps, map_diff_messages
            FROM user_mundiai_projects
            WHERE id = %s AND soft_deleted_at IS NULL
            """,
            (project_id,),
        )
        project = cursor.fetchone()
        if not project:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Project not found",
            )
        # Handle diff_map_id logic
        prev_map_id = None
        if diff_map_id == "auto":
            # Find the previous map in the project
            proj_maps = project["maps"] or []
            try:
                current_index = proj_maps.index(map_id)
                if current_index > 0:
                    prev_map_id = proj_maps[current_index - 1]
            except ValueError:
                pass  # map_id not found in project maps
        elif diff_map_id:
            prev_map_id = diff_map_id

        # Get last_edited times for maps in the project
        map_ids = project["maps"] or []
        if map_ids:
            placeholders = ", ".join(["%s"] * len(map_ids))
            cursor.execute(
                f"""
                SELECT id, last_edited
                FROM user_mundiai_maps
                WHERE id IN ({placeholders})
                """,
                map_ids,
            )
            map_edit_times = {
                row["id"]: row["last_edited"] for row in cursor.fetchall()
            }
        else:
            map_edit_times = {}

        proj_maps = project["maps"] or []
        diff_msgs = project["map_diff_messages"] or []
        diff_msgs = diff_msgs + ["current edit"]
        changelog = []
        # Pair each diff message with its resulting map state up to current
        for msg, state in zip(diff_msgs, proj_maps):
            changelog.append(
                {
                    "message": msg,
                    "map_state": state,
                    "last_edited": map_edit_times.get(state).isoformat()
                    if state in map_edit_times
                    else None,
                }
            )

        # Get layer IDs from the map
        layer_ids = map_rec["layers"] if map_rec["layers"] else []

        # Load layers using the layer IDs
        if layer_ids:
            placeholders = ", ".join(["%s"] * len(layer_ids))
            cursor.execute(
                f"""
                SELECT layer_id AS id,
                       name,
                       path,
                       type,
                       raster_cog_url,
                       metadata,
                       bounds,
                       geometry_type,
                       feature_count
                FROM map_layers
                WHERE layer_id IN ({placeholders})
                ORDER BY id
                """,
                layer_ids,
            )
            layers = cursor.fetchall()
            for layer in layers:
                if layer.get("metadata") and isinstance(layer["metadata"], str):
                    layer["metadata"] = json.loads(layer["metadata"])
        else:
            layers = []
        # Calculate diff if prev_map_id is provided
        layer_diffs = None
        if prev_map_id:
            user_id = session.get_user_id() if session else map_rec["owner_uuid"]

            # Get previous map layers with their style IDs
            cursor.execute(
                """
                SELECT ml.layer_id, ml.name, ml.type, ml.metadata, ml.geometry_type, ml.feature_count,
                       mls.style_id
                FROM user_mundiai_maps m
                JOIN map_layers ml ON ml.layer_id = ANY(m.layers)
                LEFT JOIN map_layer_styles mls ON mls.map_id = m.id AND mls.layer_id = ml.layer_id
                WHERE m.id = %s AND m.owner_uuid = %s AND m.soft_deleted_at IS NULL
                """,
                (prev_map_id, user_id),
            )
            prev_layers = {row["layer_id"]: row for row in cursor.fetchall()}

            # Get current map layers with their style IDs
            cursor.execute(
                """
                SELECT ml.layer_id, ml.name, ml.type, ml.metadata, ml.geometry_type, ml.feature_count,
                       mls.style_id
                FROM user_mundiai_maps m
                JOIN map_layers ml ON ml.layer_id = ANY(m.layers)
                LEFT JOIN map_layer_styles mls ON mls.map_id = m.id AND mls.layer_id = ml.layer_id
                WHERE m.id = %s AND m.owner_uuid = %s AND m.soft_deleted_at IS NULL
                """,
                (map_id, user_id),
            )
            new_layers = {row["layer_id"]: row for row in cursor.fetchall()}

            # Calculate diffs
            layer_diffs = []
            all_layer_ids = set(new_layers.keys()) | set(prev_layers.keys())

            for layer_id in all_layer_ids:
                new_layer = new_layers.get(layer_id)
                prev_layer = prev_layers.get(layer_id)

                if new_layer and not prev_layer:
                    # Added layer
                    layer_diffs.append(
                        {
                            "layer_id": layer_id,
                            "name": new_layer["name"],
                            "status": "added",
                        }
                    )
                elif prev_layer and not new_layer:
                    # Removed layer
                    layer_diffs.append(
                        {
                            "layer_id": layer_id,
                            "name": prev_layer["name"],
                            "status": "removed",
                        }
                    )
                elif new_layer and prev_layer:
                    # Check for changes
                    changes = {}
                    if new_layer["name"] != prev_layer["name"]:
                        changes["name"] = {
                            "old": prev_layer["name"],
                            "new": new_layer["name"],
                        }
                    if new_layer["metadata"] != prev_layer["metadata"]:
                        changes["metadata"] = {
                            "old": prev_layer["metadata"],
                            "new": new_layer["metadata"],
                        }
                    if new_layer["style_id"] != prev_layer["style_id"]:
                        changes["style_id"] = {
                            "old": prev_layer["style_id"],
                            "new": new_layer["style_id"],
                        }

                    if changes:
                        layer_diffs.append(
                            {
                                "layer_id": layer_id,
                                "name": new_layer["name"],
                                "status": "edited",
                                "changes": changes,
                            }
                        )
                    else:
                        layer_diffs.append(
                            {
                                "layer_id": layer_id,
                                "name": new_layer["name"],
                                "status": "existing",
                            }
                        )
        elif diff_map_id == "auto" and proj_maps and map_id == proj_maps[0]:
            # If this is the first map in the project and auto diff is requested,
            # mark all layers as added
            layer_diffs = []
            for layer in layers:
                layer_diffs.append(
                    {
                        "layer_id": layer["id"],
                        "name": layer["name"],
                        "status": "added",
                    }
                )

        # Return JSON payload
        response = {
            "map_id": map_id,
            "project_id": project_id,
            "layers": layers,
            "changelog": changelog,
            "display_as_diff": map_rec["display_as_diff"],
        }

        if layer_diffs is not None:
            response["diff"] = {
                "prev_map_id": prev_map_id,
                "new_map_id": map_id,
                "layer_diffs": layer_diffs,
            }

        return response


@router.get(
    "/{map_id}/layers",
    operation_id="list_map_layers",
    response_model=LayersListResponse,
)
async def get_map_layers(
    request: Request,
    map_id: str,
    session: UserContext = Depends(verify_session_optional),
):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # First check if the map exists and is accessible
        cursor.execute(
            """
            SELECT m.id, p.link_accessible, m.owner_uuid, m.layers
            FROM user_mundiai_maps m
            JOIN user_mundiai_projects p ON m.project_id = p.id
            WHERE m.id = %s AND m.soft_deleted_at IS NULL
            """,
            (map_id,),
        )

        map_result = cursor.fetchone()
        if not map_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
            )

        # Check if map is publicly accessible
        if not map_result["link_accessible"]:
            # If not publicly accessible, verify that we have auth
            if session is None or session.get_user_id() != map_result["owner_uuid"]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        # Get layer IDs from the map
        layer_ids = map_result["layers"]

        if not layer_ids:
            layers = []
        else:
            # Get all layers by their IDs
            placeholders = ",".join(["%s"] * len(layer_ids))
            cursor.execute(
                f"""
                SELECT layer_id as id, name, path, type, raster_cog_url, metadata, bounds, geometry_type, feature_count
                FROM map_layers
                WHERE layer_id IN ({placeholders})
                ORDER BY id
                """,
                layer_ids,
            )

            # Get all layers
            layers = cursor.fetchall()

        # Process metadata JSON and add feature_count for vector layers if possible
        for layer in layers:
            if layer["metadata"] is not None:
                # Convert metadata from JSON string to Python dict if needed
                if isinstance(layer["metadata"], str):
                    layer["metadata"] = json.loads(layer["metadata"])

            # Set feature_count from metadata if it exists
            if (
                "metadata" in layer
                and layer["metadata"]
                and "feature_count" in layer["metadata"]
            ):
                layer["feature_count"] = layer["metadata"]["feature_count"]

        # Return the layers
        return LayersListResponse(map_id=map_id, layers=layers)


@router.get(
    "/{map_id}/describe",
    operation_id="get_map_description",
)
async def get_map_description(
    request: Request,
    map_id: str,
    session: UserContext = Depends(verify_session_required),
    postgis_provider: Callable = Depends(get_postgis_provider),
    layer_describer: LayerDescriber = Depends(get_layer_describer),
):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # First check if the map exists and is accessible
        cursor.execute(
            """
            SELECT id, title, description, owner_uuid
            FROM user_mundiai_maps
            WHERE id = %s AND soft_deleted_at IS NULL
            """,
            (map_id,),
        )

        map_result = cursor.fetchone()
        if not map_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
            )

        # User must own the map to access this endpoint
        if session.get_user_id() != map_result["owner_uuid"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must own this map to access map description",
            )

        content = []

        # Get PostgreSQL connections for this map's project
        cursor.execute(
            """
            SELECT ppc.id, ppc.connection_uri, ppc.connection_name,
                   pps.friendly_name
            FROM project_postgres_connections ppc
            JOIN user_mundiai_maps m ON ppc.project_id = m.project_id
            LEFT JOIN project_postgres_summary pps ON pps.connection_id = ppc.id
            WHERE m.id = %s
            ORDER BY ppc.connection_name
            """,
            (map_id,),
        )

        postgres_connections = cursor.fetchall()

        # Add PostgreSQL connection data to content
        for connection in postgres_connections:
            try:
                # Get tables from this PostgreSQL connection
                tables = await postgis_provider(connection["connection_uri"])

                # Use AI-generated friendly name if available, otherwise fallback to connection_name or "Loading..."
                connection_name = (
                    connection["friendly_name"]
                    or connection["connection_name"]
                    or "Loading..."
                )
                content.append(
                    f'\n## PostGIS "{connection_name}" (ID {connection["id"]})\n'
                )
                content.append("**Available Tables:** " + tables)

            except Exception:
                continue

        # Get all layers for this map
        cursor.execute(
            """
            SELECT ml.layer_id, ml.name, ml.type
            FROM map_layers ml
            JOIN user_mundiai_maps m ON ml.layer_id = ANY(m.layers)
            WHERE m.id = %s
            ORDER BY ml.name
            """,
            (map_id,),
        )

        layers = cursor.fetchall()

        # Generate comprehensive description
        content.append(f"# Map: {map_result['title']}\n")

        if map_result["description"]:
            content.append(f"{map_result['description']}\n")

        # Process each layer with XML tags
        for layer in layers:
            # Get detailed description for each layer
            layer_description = await describe_layer_internal(
                layer["layer_id"], layer_describer, session.get_user_id()
            )

            # Add layer with XML tags
            content.append(f"<{layer['layer_id']}>")
            content.append(layer_description)
            content.append(f"</{layer['layer_id']}>")

        # Join all content and return as plain text response
        response_content = "\n".join(content)

        return Response(
            content=response_content,
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{map_result["title"]}_description.txt"',
            },
        )


@router.get(
    "/{map_id}/style.json",
    operation_id="get_map_stylejson",
    response_class=StarletteJSONResponse,
)
async def get_map_style(
    request: Request,
    map_id: str,
    only_show_inline_sources: bool = False,
    session: UserContext = Depends(verify_session_optional),
    override_layers: Optional[str] = None,
    base_map: BaseMapProvider = Depends(get_base_map_provider),
):
    # Get vector layers for this map from the database
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # First check if the map exists and is accessible
        cursor.execute(
            """
            SELECT m.id, p.link_accessible, m.owner_uuid, m.layers
            FROM user_mundiai_maps m
            JOIN user_mundiai_projects p ON m.project_id = p.id
            WHERE m.id = %s AND m.soft_deleted_at IS NULL
            """,
            (map_id,),
        )

        map_result = cursor.fetchone()
        if not map_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
            )

        # Check if map is publicly accessible
        if not map_result["link_accessible"]:
            # If not publicly accessible, verify that we have auth
            if session is None or session.get_user_id() != map_result["owner_uuid"]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    return await get_map_style_internal(
        map_id, base_map, only_show_inline_sources, override_layers
    )


async def get_map_style_internal(
    map_id: str,
    base_map: BaseMapProvider,
    only_show_inline_sources: bool = False,
    override_layers: Optional[str] = None,
):
    # Get vector layers for this map from the database
    async with get_async_db_connection() as conn:
        # Get layers from the map
        map_result = await conn.fetchrow(
            """
            SELECT layers
            FROM user_mundiai_maps
            WHERE id = $1 AND soft_deleted_at IS NULL
            """,
            map_id,
        )

        if map_result is None:
            raise HTTPException(status_code=404, detail="Map not found")

        # Get layers from the layer list
        layer_ids = map_result["layers"]
        if not layer_ids:
            all_layers = []
        else:
            # Fetch metadata as well to check for cog_url_suffix
            placeholders = ",".join(f"${i + 2}" for i in range(len(layer_ids)))
            all_layers = await conn.fetch(
                f"""
                SELECT ml.layer_id, ml.name, ml.type, ls.style_json as maplibre_layers, ml.raster_cog_url, ml.feature_count, ml.bounds, ml.metadata, ml.geometry_type
                FROM map_layers ml
                LEFT JOIN map_layer_styles mls ON ml.layer_id = mls.layer_id AND mls.map_id = $1
                LEFT JOIN layer_styles ls ON mls.style_id = ls.style_id
                WHERE ml.layer_id IN ({placeholders})
                ORDER BY ml.id
                """,
                map_id,
                *layer_ids,
            )

        vector_layers = [layer for layer in all_layers if layer["type"] == "vector"]
        # Filter for raster layers; the .cog.tif endpoint handles generation if needed
        raster_layers = [layer for layer in all_layers if layer["type"] == "raster"]
        postgis_layers = [layer for layer in all_layers if layer["type"] == "postgis"]

        def get_geometry_order(layer):
            geom_type = layer.get("geometry_type", "").lower()
            if "polygon" in geom_type:
                return 1
            elif "line" in geom_type:
                return 2
            elif "point" in geom_type:
                return 3
            return 4  # ??

        vector_layers.sort(key=get_geometry_order)
        postgis_layers.sort(key=get_geometry_order)

    style_json = await base_map.get_base_style()

    # compute combined WGS84 bounds from all_layers and derive center + zoom with 20% padding
    bounds_list = [layer["bounds"] for layer in all_layers if layer.get("bounds")]
    ZOOM_PADDING_PCT = 25
    if bounds_list:
        xs = [b[0] for b in bounds_list] + [b[2] for b in bounds_list]
        ys = [b[1] for b in bounds_list] + [b[3] for b in bounds_list]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        # apply 1/2 padding on each side
        pad_x = (max_x - min_x) * ZOOM_PADDING_PCT / 100
        pad_y = (max_y - min_y) * ZOOM_PADDING_PCT / 100
        min_x -= pad_x
        max_x += pad_x
        min_y -= pad_y
        max_y += pad_y
        # final bounds and center
        style_json["center"] = [(min_x + max_x) / 2, (min_y + max_y) / 2]
        # calculate zoom to fit both longitude and latitude spans
        lon_span = max_x - min_x
        lat_span = max_y - min_y
        zoom_lon = math.log2(360.0 / lon_span) if lon_span else None
        zoom_lat = math.log2(180.0 / lat_span) if lat_span else None
        # use the smaller zoom level to ensure both dimensions fit
        zoom = (
            min(zoom_lon, zoom_lat) if zoom_lon and zoom_lat else zoom_lon or zoom_lat
        )
        if zoom is not None and zoom > 0.0:
            style_json["zoom"] = zoom

    if override_layers is not None:
        override_layers = json.loads(override_layers)

    # If no sources in the style, initialize it
    if "sources" not in style_json:
        style_json["sources"] = {}

    # Add COG raster layers to the style if not only showing inline sources
    if not only_show_inline_sources:
        for idx, layer in enumerate(raster_layers, 1):
            layer_id = layer["layer_id"]
            source_id = f"cog-source-{layer_id}"
            cog_url = f"cog:///api/layer/{layer_id}.cog.tif"

            # Generate suffix from raster_value_stats_b1
            metadata = json.loads(layer.get("metadata", "{}"))
            if metadata and "raster_value_stats_b1" in metadata:
                min_val = metadata["raster_value_stats_b1"]["min"]
                max_val = metadata["raster_value_stats_b1"]["max"]
                cog_url += f"#color:BrewerSpectral9,{min_val},{max_val},c"

            style_json["sources"][source_id] = {
                "type": "raster",
                "url": cog_url,
                "tileSize": 256,
            }
            style_json["layers"].append(
                {
                    "id": f"raster-layer-{layer_id}",
                    "type": "raster",
                    "source": source_id,
                }
            )

    # Add vector layers as sources and layers to the style
    for idx, layer in enumerate(vector_layers, 1):
        layer_id = layer["layer_id"]

        # Use GeoJSON or PMTiles based on the only_show_inline_sources parameter
        if only_show_inline_sources:
            # For rendering, also get a presigned URL for PMTiles if available
            metadata = json.loads(layer.get("metadata", "{}"))
            pmtiles_key = metadata.get("pmtiles_key")
            assert pmtiles_key is not None

            bucket_name = get_bucket_name()
            s3_client = get_s3_client()

            presigned_url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket_name, "Key": pmtiles_key},
                ExpiresIn=180,  # URL valid for 3 minutes
            )

            style_json["sources"][layer_id] = {
                "type": "vector",
                "url": f"pmtiles://{presigned_url}",
            }
        else:
            # Default to PMTiles
            style_json["sources"][layer_id] = {
                "type": "vector",
                "url": f"pmtiles:///api/layer/{layer_id}.pmtiles",
            }

        # Check if override_layers is not None
        if override_layers is not None and layer_id in override_layers:
            for ml_layer in override_layers[layer_id]:
                # source-layer is prohibited for geojson sources
                if style_json["sources"][layer_id]["type"] == "geojson":
                    assert ml_layer["source-layer"] == "reprojectedfgb"
                    del ml_layer["source-layer"]
                    assert "source-layer" not in ml_layer
                style_json["layers"].append(ml_layer)
        # Use stored style_json from layer_styles if no override_layers
        elif layer["maplibre_layers"]:
            for ml_layer in json.loads(layer["maplibre_layers"]):
                style_json["layers"].append(ml_layer)

    for layer in postgis_layers:
        if layer["type"] == "postgis":
            layer_id = layer["layer_id"]

            style_json["sources"][layer_id] = {
                "type": "vector",
                "tiles": [
                    f"{os.getenv('WEBSITE_DOMAIN')}/api/layer/{layer_id}/{{z}}/{{x}}/{{y}}.mvt"
                ],
                "minzoom": 0,
                "maxzoom": 17,
            }

            # Check if override_layers is not None
            if override_layers is not None and layer_id in override_layers:
                for ml_layer in override_layers[layer_id]:
                    style_json["layers"].append(ml_layer)
            # Use stored style_json from layer_styles if no override_layers
            elif layer["maplibre_layers"]:
                for ml_layer in json.loads(layer["maplibre_layers"]):
                    style_json["layers"].append(ml_layer)

    # We use globe
    style_json["projection"] = {
        "type": "globe",
    }

    # Add pointer positions source and layers for real-time collaboration
    style_json["sources"]["pointer-positions"] = {
        "type": "geojson",
        "data": {"type": "FeatureCollection", "features": []},
    }

    # Add cursor layer
    style_json["layers"].append(
        {
            "id": "pointer-cursors",
            "type": "symbol",
            "source": "pointer-positions",
            "layout": {
                "icon-image": "remote-cursor",
                "icon-size": 0.45,
                "icon-allow-overlap": True,
            },
        }
    )

    # Add labels layer
    style_json["layers"].append(
        {
            "id": "pointer-labels",
            "type": "symbol",
            "source": "pointer-positions",
            "layout": {
                "text-field": ["get", "abbrev"],
                "text-offset": [1, 1],
                "text-anchor": "top-left",
                "text-size": 11,
                "text-allow-overlap": True,
                "text-ignore-placement": True,
            },
            "paint": {
                "text-color": "#000000",
                "text-halo-color": "#FFFFFF",
                "text-halo-width": 1,
            },
        }
    )

    # Return the augmented style
    return style_json


@router.post(
    "/{map_id}/layers",
    response_model=LayerUploadResponse,
    operation_id="upload_layer_to_map",
)
async def upload_layer(
    request: Request,
    map_id: str,
    file: UploadFile = File(...),
    layer_name: str = Form(None),
    add_layer_to_map: bool = Form(True),
    session: UserContext = Depends(verify_session_required),
):
    """Upload a new layer (vector or raster) to an existing map. If layer_name is not provided, the filename without extension will be used."""

    # Connect to database
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # First check if the map exists and user owns it, then get its project_id
        cursor.execute(
            """
            SELECT m.id, m.project_id
            FROM user_mundiai_maps m
            WHERE m.id = %s AND m.owner_uuid = %s AND m.soft_deleted_at IS NULL
            """,
            (map_id, session.get_user_id()),
        )

        map_result = cursor.fetchone()
        if not map_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
            )

        bucket_name = get_bucket_name()
        project_id = map_result["project_id"]

        # Generate a unique filename for the uploaded file
        filename = file.filename
        file_basename, file_ext = os.path.splitext(filename)
        file_ext = file_ext.lower()

        # If layer_name is not provided, use the filename without extension
        if not layer_name:
            layer_name = file_basename
        # Determine layer type based on file extension
        layer_type = "vector"
        if file_ext in [".tif", ".tiff", ".jpg", ".jpeg", ".png", ".dem"]:
            layer_type = "raster"
            if not file_ext:
                file_ext = ".tif"  # Default raster extension
        else:
            if not file_ext:
                file_ext = ".geojson"  # Default vector extension

        # Initialize metadata dictionary
        metadata_dict = {"original_filename": filename}

        # Generate a unique layer ID
        layer_id = generate_id(prefix="L")

        # Generate S3 key using user UUID, project ID and layer ID
        s3_key = f"uploads/{session.get_user_id()}/{project_id}/{layer_id}{file_ext}"

        # Create S3 client
        s3_client = get_s3_client()
        bucket_name = get_bucket_name()

        # Save uploaded file to a temporary location
        # Preserve original file extension for GDAL/OGR format detection
        filename = file.filename
        file_ext = os.path.splitext(filename)[1].lower()

        with tempfile.NamedTemporaryFile(suffix=file_ext) as temp_file:
            # Read file content
            content = await file.read()
            # Track file size in bytes
            file_size_bytes = len(content)
            # Write to temp file
            temp_file.write(content)
            temp_file_path = temp_file.name

            # If this is a ZIP file, process it for shapefiles and convert to GeoPackage
            temp_dir = None
            if file_ext.lower() == ".zip":
                try:
                    # Process the ZIP file to extract and convert shapefiles to GeoPackage
                    gpkg_file_path, temp_dir = process_zip_with_shapefile(
                        temp_file_path
                    )

                    # Update file path and extension to use the converted GeoPackage
                    temp_file_path = gpkg_file_path
                    file_ext = ".gpkg"

                    # Update S3 key to reflect the new file type
                    unique_filename = f"{uuid.uuid4()}.gpkg"
                    s3_key = f"uploads/{map_id}/{unique_filename}"

                    # Update metadata to indicate this was converted from a shapefile
                    metadata_dict.update(
                        {
                            "original_format": "shapefile_zip",
                            "converted_to": "gpkg",
                        }
                    )

                    # Update layer type
                    layer_type = "vector"
                except ValueError as e:
                    print(f"Error processing ZIP file: {str(e)}")
                    # If no shapefile is found in the ZIP, raise an error
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"ZIP file does not contain any shapefiles: {str(e)}",
                    )
                except Exception as e:
                    print(f"Error processing ZIP file: {str(e)}")
                    # Clean up temp directory if it exists
                    if temp_dir:
                        import shutil

                        shutil.rmtree(temp_dir, ignore_errors=True)
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Error processing ZIP file: {str(e)}",
                    )

            # Upload file to S3/MinIO
            s3_client.upload_file(temp_file_path, bucket_name, s3_key)

            # Generate a presigned URL for the file
            presigned_url = s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": bucket_name, "Key": s3_key},
                ExpiresIn=3600 * 24 * 7,  # 1 week
            )

            # No need to rewrite URL - host networking ensures hostname consistency

            # Additional processing for raster layers
            raster_cog_url = None
            if layer_type == "raster":
                # For raster files, we could convert to COG here
                # For now, we'll just use the same URL for both fields
                raster_cog_url = presigned_url

            # Get layer bounds using GDAL
            bounds = None
            geometry_type = "unknown"
            feature_count = None
            # Special handling for XYZ layers and example.com test URLs
            if "type=xyz&" in presigned_url or "example.com" in presigned_url:
                bounds = None
            elif layer_type == "raster":
                # Use GDAL to get bounds for raster files
                ds = gdal.Open(temp_file_path)
                if ds:
                    gt = ds.GetGeoTransform()
                    width = ds.RasterXSize
                    height = ds.RasterYSize

                    # Calculate corner coordinates
                    xmin = gt[0]
                    ymax = gt[3]
                    xmax = gt[0] + width * gt[1] + height * gt[2]
                    ymin = gt[3] + width * gt[4] + height * gt[5]

                    bounds = [xmin, ymin, xmax, ymax]

                    # Check if CRS is not EPSG:4326
                    src_crs = ds.GetProjection()
                    if (
                        src_crs
                        and "EPSG:4326" not in src_crs
                        and "WGS84" not in src_crs
                    ):
                        # Create transformer from source CRS to WGS84
                        src_srs = osr.SpatialReference()
                        src_srs.ImportFromWkt(src_crs)
                        transformer = Transformer.from_crs(
                            src_srs.ExportToProj4(), "EPSG:4326", always_xy=True
                        )

                        # Transform the bounds
                        xmin, ymin = transformer.transform(bounds[0], bounds[1])
                        xmax, ymax = transformer.transform(bounds[2], bounds[3])

                        bounds = [xmin, ymin, xmax, ymax]

                    # Get statistics for single-band rasters
                    if ds.RasterCount == 1:
                        try:
                            band = ds.GetRasterBand(1)
                            # ComputeStatistics(approx_ok, force)
                            stats = band.ComputeStatistics(
                                False
                            )  # [min, max, mean, stdev]
                            min_val, max_val = stats[0], stats[1]
                            metadata_dict["raster_value_stats_b1"] = {
                                "min": min_val,
                                "max": max_val,
                            }
                        except Exception as e:
                            print(f"Error computing raster statistics: {str(e)}")

                    # Close dataset
                    ds = None
            else:
                # Get bounds from vector file and detect geometry type
                with fiona.open(temp_file_path) as collection:
                    try:
                        # Fiona bounds are returned as (minx, miny, maxx, maxy)
                        bounds = list(collection.bounds)
                        # Get feature count
                        feature_count = len(collection)

                        # Detect geometry type
                        # Try to get the geometry type from schema
                        if collection.schema and "geometry" in collection.schema:
                            geom_type = collection.schema["geometry"]
                            # Normalize geometry type names to lowercase
                            geometry_type = (
                                geom_type.lower() if geom_type else "unknown"
                            )

                            # If there are features, check the first feature for actual geometry type
                            if len(collection) > 0:
                                first_feature = next(iter(collection))
                                if (
                                    first_feature
                                    and "geometry" in first_feature
                                    and "type" in first_feature["geometry"]
                                ):
                                    actual_type = first_feature["geometry"][
                                        "type"
                                    ].lower()
                                    # Update if the actual type is more specific
                                    if actual_type and actual_type != "null":
                                        geometry_type = actual_type
                    except Exception as e:
                        print(f"Error detecting geometry type: {str(e)}")
                        geometry_type = "unknown"

                    # Check if we need to transform coordinates to EPSG:4326
                    src_crs = collection.crs
                    crs_string = src_crs.to_string()

                    # Check if CRS is not EPSG:4326
                    if (
                        src_crs
                        and "EPSG:4326" not in crs_string
                        and "WGS84" not in crs_string
                        and bounds is not None
                    ):
                        # Create transformer from source CRS to WGS84 (EPSG:4326)
                        transformer = Transformer.from_crs(
                            src_crs, "EPSG:4326", always_xy=True
                        )

                        # Transform the bounds
                        xmin, ymin = transformer.transform(bounds[0], bounds[1])
                        xmax, ymax = transformer.transform(bounds[2], bounds[3])

                        bounds = [xmin, ymin, xmax, ymax]

            # For vector layers, add geometry_type and feature_count to metadata
            if layer_type == "vector":
                if geometry_type != "unknown":
                    metadata_dict["geometry_type"] = geometry_type
                if feature_count is not None:
                    metadata_dict["feature_count"] = feature_count

            # Generate MapLibre layers for vector layers
            maplibre_layers = None
            if layer_type == "vector" and geometry_type:
                maplibre_layers = generate_maplibre_layers_for_layer_id(
                    layer_id, geometry_type
                )

            cursor.execute(
                """
                INSERT INTO map_layers
                (layer_id, owner_uuid, name, path, type, raster_cog_url, metadata, bounds, geometry_type, feature_count, s3_key, size_bytes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING layer_id
                """,
                (
                    layer_id,
                    session.get_user_id(),
                    layer_name,
                    presigned_url,
                    layer_type,
                    raster_cog_url,
                    psycopg2.extras.Json(metadata_dict),
                    bounds,
                    geometry_type if layer_type == "vector" else None,
                    feature_count,
                    s3_key,
                    file_size_bytes,
                ),
            )

            new_layer_id = cursor.fetchone()["layer_id"]

            # If adding layer to map, update the map with the new layer
            if add_layer_to_map:
                # First get the current layers array
                cursor.execute(
                    """
                    SELECT layers FROM user_mundiai_maps
                    WHERE id = %s
                    """,
                    (map_id,),
                )
                map_data = cursor.fetchone()
                current_layers = (
                    map_data["layers"] if map_data and map_data["layers"] else []
                )

                # Then update with the new layer appended
                cursor.execute(
                    """
                    UPDATE user_mundiai_maps
                    SET layers = %s,
                        last_edited = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (current_layers + [new_layer_id], map_id),
                )

            # Commit changes
            conn.commit()

            # Create direct URL for the layer based on type
            layer_url = (
                f"/api/layer/{new_layer_id}.pmtiles"
                if layer_type == "vector"
                else f"/api/layer/{new_layer_id}.cog.tif"
            )

            # If this is a vector layer, create a style for it
            if layer_type == "vector" and geometry_type:
                maplibre_layers = generate_maplibre_layers_for_layer_id(
                    new_layer_id, geometry_type
                )

                # Create a default style entry
                style_id = generate_id(prefix="S")
                cursor.execute(
                    """
                    INSERT INTO layer_styles
                    (style_id, layer_id, style_json, created_by)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        style_id,
                        new_layer_id,
                        psycopg2.extras.Json(maplibre_layers),
                        session.get_user_id(),
                    ),
                )

                # Link the style to the map
                cursor.execute(
                    """
                    INSERT INTO map_layer_styles (map_id, layer_id, style_id)
                    VALUES (%s, %s, %s)
                    """,
                    (map_id, new_layer_id, style_id),
                )
                conn.commit()

                # Generate PMTiles for vector layers
                if feature_count is not None and feature_count > 0:
                    # Generate PMTiles asynchronously
                    pmtiles_key = await generate_pmtiles_for_layer(
                        new_layer_id,
                        s3_key,
                        feature_count,
                        session.get_user_id(),
                        project_id,
                    )

                    # Update metadata with PMTiles key
                    cursor.execute(
                        """
                        SELECT metadata FROM map_layers
                        WHERE layer_id = %s
                        """,
                        (new_layer_id,),
                    )
                    result = cursor.fetchone()
                    metadata = result["metadata"] or {}
                    metadata["pmtiles_key"] = pmtiles_key

                    # Update the database
                    cursor.execute(
                        """
                        UPDATE map_layers
                        SET metadata = %s
                        WHERE layer_id = %s
                        """,
                        (psycopg2.extras.Json(metadata), new_layer_id),
                    )
                    conn.commit()

            # Cleanup temp_dir if it exists
            if temp_dir:
                import shutil

                shutil.rmtree(temp_dir, ignore_errors=True)

            # Return success response
            return LayerUploadResponse(
                id=new_layer_id, name=layer_name, type=layer_type, url=layer_url
            )


# Create a separate router for layer-specific endpoints
layer_router = APIRouter()


@layer_router.get(
    "/layer/{layer_id}.cog.tif",
    operation_id="view_layer_as_cog_tif",
)
async def get_layer_cog_tif(
    layer_id: str,
    request: Request,
    session: UserContext = Depends(verify_session_required),
):
    """
    Stream a Cloud Optimized GeoTIFF (COG) directly from S3 for a raster layer.
    This route allows direct access to the layer without requiring a map prefix.
    If the COG doesn't exist yet, it will be created on-the-fly.
    """
    # Connect to database
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Get the layer by layer_id
        cursor.execute(
            """
            SELECT layer_id, name, path, type, raster_cog_url, metadata, feature_count, s3_key
            FROM map_layers
            WHERE layer_id = %s
            """,
            (layer_id,),
        )

        layer = cursor.fetchone()
        if not layer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found"
            )

        # Check if layer is a raster type
        if layer["type"] != "raster":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Layer is not a raster type. COG can only be generated from raster data.",
            )

        # Check if layer is associated with any maps via the layers array
        cursor.execute(
            """
            SELECT m.id, p.link_accessible, m.owner_uuid
            FROM user_mundiai_maps m
            JOIN user_mundiai_projects p ON m.project_id = p.id
            WHERE %s = ANY(m.layers) AND m.soft_deleted_at IS NULL
            """,
            (layer_id,),
        )

        map_result = cursor.fetchone()
        if map_result and not map_result["link_accessible"]:
            # If not publicly accessible, verify that we have auth
            if session.get_user_id() != map_result["owner_uuid"]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        # Continue with the same implementation as the map-scoped endpoint
        bucket_name = get_bucket_name()

        # Check if metadata has cog_key
        metadata = layer["metadata"] or {}
        cog_key = metadata.get("cog_key")

        # Set up MinIO/S3 client
        s3_client = get_s3_client()

        # If COG doesn't exist, create it
        if not cog_key:
            with tempfile.TemporaryDirectory() as temp_dir:
                # Download the raster file
                s3_key = layer["s3_key"]
                file_extension = os.path.splitext(s3_key)[1]
                local_input_file = os.path.join(
                    temp_dir, f"layer_{layer_id}{file_extension}"
                )

                # Download from S3 using async client
                s3 = await get_async_s3_client()
                await s3.download_file(bucket_name, s3_key, local_input_file)
                # Create COG file path
                local_cog_file = os.path.join(temp_dir, f"layer_{layer_id}.cog.tif")

                # Check raster info (needed for band count)
                gdalinfo_cmd = ["gdalinfo", "-json", local_input_file]
                try:
                    gdalinfo_result = subprocess.run(
                        gdalinfo_cmd, check=True, capture_output=True, text=True
                    )
                    gdalinfo_json = json.loads(gdalinfo_result.stdout)
                except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
                    logger.error(
                        f"Failed to get gdalinfo for {layer_id}: {e}", exc_info=True
                    )
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to process raster info for layer {layer_id}.",
                    )

                # Always attempt reprojection to EPSG:3857 (gdalwarp is a no-op if already in 3857)
                reprojected_file_path = os.path.join(
                    temp_dir, f"layer_{layer_id}_3857.tif"
                )
                gdalwarp_cmd = [
                    "gdalwarp",
                    "-t_srs",
                    "EPSG:3857",
                    "-r",
                    "bilinear",  # resampling method
                    local_input_file,
                    reprojected_file_path,
                ]
                try:
                    print(f"INFO: Running gdalwarp for layer {layer_id} to EPSG:3857.")
                    subprocess.run(
                        gdalwarp_cmd, check=True, capture_output=True, text=True
                    )
                    input_file_for_cog = reprojected_file_path
                    print(
                        f"INFO: Layer {layer_id} successfully processed/reprojected to EPSG:3857."
                    )
                except subprocess.CalledProcessError as e:
                    print(
                        f"ERROR: gdalwarp failed for layer {layer_id}: {e.stderr}. Using original file for COG creation."
                    )
                    # Fallback to original file if reprojection fails
                    input_file_for_cog = local_input_file

                # Get band count from the original gdalinfo output
                num_bands = len(gdalinfo_json.get("bands", []))
                needs_color_ramp_suffix = False

                if num_bands == 1:
                    try:
                        # Try expanding to RGB first
                        local_rgb_file = os.path.join(
                            temp_dir, f"layer_{layer_id}_rgb.tif"
                        )
                        rgb_cmd = [
                            "gdal_translate",
                            "-of",
                            "GTiff",
                            "-expand",
                            "rgb",
                            local_input_file,
                            local_rgb_file,
                        ]
                        subprocess.run(
                            rgb_cmd, check=True, capture_output=True, text=True
                        )
                        input_file_for_cog = local_rgb_file
                        print(f"INFO: Expanded single band to RGB for layer {layer_id}")
                    except subprocess.CalledProcessError as e:
                        print(
                            f"WARN: gdal_translate -expand rgb failed for layer {layer_id}: {e.stderr}. Using single-band with color ramp."
                        )
                        # Use the existing raster_value_stats_b1 from metadata
                        if "raster_value_stats_b1" in metadata:
                            needs_color_ramp_suffix = True
                            print(
                                f"INFO: Using existing raster_value_stats_b1 for layer {layer_id}"
                            )
                        # Keep input_file_for_cog as the original single-band file

                # Convert to Cloud Optimized GeoTIFF
                cog_cmd_base = [
                    "gdal_translate",
                    "-of",
                    "COG",
                    "-co",
                    "BLOCKSIZE=256",
                ]
                if needs_color_ramp_suffix:
                    cog_cmd_base.extend(["-ot", "Float32"])
                    cog_cmd_compression = ["-co", "COMPRESS=LZW"]
                else:
                    cog_cmd_compression = ["-co", "COMPRESS=JPEG", "-co", "QUALITY=85"]

                cog_cmd = (
                    cog_cmd_base
                    + cog_cmd_compression
                    + [
                        "-co",
                        "OVERVIEWS=AUTO",
                        input_file_for_cog,
                        local_cog_file,
                    ]
                )

                try:
                    subprocess.run(cog_cmd, check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as e:
                    error_detail = f"COG generation failed. Command: {' '.join(e.cmd)}\nStderr: {e.stderr}\nStdout: {e.stdout}"
                    print(f"ERROR: {error_detail}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"COG generation failed: {e.stderr or 'Unknown GDAL error'}",
                    )

                # Upload the COG file to S3
                cog_key = f"cog/layer/{layer_id}.cog.tif"
                s3 = await get_async_s3_client()
                await s3.upload_file(local_cog_file, bucket_name, cog_key)
                print(f"INFO: Uploaded COG to s3://{bucket_name}/{cog_key}")

                # Update the layer metadata with the COG key
                metadata["cog_key"] = cog_key

                # Update the database
                cursor.execute(
                    """
                    UPDATE map_layers
                    SET metadata = %s
                    WHERE layer_id = %s
                    """,
                    (psycopg2.extras.Json(metadata), layer_id),
                )
                conn.commit()
                print(f"INFO: Updated metadata for layer {layer_id}", metadata)

        # Ensure cog_key is available if it was just generated
        if not cog_key:
            cog_key = metadata.get("cog_key")
            if not cog_key:
                # This case should ideally not be reached if generation logic is sound
                raise HTTPException(
                    status_code=500, detail="COG key missing after generation attempt."
                )

        # Get the file size first to handle range requests
        s3_head = s3_client.head_object(Bucket=bucket_name, Key=cog_key)
        file_size = s3_head["ContentLength"]

        # Check for Range header to support byte serving
        range_header = request.headers.get("range", None) if request else None
        start_byte = 0
        end_byte = file_size - 1

        # Parse the Range header if present
        if range_header:
            range_match = re.search(r"bytes=(\d+)-(\d*)", range_header)
            if range_match:
                start_byte = int(range_match.group(1))
                end_group = range_match.group(2)
                if end_group:
                    end_byte = min(int(end_group), file_size - 1)
                else:
                    end_byte = file_size - 1

            # Calculate content length for the range
            content_length = end_byte - start_byte + 1

            # Get the specified range from S3
            s3_response = s3_client.get_object(
                Bucket=bucket_name,
                Key=cog_key,
                Range=f"bytes={start_byte}-{end_byte}",
            )

            # Set response status and headers for partial content
            status_code = 206  # Partial Content
            headers = {
                "Content-Range": f"bytes {start_byte}-{end_byte}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "Content-Type": "image/tiff",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Range, Content-Type",
            }
        else:
            # Get the entire file
            s3_response = s3_client.get_object(Bucket=bucket_name, Key=cog_key)
            status_code = 200
            headers = {
                "Content-Length": str(file_size),
                "Content-Type": "image/tiff",
                "Accept-Ranges": "bytes",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Range, Content-Type",
            }

        # Create an async generator to stream the file
        async def stream_s3_file():
            # Get the body of the S3 object (this is a stream)
            body = s3_response["Body"]

            # Stream the content in chunks
            chunk_size = 8192  # 8KB chunks
            while True:
                chunk = body.read(chunk_size)
                if not chunk:
                    break
                yield chunk

            # Close the body
            body.close()

        # Return a streaming response with the appropriate status and headers
        return StreamingResponse(
            stream_s3_file(), status_code=status_code, headers=headers
        )


async def generate_pmtiles_for_layer(
    layer_id: str,
    s3_key: str,
    feature_count: int,
    user_id: str = None,
    project_id: str = None,
):
    """Generate PMTiles for a vector layer and store in S3."""
    bucket_name = get_bucket_name()

    with tempfile.TemporaryDirectory() as temp_dir:
        # Get file extension from s3_key
        file_extension = os.path.splitext(s3_key)[1]
        local_input_file = os.path.join(temp_dir, f"layer_{layer_id}{file_extension}")

        # Download the vector file from S3
        s3 = await get_async_s3_client()
        await s3.download_file(bucket_name, s3_key, local_input_file)
        # Create local output PMTiles file
        local_output_file = os.path.join(temp_dir, f"layer_{layer_id}.pmtiles")
        # Reproject to EPSG:4326 and convert to FlatGeobuf
        reprojected_file = os.path.join(temp_dir, "reprojected.fgb")
        ogr_cmd = [
            "ogr2ogr",
            "-f",
            "FlatGeobuf",
            "-t_srs",
            "EPSG:4326",
            "-nlt",
            "PROMOTE_TO_MULTI",
            reprojected_file,
            local_input_file,
        ]
        process = await asyncio.create_subprocess_exec(*ogr_cmd)
        await process.wait()
        if process.returncode != 0:
            raise Exception(
                f"ogr2ogr command failed with exit code {process.returncode}"
            )
        # Run tippecanoe to generate pmtiles
        tippecanoe_cmd = [
            "tippecanoe",
            "-o",
            local_output_file,
            "-q",  # Quiet mode - suppress progress indicators
        ]
        if feature_count > 1:
            tippecanoe_cmd.append(
                "-zg"
            )  # Can't guess maxzoom (-zg) without at least two distinct feature locations
        tippecanoe_cmd.extend(
            [
                "--drop-densest-as-needed",
                reprojected_file,
            ]
        )
        process = await asyncio.create_subprocess_exec(*tippecanoe_cmd)
        await process.wait()
        if process.returncode != 0:
            raise Exception(
                f"tippecanoe command failed with exit code {process.returncode}"
            )

        # Upload the PMTiles file to S3 with user_id and project_id in path if available
        if user_id and project_id:
            pmtiles_key = f"pmtiles/{user_id}/{project_id}/{layer_id}.pmtiles"
        else:
            # Fallback to old path if user_id/project_id not available
            pmtiles_key = f"pmtiles/layer/{layer_id}.pmtiles"
        s3 = await get_async_s3_client()
        await s3.upload_file(local_output_file, bucket_name, pmtiles_key)

        # Update the database with the PMTiles key
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Get current metadata
            cursor.execute(
                """
                SELECT metadata FROM map_layers
                WHERE layer_id = %s
                """,
                (layer_id,),
            )
            result = cursor.fetchone()
            metadata = result["metadata"] or {}

            # Update metadata with PMTiles key
            metadata["pmtiles_key"] = pmtiles_key

            # Update the database
            cursor.execute(
                """
                UPDATE map_layers
                SET metadata = %s
                WHERE layer_id = %s
                """,
                (psycopg2.extras.Json(metadata), layer_id),
            )
            conn.commit()

        return pmtiles_key


@layer_router.get(
    "/layer/{layer_id}.pmtiles",
    operation_id="view_layer_as_pmtiles",
)
async def get_layer_pmtiles(
    layer_id: str,
    request: Request,
    session: UserContext = Depends(verify_session_required),
):
    async with get_async_db_connection() as conn:
        # Get the layer by layer_id
        layer = await conn.fetchrow(
            """
            SELECT layer_id, name, path, type, metadata, feature_count, s3_key
            FROM map_layers
            WHERE layer_id = $1
            """,
            layer_id,
        )

        if not layer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found"
            )

        # Check if layer is a vector type
        if layer["type"] != "vector":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Layer is not a vector type. PMTiles can only be generated from vector data.",
            )

        # Check if layer is associated with any maps via the layers array
        map_result = await conn.fetchrow(
            """
            SELECT m.id, p.link_accessible, m.owner_uuid, m.project_id
            FROM user_mundiai_maps m
            JOIN user_mundiai_projects p ON m.project_id = p.id
            WHERE $1 = ANY(m.layers) AND m.soft_deleted_at IS NULL
            """,
            layer_id,
        )

        if map_result and not map_result["link_accessible"]:
            # If not publicly accessible, verify that we have auth
            # NOTE: owner_uuid is <class 'asyncpg.pgproto.pgproto.UUID'>
            if session.get_user_id() != str(map_result["owner_uuid"]):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    # Set up S3 client and bucket
    bucket_name = get_bucket_name()

    # Check if metadata has pmtiles_key
    metadata = layer["metadata"] or "{}"
    pmtiles_key = json.loads(metadata).get("pmtiles_key")

    # If PMTiles doesn't exist, create it
    if not pmtiles_key:
        # Get user_id and project_id from map_result if available
        user_id = str(map_result["owner_uuid"]) if map_result else None
        project_id = map_result["project_id"] if map_result else None
        pmtiles_key = await generate_pmtiles_for_layer(
            layer_id, layer["s3_key"], layer["feature_count"], user_id, project_id
        )

    # Get the file size first to handle range requests using async S3
    s3 = await get_async_s3_client()
    s3_head = await s3.head_object(Bucket=bucket_name, Key=pmtiles_key)
    file_size = s3_head["ContentLength"]

    # Check for Range header to support byte serving
    range_header = request.headers.get("range", None) if request else None
    start_byte = 0
    end_byte = file_size - 1

    # Parse the Range header if present
    if range_header:
        range_match = re.search(r"bytes=(\d+)-(\d*)", range_header)
        if range_match:
            start_byte = int(range_match.group(1))
            end_group = range_match.group(2)
            if end_group:
                end_byte = min(int(end_group), file_size - 1)
            else:
                end_byte = file_size - 1

        # Calculate content length for the range
        content_length = end_byte - start_byte + 1

    # Create streaming function that handles S3 connection properly
    async def stream_s3_file():
        s3 = await get_async_s3_client()
        if range_header:
            # Get range from S3
            s3_response = await s3.get_object(
                Bucket=bucket_name,
                Key=pmtiles_key,
                Range=f"bytes={start_byte}-{end_byte}",
            )
        else:
            # Get entire file from S3
            s3_response = await s3.get_object(Bucket=bucket_name, Key=pmtiles_key)

        # Read all content and yield in chunks
        body = s3_response["Body"]
        chunk_size = 8192
        while True:
            chunk = await body.read(chunk_size)
            if not chunk:
                break
            yield chunk

    # Set headers based on range request
    if range_header:
        status_code = 206  # Partial Content
        headers = {
            "Content-Range": f"bytes {start_byte}-{end_byte}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
            "Content-Type": "application/octet-stream",
        }
    else:
        status_code = 200
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": "application/octet-stream",
        }

    # Return a streaming response with the appropriate status and headers
    return StreamingResponse(stream_s3_file(), status_code=status_code, headers=headers)


@layer_router.get(
    "/layer/{layer_id}/{z}/{x}/{y}.mvt",
    operation_id="get_layer_mvt_tile",
)
async def get_layer_mvt_tile(
    layer_id: str,
    z: int,
    x: int,
    y: int,
    request: Request,
    session: UserContext = Depends(verify_session_required),
):
    # Validate tile coordinates
    if z < 0 or z > 18 or x < 0 or y < 0 or x >= (1 << z) or y >= (1 << z):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tile coordinates"
        )
    async with get_async_db_connection() as conn:
        # Get the layer by layer_id
        layer = await conn.fetchrow(
            """
            SELECT layer_id, name, type, postgis_connection_id, postgis_query, owner_uuid
            FROM map_layers
            WHERE layer_id = $1
            """,
            layer_id,
        )

        if not layer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found"
            )

        # Check if user owns the layer
        if session.get_user_id() != str(layer["owner_uuid"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check if layer is a PostGIS type
        if layer["type"] != "postgis":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Layer is not a PostGIS type. MVT tiles can only be generated from PostGIS data.",
            )
        # Get PostGIS connection details and verify ownership
        connection_details = await conn.fetchrow(
            """
            SELECT user_id, connection_uri
            FROM project_postgres_connections
            WHERE id = $1
            """,
            layer["postgis_connection_id"],
        )

        if not connection_details:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="PostGIS connection not found",
            )

        # Require that the connection owner is the requester
        # TODO this is a double check?
        if session.get_user_id() != str(connection_details["user_id"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Calculate tile bounds in Web Mercator (EPSG:3857)
    # Web Mercator bounds: [-20037508.34, -20037508.34, 20037508.34, 20037508.34]
    world_size = 20037508.34 * 2
    tile_size = world_size / (1 << z)

    xmin = -20037508.34 + x * tile_size
    ymin = 20037508.34 - (y + 1) * tile_size
    xmax = -20037508.34 + (x + 1) * tile_size
    ymax = 20037508.34 - y * tile_size
    try:
        async with get_pooled_connection(
            connection_details["connection_uri"]
        ) as postgis_conn:
            mvt_query = f"""
            WITH
            bounds AS (
                SELECT ST_MakeEnvelope($1, $2, $3, $4, 3857) AS bounds_geom,
                       ST_MakeEnvelope($1, $2, $3, $4, 3857)::box2d AS b2d
            ),
            mvtgeom AS (
                SELECT ST_AsMVTGeom(ST_Transform(t.geom, 3857), bounds.b2d) AS geom
                FROM ({layer["postgis_query"]}) t, bounds
                WHERE ST_IsValid(t.geom)
                  AND ST_Intersects(ST_Transform(t.geom, 3857), bounds.bounds_geom)
            )
            SELECT ST_AsMVT(mvtgeom.*, 'reprojectedfgb') FROM mvtgeom
            """

            # Execute query and get MVT data
            mvt_data = await postgis_conn.fetchval(mvt_query, xmin, ymin, xmax, ymax)

        if mvt_data is None:
            mvt_data = b""

        return Response(
            content=mvt_data,
            media_type="application/vnd.mapbox-vector-tile",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=3600",
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating MVT tile: {str(e)}",
        )


@layer_router.get(
    "/layer/{layer_id}.geojson",
    operation_id="view_layer_as_geojson",
)
async def get_layer_geojson(
    layer_id: str,
    request: Request,
    session: UserContext = Depends(verify_session_required),
):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Get the layer by layer_id
        cursor.execute(
            """
            SELECT layer_id, name, path, type, metadata, feature_count, owner_uuid, s3_key
            FROM map_layers
            WHERE layer_id = %s
            """,
            (layer_id,),
        )

        layer = cursor.fetchone()
        if not layer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found"
            )

        # Check if layer is a vector type
        if layer["type"] != "vector":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Layer is not a vector type. GeoJSON format is only available for vector data.",
            )

        # First check direct layer ownership
        if session.get_user_id() != layer["owner_uuid"]:
            # Check if layer is associated with any public map
            cursor.execute(
                """
                SELECT m.id, p.link_accessible, m.owner_uuid
                FROM user_mundiai_maps m
                JOIN user_mundiai_projects p ON m.project_id = p.id
                WHERE %s = ANY(m.layers) AND m.soft_deleted_at IS NULL AND p.link_accessible = true
                """,
                (layer_id,),
            )

            map_result = cursor.fetchone()
            if not map_result:
                # Not owner and not in any public map
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        # Retrieve the vector data
        bucket_name = get_bucket_name()
        with tempfile.TemporaryDirectory() as temp_dir:
            # Get file extension from s3_key or path
            s3_key_or_path = layer["s3_key"] or layer["path"]

            # If the path is a presigned URL, download using httpx
            if s3_key_or_path.startswith("http"):
                # Extract file extension from URL (before query parameters)
                url_path = s3_key_or_path.split("?")[0]
                file_extension = os.path.splitext(url_path)[1]

                local_input_file = os.path.join(
                    temp_dir, f"layer_{layer_id}_input{file_extension}"
                )

                async with httpx.AsyncClient() as client:
                    response = await client.get(s3_key_or_path)
                    response.raise_for_status()
                    with open(local_input_file, "wb") as f:
                        f.write(response.content)
            else:
                # Otherwise, assume it's an S3 key
                s3_key = s3_key_or_path
                file_extension = os.path.splitext(s3_key)[1]

                local_input_file = os.path.join(
                    temp_dir, f"layer_{layer_id}_input{file_extension}"
                )

                # Download from S3 using async client
                s3 = await get_async_s3_client()
                await s3.download_file(bucket_name, s3_key, local_input_file)

            # Convert to GeoJSON using ogr2ogr
            local_geojson_file = os.path.join(temp_dir, f"layer_{layer_id}.geojson")
            ogr_cmd = [
                "ogr2ogr",
                "-f",
                "GeoJSON",
                "-t_srs",
                "EPSG:4326",  # Ensure coordinates are in WGS84
                "-lco",
                "COORDINATE_PRECISION=6",  # ~1m precision at equator
                local_geojson_file,
                local_input_file,
            ]
            subprocess.run(ogr_cmd, check=True)

            # Read the GeoJSON file and return it
            with open(local_geojson_file, "r") as f:
                geojson_content = f.read()

            # Return the GeoJSON with appropriate headers and cache control
            return Response(
                content=geojson_content,
                media_type="application/geo+json",
                headers={
                    "Content-Disposition": f'attachment; filename="{layer["name"]}.geojson"',
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "public, max-age=86400",  # Cache for 24 hours
                },
            )


KUE_SQL_SYSTEM_PROMPT = """
You are an AI assistant that is converting natural language queries to SQL for DuckDB with spatial extension.
The user is viewing a GIS attribute table, and will type ad-hoc into an input text box. You are to
write a DuckDB SQL query that will automatically be executed and the results will be shown to them in
the attribute table. DuckDB is read-only.

<QueryInstructions>
In your SELECT statement, list out the columns explicitly, most important first. DO NOT `SELECT * FROM ...`.
This is because the user has limited screen space, and some columns are more interesting than others.

ONLY quote column names that have colons in them, e.g. "name:en" vs CountryCode (no quotes).

If the user message is empty, give a SQL query that would best display table data.
Generally limit your SQL query to 6 columns, as more is too much to display.

DO NOT INCLUDE Geometry / geom columns in the SELECT statement.
</QueryInstructions>

<Columns>
Shape__Area and Shape__Length are generally useless unless the user asks for them.
</Columns>

<ResponseFormat>
Begin IMMEDIATELY with SQL.
NEVER preface or suffix with English.
NEVER use ` or ``` to begin the SQL.
NEVER add comments like #, --, //, or /*.

Use newlines to wrap text at 80 characters and use tabs to indent semantically.
However, do not put each column on a new line, as it takes up too much vertical height.
This is the perfect sweet spot:

SELECT foo, bar, baz
FROM FROM Lexample
WHERE col LIKE '%test%'
    AND baz = 'qux'
LIMIT 10;

</ResponseFormat>
"""


class LayerQueryRequest(BaseModel):
    natural_language_query: str
    max_n_rows: int = 20


@layer_router.post(
    "/layer/{layer_id}/query",
    operation_id="query_layer",
)
async def query_layer(
    layer_id: str,
    request: Request,
    body: LayerQueryRequest,
    session: UserContext = Depends(verify_session_required),
    layer_describer: LayerDescriber = Depends(get_layer_describer),
    chat_args: ChatArgsProvider = Depends(get_chat_args_provider),
):
    natural_language_query = body.natural_language_query
    max_n_rows = min(body.max_n_rows, 25)  # Cap at 25 rows
    user_id = session.get_user_id()

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT layer_id, name, path, type, s3_key
            FROM map_layers
            WHERE layer_id = %s AND owner_uuid = %s
            """,
            (layer_id, user_id),
        )

        layer = cursor.fetchone()
        if not layer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found"
            )

    # Check if schema info is cached in Redis
    schema_info = redis.get(f"vector_schema:{layer_id}:duckdb")
    if not schema_info:
        # ~0.5 seconds
        schema_info = await describe_layer_internal(
            layer_id, layer_describer, session.get_user_id()
        )

        # 5 minute expiry
        redis.set(
            f"vector_schema:{layer_id}:duckdb",
            schema_info,
            ex=5 * 60,
        )

    # Generate SQL from natural language query using async client
    client = get_openai_client()

    sql_messages = [
        {
            "role": "system",
            "content": KUE_SQL_SYSTEM_PROMPT,
        },
        {
            "role": "system",
            "content": f"""
The table name representing the layer is {layer_id}.

The column names are from "Attribute Fields" in the table schema.
DO NOT select column names that are not listed. Do not assume there
is a primary key column like ID or id, unless it's affirmatively listed.

<TableSchema>
{schema_info}
</TableSchema>
""",
        },
        {
            "role": "user",
            "content": natural_language_query,
        },
    ]

    # Loop in case we see an error or two
    for _ in range(2):
        # ~1.4 seconds
        chat_completions_args = await chat_args.get_args(user_id, "query_layer")
        response = await client.chat.completions.create(
            **chat_completions_args,
            messages=sql_messages,
            max_completion_tokens=512,
        )

        sql_query = response.choices[0].message.content.strip()

        # Use the execute_duckdb_query function from src/duckdb.py
        try:
            # ~1.1 seconds
            result = await execute_duckdb_query(sql_query, layer_id, max_n_rows)
            return result

        except (duckdb.duckdb.BinderException, duckdb.duckdb.CatalogException) as e:
            sql_messages.append(
                {
                    "role": "system",
                    "content": f"<SQLQueryError> {e} </SQLQueryError> Fix your above query.",
                }
            )
            print("error", e, "trying again")
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred while executing the SQL query",
            )


async def describe_layer_internal(
    layer_id: str,
    layer_describer: LayerDescriber,
    session_user_id: str,
) -> str:
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT layer_id, name, type, metadata, bounds, geometry_type,
                   created_on, last_edited, feature_count, s3_key,
                   postgis_query, postgis_connection_id
            FROM map_layers
            WHERE layer_id = %s
            """,
            (layer_id,),
        )

        layer = cursor.fetchone()
        if not layer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found"
            )

        # Check if the layer is associated with any maps via the layers array
        # Order by created_on DESC to get the most recently created map first
        cursor.execute(
            """
            SELECT id, title, description, owner_uuid
            FROM user_mundiai_maps
            WHERE %s = ANY(layers) AND soft_deleted_at IS NULL
            ORDER BY created_on DESC
            """,
            (layer_id,),
        )

        map_result = cursor.fetchone()
        if map_result:
            # User must own the map to access this endpoint
            if session_user_id != map_result["owner_uuid"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You must own this map to access layer description",
                )

        # Use the injected LayerDescriber to generate the response
        markdown_response = await layer_describer.describe_layer(layer_id, dict(layer))

        # Fetch active style JSON if layer is associated with a map
        if map_result:
            cursor.execute(
                """
                SELECT ls.style_json, ls.style_id
                FROM map_layer_styles mls
                JOIN layer_styles ls ON mls.style_id = ls.style_id
                WHERE mls.map_id = %s AND mls.layer_id = %s
                """,
                (map_result["id"], layer_id),
            )
            style_result = cursor.fetchone()
            if style_result:
                # Add style information if available (for vector layers)
                style_section = f"\n## Style ID ({style_result['style_id']})\n"
                style_section += "```json\n"
                style_section += json.dumps(style_result["style_json"])
                style_section += "\n```"
                markdown_response += style_section

        return markdown_response


@layer_router.get(
    "/layer/{layer_id}/describe",
    operation_id="describe_layer",
)
async def describe_layer(
    layer_id: str,
    request: Request,
    session: UserContext = Depends(verify_session_required),
    layer_describer: LayerDescriber = Depends(get_layer_describer),
):
    markdown_response = await describe_layer_internal(
        layer_id, layer_describer, session.get_user_id()
    )

    return Response(
        content=markdown_response,
        media_type="text/plain",
    )


@router.put("/{map_id}/layer/{layer_id}", operation_id="add_layer_to_map")
async def add_layer_to_map(
    request: Request,
    map_id: str,
    layer_id: str,
    session: UserContext = Depends(verify_session_required),
):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Check if the map exists and get current layers
        cursor.execute(
            """
            SELECT id, owner_uuid, layers
            FROM user_mundiai_maps
            WHERE id = %s AND soft_deleted_at IS NULL
            """,
            (map_id,),
        )

        map_result = cursor.fetchone()
        if not map_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
            )

        # Check if user is the owner of the map
        if session.get_user_id() != map_result["owner_uuid"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to modify this map",
            )

        # Check if the layer exists
        cursor.execute(
            """
            SELECT layer_id, name
            FROM map_layers
            WHERE layer_id = %s
            """,
            (layer_id,),
        )

        layer_result = cursor.fetchone()
        if not layer_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Layer not found"
            )

        # Check if the layer is already associated with this map
        current_layers = map_result["layers"] or []
        if layer_id in current_layers:
            return {"message": "Layer is already associated with this map"}

        # Update the map to include the layer_id in its layers array
        cursor.execute(
            """
            UPDATE user_mundiai_maps
            SET layers = array_append(layers, %s),
                last_edited = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id
            """,
            (layer_id, map_id),
        )

        updated_map = cursor.fetchone()
        conn.commit()

        if not updated_map:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to associate layer with map",
            )

        return {
            "message": "Layer successfully associated with map",
            "layer_id": layer_result["layer_id"],
            "layer_name": layer_result["name"],
            "map_id": map_id,
        }


def pull_bounds_from_map(map_id: str) -> tuple[float, float, float, float]:
    """Pull the bounds from the map in the database by taking the min and max of all layer bounds."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT
                MIN(ml.bounds[1]) as xmin,
                MIN(ml.bounds[2]) as ymin,
                MAX(ml.bounds[3]) as xmax,
                MAX(ml.bounds[4]) as ymax
            FROM map_layers ml
            JOIN user_mundiai_maps m ON ml.layer_id = ANY(m.layers)
            WHERE m.id = %s AND ml.bounds IS NOT NULL
            """,
            (map_id,),
        )
        result = cursor.fetchone()

        if not result or result["xmin"] is None:
            # No layers with bounds found
            return (-180, -90, 180, 90)

        return (
            result["xmin"],
            result["ymin"],
            result["xmax"],
            result["ymax"],
        )


@router.get("/{map_id}/render.png", operation_id="render_map_to_png")
async def render_map(
    request: Request,
    map_id: str,
    bbox: Optional[str] = None,
    width: int = 1024,
    height: int = 600,
    bgcolor: str = "#ffffff",
    style_json: Optional[str] = None,
    base_map: BaseMapProvider = Depends(get_base_map_provider),
    session: Optional[UserContext] = Depends(verify_session_optional),
):
    # Verify user has access to map
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT m.id, p.link_accessible, m.owner_uuid
            FROM user_mundiai_maps m
            JOIN user_mundiai_projects p ON m.project_id = p.id
            WHERE m.id = %s AND m.soft_deleted_at IS NULL
            """,
            (map_id,),
        )

        map_result = cursor.fetchone()
        if not map_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
            )

        # Check if map is publicly accessible
        if not map_result["link_accessible"]:
            # If not publicly accessible, verify that we have auth
            if session is None or session.get_user_id() != map_result["owner_uuid"]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required to access this map",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    if style_json is None:
        style_json = await get_map_style(
            request,
            map_id,
            only_show_inline_sources=True,
            session=session,
            base_map=base_map,
        )

    return (
        await render_map_internal(
            map_id, bbox, width, height, "mbgl", bgcolor, style_json
        )
    )[0]


# requires style.json to be provided, so that we can do this without auth
async def render_map_internal(
    map_id, bbox, width, height, renderer, bgcolor, style_json
) -> tuple[Response, dict]:
    if bbox is None:
        xmin, ymin, xmax, ymax = pull_bounds_from_map(map_id)
    else:
        xmin, ymin, xmax, ymax = map(float, bbox.split(","))

    assert style_json is not None
    # Create a temporary file for the output PNG
    with tempfile.NamedTemporaryFile(suffix=".png") as temp_output:
        output_path = temp_output.name

        # Format the style JSON with required parameters
        input_data = {
            "width": width,
            "height": height,
            "bounds": f"{xmin},{ymin},{xmax},{ymax}",
            "style": style_json,
            "ratio": 1,
        }

        # Get zoom and center for metadata using the zoom script
        zoom_process = await asyncio.create_subprocess_exec(
            "node",
            "src/renderer/zoom.js",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        zoom_stdout, zoom_stderr = await zoom_process.communicate(
            input=json.dumps(
                {
                    "bbox": f"{xmin},{ymin},{xmax},{ymax}",
                    "width": width,
                    "height": height,
                }
            ).encode()
        )
        zoom_data = json.loads(zoom_stdout.decode())

        # Run the renderer using subprocess
        try:
            process = await asyncio.create_subprocess_exec(
                "xvfb-run",
                "-a",
                "node",
                "src/renderer/render.js",
                output_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate(
                input=json.dumps(input_data).encode()
            )

            if process.returncode != 0:
                raise subprocess.CalledProcessError(
                    process.returncode, "xvfb-run", output=stdout, stderr=stderr
                )

            temp_output.seek(0)
            screenshot_data = temp_output.read()

            return (
                Response(
                    content=screenshot_data,
                    media_type="image/png",
                    headers={
                        "Content-Type": "image/png",
                        "Content-Disposition": f"inline; filename=map_{map_id}.png",
                    },
                ),
                zoom_data,
            )
        except subprocess.CalledProcessError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error rendering map: {e.stderr.decode()}",
            )


@router.delete("/{map_id}/layer/{layer_id}", operation_id="remove_layer_from_map")
async def remove_layer_from_map(
    map_id: str,
    layer_id: str,
    session: UserContext = Depends(verify_session_required),
):
    """
    Remove a layer from a map by setting its map_id to NULL.
    The layer still exists in the database but is no longer associated with the map.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Check if the map exists
        cursor.execute(
            """
            SELECT id, owner_uuid
            FROM user_mundiai_maps
            WHERE id = %s AND soft_deleted_at IS NULL
            """,
            (map_id,),
        )

        map_result = cursor.fetchone()
        if not map_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
            )

        # Check if user owns the map
        if session.get_user_id() != map_result["owner_uuid"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to modify this map",
            )
        # Check if the layer exists and is in the map's layers array
        cursor.execute(
            """
            SELECT layers, (SELECT name FROM map_layers WHERE layer_id = %s) as layer_name
            FROM user_mundiai_maps
            WHERE id = %s
            """,
            (layer_id, map_id),
        )

        map_data = cursor.fetchone()
        if not map_data or not map_data["layers"] or layer_id not in map_data["layers"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Layer not found or not associated with this map",
            )

        # Remove the layer from the map's layers array
        cursor.execute(
            """
            UPDATE user_mundiai_maps
            SET layers = array_remove(layers, %s)
            WHERE id = %s
            RETURNING id
            """,
            (layer_id, map_id),
        )

        updated_map = cursor.fetchone()
        conn.commit()

        if not updated_map:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to remove layer from map",
            )

        return {
            "message": "Layer successfully removed from map",
            "layer_id": layer_id,
            "layer_name": map_data["layer_name"],
        }


@router.get("/", operation_id="list_user_maps", response_model=UserMapsResponse)
async def get_user_maps(
    request: Request, session: UserContext = Depends(verify_session_required)
):
    """
    Get all maps owned by the authenticated user.

    Returns a list of all maps that belong to the currently authenticated user.
    Authentication is required via SuperTokens session or API key.
    """
    # Get the user ID from authentication
    user_id = session.get_user_id()

    # Connect to database
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Get all maps owned by this user that are not soft-deleted
        cursor.execute(
            """
            SELECT m.id, m.title, m.description, m.created_on, m.last_edited, p.link_accessible, m.project_id
            FROM user_mundiai_maps m
            JOIN user_mundiai_projects p ON m.project_id = p.id
            WHERE m.owner_uuid = %s AND m.soft_deleted_at IS NULL
            ORDER BY m.last_edited DESC
            """,
            (user_id,),
        )

        # Fetch all maps
        maps_data = cursor.fetchall()

        # Convert datetime objects to ISO format strings for JSON serialization
        maps_response = []
        for map_data in maps_data:
            # Convert datetime objects to strings
            created_on = (
                map_data["created_on"].isoformat()
                if isinstance(map_data["created_on"], datetime)
                else map_data["created_on"]
            )
            last_edited = (
                map_data["last_edited"].isoformat()
                if isinstance(map_data["last_edited"], datetime)
                else map_data["last_edited"]
            )

            maps_response.append(
                {
                    "id": map_data["id"],
                    "project_id": map_data["project_id"],
                    "title": map_data["title"] or "Untitled Map",
                    "description": map_data["description"] or "",
                    "created_on": created_on,
                    "last_edited": last_edited,
                }
            )

        # Return the list of maps
        return UserMapsResponse(maps=maps_response)


@router.get(
    "/{prev_map_id}/diff/{new_map_id}",
    operation_id="summarize_map_diff",
)
async def summarize_map_diff(
    request: Request,
    prev_map_id: str,
    new_map_id: str,
    session: UserContext = Depends(verify_session_required),
    postgis_provider: Callable = Depends(get_postgis_provider),
    layer_describer: LayerDescriber = Depends(get_layer_describer),
    chat_args: ChatArgsProvider = Depends(get_chat_args_provider),
):
    """Summarize the difference between two map versions."""
    # Get descriptions for both maps
    prev_map_description = await get_map_description(
        request,
        prev_map_id,
        session,
        postgis_provider=postgis_provider,
        layer_describer=layer_describer,
    )
    new_map_description = await get_map_description(
        request,
        new_map_id,
        session,
        postgis_provider=postgis_provider,
        layer_describer=layer_describer,
    )

    prev_text = prev_map_description.body.decode("utf-8")
    new_text = new_map_description.body.decode("utf-8")

    # Calculate diff
    diff = list(
        difflib.unified_diff(
            prev_text.splitlines(),
            new_text.splitlines(),
            n=0,
        )
    )
    diff_content = "\n".join(diff)

    # Use OpenAI to summarize the diff
    client = get_openai_client()
    chat_completions_args = await chat_args.get_args(
        session.get_user_id(), "summarize_map_diff"
    )
    response = await client.chat.completions.create(
        **chat_completions_args,
        messages=[
            {
                "role": "system",
                "content": """
Summarize the map changes in 8 words or less based on the diff provided.
Be specific but concise about what changed.

Coordinate bounds change often, and are rarely important.

Keep your response to a maximum of 8 words. Use lowercase except for proper nouns/acronyms
("fixed polygons" instead of "Fixed polygons")

If no changes, use "no edits".
""",
            },
            {
                "role": "user",
                "content": diff_content,
            },
        ],
        max_tokens=30,
    )

    summary = response.choices[0].message.content.strip()
    return {"diff_summary": summary}


project_router = APIRouter()


class MostRecentVersion(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    last_edited: Optional[str] = None


class PostgresConnectionDetails(BaseModel):
    connection_id: str
    table_count: int
    friendly_name: str


class ProjectResponse(BaseModel):
    id: str
    owner_uuid: str
    link_accessible: bool
    maps: Optional[List[str]] = None
    created_on: str
    most_recent_version: Optional[MostRecentVersion] = None
    postgres_connections: List[PostgresConnectionDetails] = []


class UserProjectsResponse(BaseModel):
    projects: List[ProjectResponse]


@project_router.get(
    "/", response_model=UserProjectsResponse, operation_id="list_user_projects"
)
async def list_user_projects(
    session: UserContext = Depends(verify_session_required),
):
    """
    List all projects associated with the authenticated user.
    A project is associated if the user is the owner, an editor, or a viewer.
    """
    user_id = session.get_user_id()

    async with get_async_db_connection() as conn:
        projects_data = await conn.fetch(
            """
            SELECT p.id, p.owner_uuid, p.link_accessible, p.maps, p.created_on
            FROM user_mundiai_projects p
            WHERE (
                p.owner_uuid = $1 OR
                $2 = ANY(p.editor_uuids) OR
                $3 = ANY(p.viewer_uuids)
            ) AND p.soft_deleted_at IS NULL
            ORDER BY p.created_on DESC
            """,
            user_id,
            user_id,
            user_id,
        )

        projects_response = []
        for project_data in projects_data:
            created_on_str = (
                project_data["created_on"].isoformat()
                if isinstance(project_data["created_on"], datetime)
                else str(project_data["created_on"])
            )
            owner_uuid_str = str(project_data["owner_uuid"])
            most_recent_map_details = None

            if project_data["maps"] and len(project_data["maps"]) > 0:
                most_recent_map_id = project_data["maps"][-1]

                map_details = await conn.fetchrow(
                    """
                    SELECT title, description, last_edited
                    FROM user_mundiai_maps
                    WHERE id = $1 AND soft_deleted_at IS NULL
                    """,
                    most_recent_map_id,
                )
                if map_details:
                    last_edited_str = (
                        map_details["last_edited"].isoformat()
                        if isinstance(map_details["last_edited"], datetime)
                        else str(map_details["last_edited"])
                    )
                    most_recent_map_details = MostRecentVersion(
                        title=map_details["title"],
                        description=map_details["description"],
                        last_edited=last_edited_str,
                    )

            # Get PostgreSQL connections for this project
            postgres_connections = []
            postgres_conn_results = await conn.fetch(
                """
                SELECT id, connection_uri, connection_name
                FROM project_postgres_connections
                WHERE project_id = $1
                ORDER BY created_at ASC
                """,
                project_data["id"],
            )

            for postgres_conn_result in postgres_conn_results:
                connection_id = postgres_conn_result["id"]
                connection_uri = postgres_conn_result["connection_uri"]

                # Get AI-generated friendly name, fallback to connection_name if not available
                summary_result = await conn.fetchrow(
                    """
                    SELECT friendly_name
                    FROM project_postgres_summary
                    WHERE connection_id = $1
                    ORDER BY generated_at DESC
                    LIMIT 1
                """,
                    connection_id,
                )

                friendly_name = (
                    summary_result["friendly_name"]
                    if summary_result and summary_result["friendly_name"]
                    else postgres_conn_result["connection_name"] or "Loading..."
                )
                table_count = 0

                try:
                    postgres_conn = await asyncpg.connect(connection_uri)
                    try:
                        # Count tables in all schemas (excluding system schemas)
                        table_count_result = await postgres_conn.fetchval("""
                            SELECT COUNT(*)
                            FROM information_schema.tables
                            WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
                            AND table_type = 'BASE TABLE'
                        """)
                        table_count = table_count_result or 0
                    finally:
                        await postgres_conn.close()
                except Exception as e:
                    # If connection fails, just log and continue with 0 count
                    print(f"Failed to connect to PostgreSQL for table count: {e}")
                    table_count = 0

                postgres_connections.append(
                    PostgresConnectionDetails(
                        connection_id=connection_id,
                        table_count=table_count,
                        friendly_name=friendly_name,
                    )
                )

            projects_response.append(
                ProjectResponse(
                    id=project_data["id"],
                    owner_uuid=owner_uuid_str,
                    link_accessible=project_data["link_accessible"],
                    maps=project_data["maps"],
                    created_on=created_on_str,
                    most_recent_version=most_recent_map_details,
                    postgres_connections=postgres_connections,
                )
            )

    return UserProjectsResponse(projects=projects_response)


@project_router.get(
    "/{project_id}", response_model=ProjectResponse, operation_id="get_project"
)
async def get_project(
    project_id: str,
    session: UserContext = Depends(verify_session_required),
):
    user_id = session.get_user_id()
    async with get_async_db_connection() as conn:
        project_data = await conn.fetchrow(
            """
            SELECT p.id, p.owner_uuid, p.link_accessible, p.maps, p.created_on
            FROM user_mundiai_projects p
            WHERE (
                p.owner_uuid = $1 OR
                $2 = ANY(p.editor_uuids) OR
                $3 = ANY(p.viewer_uuids)
            ) AND p.soft_deleted_at IS NULL
            AND p.id = $4
            ORDER BY p.created_on DESC
            """,
            user_id,
            user_id,
            user_id,
            project_id,
        )

        if project_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found.",
            )

        created_on_str = (
            project_data["created_on"].isoformat()
            if isinstance(project_data["created_on"], datetime)
            else str(project_data["created_on"])
        )
        owner_uuid_str = str(project_data["owner_uuid"])
        most_recent_map_details = None

        if project_data["maps"] and len(project_data["maps"]) > 0:
            most_recent_map_id = project_data["maps"][-1]
            map_details = await conn.fetchrow(
                """
                SELECT title, description, last_edited
                FROM user_mundiai_maps
                WHERE id = $1 AND soft_deleted_at IS NULL
                """,
                most_recent_map_id,
            )
            if map_details:
                last_edited_str = (
                    map_details["last_edited"].isoformat()
                    if isinstance(map_details["last_edited"], datetime)
                    else str(map_details["last_edited"])
                )
                most_recent_map_details = MostRecentVersion(
                    title=map_details["title"],
                    description=map_details["description"],
                    last_edited=last_edited_str,
                )

        # Get PostgreSQL connections for this project
        postgres_connections = []
        postgres_conn_results = await conn.fetch(
            """
            SELECT id, connection_uri, connection_name
            FROM project_postgres_connections
            WHERE project_id = $1
            ORDER BY created_at ASC
            """,
            project_data["id"],
        )

        for postgres_conn_result in postgres_conn_results:
            connection_id = postgres_conn_result["id"]
            connection_uri = postgres_conn_result["connection_uri"]

            # Get AI-generated friendly name, fallback to connection_name if not available
            summary_result = await conn.fetchrow(
                """
                SELECT friendly_name
                FROM project_postgres_summary
                WHERE connection_id = $1
                ORDER BY generated_at DESC
                LIMIT 1
            """,
                connection_id,
            )

            friendly_name = (
                summary_result["friendly_name"]
                if summary_result and summary_result["friendly_name"]
                else postgres_conn_result["connection_name"] or "Loading..."
            )
            table_count = 0

            try:
                postgres_conn = await asyncpg.connect(connection_uri)
                try:
                    # Count tables in all schemas (excluding system schemas)
                    table_count_result = await postgres_conn.fetchval("""
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
                        AND table_type = 'BASE TABLE'
                    """)
                    table_count = table_count_result or 0
                finally:
                    await postgres_conn.close()
            except Exception as e:
                # If connection fails, just log and continue with 0 count
                print(f"Failed to connect to PostgreSQL for table count: {e}")
                table_count = 0

            postgres_connections.append(
                PostgresConnectionDetails(
                    connection_id=connection_id,
                    table_count=table_count,
                    friendly_name=friendly_name,
                )
            )

        return ProjectResponse(
            id=project_data["id"],
            owner_uuid=owner_uuid_str,
            link_accessible=project_data["link_accessible"],
            maps=project_data["maps"],
            created_on=created_on_str,
            most_recent_version=most_recent_map_details,
            postgres_connections=postgres_connections,
        )


class ProjectUpdateRequest(BaseModel):
    link_accessible: bool


class ProjectUpdateResponse(BaseModel):
    updated: bool


@project_router.post(
    "/{project_id}", response_model=ProjectUpdateResponse, operation_id="update_project"
)
async def update_project(
    project_id: str,
    update_data: ProjectUpdateRequest,
    session: UserContext = Depends(verify_session_required),
):
    """
    Update project settings. Currently supports updating link_accessible status.
    Only the project owner can update these settings.
    """
    user_id = session.get_user_id()

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # First check if user is the owner
        cursor.execute(
            """
            SELECT owner_uuid
            FROM user_mundiai_projects
            WHERE id = %s AND soft_deleted_at IS NULL
            """,
            (project_id,),
        )
        project_data = cursor.fetchone()

        if project_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found.",
            )

        # Verify ownership
        if str(project_data["owner_uuid"]) != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the project owner can update project settings.",
            )

        # Update link_accessible
        cursor.execute(
            """
            UPDATE user_mundiai_projects
            SET link_accessible = %s
            WHERE id = %s
            """,
            (update_data.link_accessible, project_id),
        )
        conn.commit()

        return ProjectUpdateResponse(updated=True)


class PostgresConnectionRequest(BaseModel):
    connection_uri: str
    connection_name: Optional[str] = None


class PostgresConnectionResponse(BaseModel):
    success: bool
    message: str


class DatabaseDocumentationResponse(BaseModel):
    connection_id: str
    connection_name: str
    friendly_name: Optional[str] = None
    documentation: Optional[str] = None
    generated_at: Optional[datetime] = None


@project_router.post(
    "/{project_id}/postgis-connections",
    response_model=PostgresConnectionResponse,
    operation_id="add_postgis_connection",
)
async def add_postgis_connection(
    project_id: str,
    connection_data: PostgresConnectionRequest,
    background_tasks: BackgroundTasks,
    session: UserContext = Depends(verify_session_required),
    database_documenter: DatabaseDocumenter = Depends(get_database_documenter),
):
    """
    Add a PostgreSQL connection URI to a project.
    Only the project owner or editors can add connections.
    """
    user_id = session.get_user_id()

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Check if user has access to the project
        cursor.execute(
            """
            SELECT owner_uuid, editor_uuids
            FROM user_mundiai_projects
            WHERE id = %s AND soft_deleted_at IS NULL
            """,
            (project_id,),
        )
        project = cursor.fetchone()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found.",
            )

        # Check if user is owner or editor
        if str(project["owner_uuid"]) != user_id and user_id not in (
            project["editor_uuids"] or []
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to modify this project.",
            )

        # Validate the connection URI format
        connection_uri = connection_data.connection_uri.strip()
        if not connection_uri.startswith("postgresql://"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid PostgreSQL connection URI format. Must start with 'postgresql://'",
            )

        # Check if connection already exists
        cursor.execute(
            """
            SELECT id FROM project_postgres_connections
            WHERE project_id = %s AND user_id = %s AND connection_uri = %s
            """,
            (project_id, user_id, connection_uri),
        )
        existing_conn = cursor.fetchone()

        if not existing_conn:
            # Generate new connection ID
            connection_id = generate_id(prefix="C")

            # Insert the new connection
            cursor.execute(
                """
                INSERT INTO project_postgres_connections
                (id, project_id, user_id, connection_uri, connection_name)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    connection_id,
                    project_id,
                    user_id,
                    connection_data.connection_uri,
                    connection_data.connection_name,
                ),
            )
            conn.commit()

            # Start background task to generate database documentation
            background_tasks.add_task(
                database_documenter.generate_documentation,
                connection_id,
                connection_data.connection_uri,
                connection_data.connection_name or "Database",
            )

            return PostgresConnectionResponse(
                success=True, message="PostgreSQL connection added successfully"
            )
        else:
            return PostgresConnectionResponse(
                success=True, message="Connection URI already exists"
            )


@project_router.get(
    "/{project_id}/postgis-connections/{connection_id}/documentation",
    response_model=DatabaseDocumentationResponse,
    operation_id="get_database_documentation",
)
async def get_database_documentation(
    project_id: str,
    connection_id: str,
    session: UserContext = Depends(verify_session_required),
):
    """
    Retrieve the generated database documentation for a specific PostgreSQL connection.
    """
    user_id = session.get_user_id()

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Check if user has access to the project
        cursor.execute(
            """
            SELECT owner_uuid, editor_uuids, viewer_uuids
            FROM user_mundiai_projects
            WHERE id = %s AND soft_deleted_at IS NULL
            """,
            (project_id,),
        )
        project = cursor.fetchone()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found.",
            )

        # Check if user has access (owner, editor, or viewer)
        if (
            str(project["owner_uuid"]) != user_id
            and user_id not in (project["editor_uuids"] or [])
            and user_id not in (project["viewer_uuids"] or [])
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to access this project.",
            )

        # Get the database connection and documentation (most recent summary)
        cursor.execute(
            """
            SELECT
                ppc.id,
                ppc.connection_name,
                pps.friendly_name,
                pps.summary_md,
                pps.generated_at
            FROM project_postgres_connections ppc
            LEFT JOIN project_postgres_summary pps ON ppc.id = pps.connection_id
            WHERE ppc.id = %s AND ppc.project_id = %s
            ORDER BY pps.generated_at DESC
            LIMIT 1
            """,
            (connection_id, project_id),
        )
        connection = cursor.fetchone()

        if not connection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Database connection {connection_id} not found.",
            )

        return DatabaseDocumentationResponse(
            connection_id=connection["id"],
            connection_name=connection["connection_name"] or "Loading...",
            friendly_name=connection["friendly_name"],
            documentation=connection["summary_md"],
            generated_at=connection["generated_at"],
        )


class SocialImageCacheBustedError(Exception):
    pass


@project_router.get("/{project_id}/social.webp", response_class=Response)
async def get_project_social_preview(
    request: Request,
    project_id: str,
    session: UserContext = Depends(verify_session_required),
):
    # Fetch the latest map_id for the project
    user_id = session.get_user_id()
    async with get_async_db_connection() as conn:
        project_record = await conn.fetchrow(
            """
            SELECT maps FROM user_mundiai_projects
            WHERE id = $1 AND owner_uuid = $2 AND soft_deleted_at IS NULL
            """,
            project_id,
            user_id,
        )

    if not project_record or len(project_record["maps"]) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} either does not exist or has no maps.",
        )

    latest_map_id = project_record["maps"][-1]

    # S3 configuration - key by map_id instead of project_id
    bucket_name = get_bucket_name()
    s3_key = f"social_previews/map_{latest_map_id}.webp"

    # Try to get the image from S3
    try:
        s3 = await get_async_s3_client()
        s3_response = await s3.get_object(Bucket=bucket_name, Key=s3_key)
        image_data = await s3_response["Body"].read()

    except botocore.exceptions.ClientError:
        # Re-render with semaphore to limit concurrent renders
        async with SOCIAL_RENDER_SEMAPHORE:
            print(
                f"Rendering social image for map {latest_map_id} (semaphore acquired)"
            )

            base_map_provider = get_base_map_provider()
            style_json = await get_map_style_internal(
                latest_map_id,
                base_map_provider,
                only_show_inline_sources=True,
            )

            render_response, _ = await render_map_internal(
                map_id=latest_map_id,
                bbox=None,
                width=1200,
                height=630,
                renderer="mbgl",
                bgcolor="#ffffff",
                style_json=style_json,
            )

            img = Image.open(io.BytesIO(render_response.body))
            webp_buffer = io.BytesIO()
            img.save(webp_buffer, format="WEBP", quality=80, lossless=False)

            s3 = await get_async_s3_client()
            await s3.put_object(
                Bucket=bucket_name,
                Key=s3_key,
                Body=webp_buffer.getvalue(),
                ContentType="image/webp",
            )

            image_data = webp_buffer.getvalue()
            print(f"Social image rendering completed for map {latest_map_id}")

    return Response(
        content=image_data,
        media_type="image/webp",
        headers={
            "Content-Type": "image/webp",
            "Cache-Control": "max-age=900, public",
        },
    )


@project_router.delete("/{project_id}", operation_id="delete_project")
async def delete_project(
    project_id: str,
    session: UserContext = Depends(verify_session_required),
):
    """
    Soft delete a project by setting its soft_deleted_at timestamp.
    The project still exists in the database but is no longer accessible.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Check if the project exists
        cursor.execute(
            """
            SELECT id, owner_uuid
            FROM user_mundiai_projects
            WHERE id = %s AND soft_deleted_at IS NULL
            """,
            (project_id,),
        )

        project_result = cursor.fetchone()
        if not project_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
            )

        # Check if user owns the project
        if session.get_user_id() != project_result["owner_uuid"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete this project",
            )

        # Soft delete the project
        cursor.execute(
            """
            UPDATE user_mundiai_projects
            SET soft_deleted_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id
            """,
            (project_id,),
        )

        updated_project = cursor.fetchone()
        conn.commit()

        if not updated_project:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete project",
            )

        return {
            "message": "Project successfully deleted",
            "project_id": project_id,
        }


# Export both routers
__all__ = ["router", "layer_router", "project_router"]
