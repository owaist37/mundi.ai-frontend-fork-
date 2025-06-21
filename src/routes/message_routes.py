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

from fastapi import APIRouter, HTTPException, status, Request, Depends
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Union, Tuple
from pydantic import BaseModel
import logging
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from fastapi import BackgroundTasks, WebSocket, WebSocketDisconnect

import pandas as pd
import asyncio
import uuid
import traceback
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import asyncpg
import time
from typing import Callable
from collections import defaultdict, deque
from redis import Redis
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_tool_message_param import (
    ChatCompletionToolMessageParam,
)
from openai.types.chat.chat_completion_message_param import (
    ChatCompletionUserMessageParam,
    ChatCompletionSystemMessageParam,
)
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam

from src.symbology.llm import generate_maplibre_layers_for_layer_id
from src.structures import get_db_connection, get_async_db_connection
from src.symbology.verify import StyleValidationError, verify_style_json_str
from src.routes.postgres_routes import generate_id, get_map_style_internal
from src.dependencies.base_map import get_base_map_provider
from src.routes.postgres_routes import get_map_description
from src.duckdb import execute_duckdb_query
from src.dependencies.postgis import get_postgis_provider
from src.dependencies.layer_describer import LayerDescriber, get_layer_describer
from src.dependencies.chat_completions import ChatArgsProvider, get_chat_args_provider
from src.dependencies.map_state import MapStateProvider, get_map_state_provider
from src.dependencies.system_prompt import (
    SystemPromptProvider,
    get_system_prompt_provider,
)
from src.dependencies.session import (
    verify_session_required,
    UserContext,
    verify_websocket,
)
from src.utils import get_openai_client
from src.openstreetmap import download_from_openstreetmap, has_openstreetmap_api_key

logger = logging.getLogger(__name__)


redis = Redis(
    host=os.environ["REDIS_HOST"],
    port=int(os.environ["REDIS_PORT"]),
    decode_responses=True,
)

# Create router
router = APIRouter()

# In-memory pub/sub for chat updates: job_id -> asyncio.Queue
chat_channels: Dict[str, asyncio.Queue] = {}
# Subscriber registry for WebSocket notifications by map_id
subscribers_by_map = defaultdict(set)
subscribers_lock = asyncio.Lock()

# Track recently disconnected users and their missed messages per map
# (user_id, map_id) -> {"disconnect_time": float, "missed_messages": deque[(timestamp, payload)]}
recently_disconnected_users: Dict[Tuple[str, str], Dict[str, Any]] = {}
DISCONNECT_TTL = 30.0  # Keep disconnected user data for 30 seconds
MAX_MISSED_MESSAGES = 100  # Limit buffer size per user per map


class ChatCompletionMessageRow(BaseModel):
    id: int
    map_id: str
    sender_id: str
    message_json: Union[
        ChatCompletionMessageParam,
        ChatCompletionMessage,
        dict,
    ]
    created_at: str


class MessagesListResponse(BaseModel):
    map_id: str
    messages: List[ChatCompletionMessageRow]


@router.get(
    "/{map_id}/messages",
    # response_model=MessagesListResponse,
    operation_id="get_map_messages",
    response_class=JSONResponse,
)
async def get_map_messages(
    request: Request,
    map_id: str,
    session: UserContext = Depends(verify_session_required),
):
    all_messages = await get_all_map_messages(map_id, session)

    # Filter for messages with role "user" or "assistant" and no tool_calls
    filtered_messages = [
        msg
        for msg in all_messages["messages"]
        if msg.get("message_json", {}).get("role") in ["user", "assistant"]
        and not msg.get("message_json", {}).get("tool_calls")
    ]

    return {
        "map_id": map_id,
        "messages": filtered_messages,
    }


async def get_all_map_messages(
    map_id: str,
    session: UserContext,
):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

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

        if session.get_user_id() != str(map_result["owner_uuid"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        cursor.execute(
            """
            SELECT id, map_id, sender_id, message_json, created_at
            FROM chat_completion_messages
            WHERE map_id = %s
            ORDER BY created_at ASC
            """,
            (map_id,),
        )

        db_messages = cursor.fetchall()
        # We keep everything as dict here, which is because serializing to chat completion row
        # kept fucking up image urls.
        messages = list(db_messages)

        return {
            "map_id": map_id,
            "messages": messages,
        }


def add_chat_completion_message_args(
    cursor,
    map_id: str,
    user_id: str,
    message: Union[ChatCompletionMessage, ChatCompletionMessageParam],
) -> dict:
    if isinstance(message, BaseModel):
        message = message.model_dump()

    cursor.execute(
        """
        INSERT INTO chat_completion_messages
        (map_id, sender_id, message_json)
        VALUES (%s, %s, %s)
        RETURNING id, map_id, sender_id, message_json, created_at
        """,
        (
            map_id,
            user_id,
            psycopg2.extras.Json(message),
        ),
    )
    return cursor.fetchone()


async def process_chat_interaction_task(
    request: Request,  # Keep request for get_map_messages
    map_id: str,
    session: UserContext,  # Pass session for auth
    user_id: str,  # Pass user_id directly
    chat_args: ChatArgsProvider,
    map_state: MapStateProvider,
    system_prompt_provider: SystemPromptProvider,
):
    # kick it off with a quick sleep, to detach from the event loop blocking /send
    await asyncio.sleep(0.05)

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        def add_chat_completion_message(
            message: Union[ChatCompletionMessage, ChatCompletionMessageParam],
        ):
            add_chat_completion_message_args(cursor, map_id, user_id, message)
            conn.commit()

        for i in range(25):
            # Check if the message processing has been cancelled
            if redis.get(f"messages:{map_id}:cancelled"):
                redis.delete(f"messages:{map_id}:cancelled")
                break

            # Refresh messages to include any new system messages we just added
            updated_messages_response = await get_all_map_messages(map_id, session)
            openai_messages = [
                msg["message_json"] for msg in updated_messages_response["messages"]
            ]

            cursor.execute(
                """
                SELECT ml.layer_id, ml.created_on, ml.last_edited, ml.type, ml.name
                FROM map_layers ml
                WHERE ml.owner_uuid = %s
                AND NOT EXISTS (
                    SELECT 1 FROM user_mundiai_maps m
                    WHERE ml.layer_id = ANY(m.layers) AND m.owner_uuid = %s
                )
                ORDER BY ml.created_on DESC
                LIMIT 10
                """,
                (user_id, user_id),
            )
            unattached_layers = cursor.fetchall()

            layer_enum = {}
            for layer in unattached_layers:
                layer_name = (
                    layer.get("name") or f"Unnamed Layer ({layer['layer_id'][:8]})"
                )
                layer_enum[layer["layer_id"]] = (
                    f"{layer_name} (type: {layer.get('type', 'unknown')}, created: {layer['created_on']})"
                )

            client = get_openai_client()

            tools_payload = [
                {
                    "type": "function",
                    "function": {
                        "name": "new_layer_from_postgis",
                        "description": "Creates a new layer, given a PostGIS connection and query, and adds it to the map so the user can see it. Layer will automatically pull data from PostGIS. Modify style using the create_layer_style tool.",
                        "strict": True,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "postgis_connection_id": {
                                    "type": "string",
                                    "description": "Unique PostGIS connection ID used as source",
                                },
                                "query": {
                                    "type": "string",
                                    "description": "SQL query to execute against PostGIS database for this layer, should list fetched columns for attributes that might be used for symbology (+ shape geometry). This query MUST alias the geometry column as 'geom'.",
                                },
                                "layer_name": {
                                    "type": "string",
                                    "description": "Sets a human-readable name for this layer. This name will appear in the layer list/legend for the user.",
                                },
                            },
                            "required": [
                                "postgis_connection_id",
                                "query",
                                "layer_name",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "add_layer_to_map",
                        "description": "Shows a newly created or existing unattached layer on the user's current map and layer list. Use this after a geoprocessing step that creates a layer, or if the user asks to see an existing layer that isn't currently on their map.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "layer_id": {
                                    "type": "string",
                                    "description": "The ID of the layer to add to the map. Choose from available unattached layers.",
                                    "enum": list(layer_enum.keys())
                                    if layer_enum
                                    else ["NO_UNATTACHED_LAYERS"],
                                },
                                "new_name": {
                                    "type": "string",
                                    "description": "Sets a new human-readable name for this layer. This name will appear in the layer list/legend for the user.",
                                },
                            },
                            "required": ["layer_id", "new_name"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "create_layer_style",
                        "description": "Creates a new style for a layer with MapLibre JSON layers. Automatically renders the style for visual inspection.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "layer_id": {
                                    "type": "string",
                                    "description": "The ID of the layer to create a style for",
                                },
                                "maplibre_json_layers_str": {
                                    "type": "string",
                                    "description": 'JSON string of MapLibre layer objects. Example: [{"id": "LZJ5RmuZr6qN-line", "type": "line", "source": "LZJ5RmuZr6qN", "paint": {"line-color": "#1E90FF"}}]',
                                },
                            },
                            "required": ["layer_id", "maplibre_json_layers_str"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "set_active_style",
                        "description": "Sets a style as active for a layer in a map",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "layer_id": {
                                    "type": "string",
                                    "description": "The ID of the layer",
                                },
                                "style_id": {
                                    "type": "string",
                                    "description": "The ID of the style to set as active",
                                },
                            },
                            "required": ["layer_id", "style_id"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "query_duckdb_sql",
                        "description": "Execute a SQL query against vector layer data using DuckDB",
                        "strict": True,
                        "parameters": {
                            "type": "object",
                            "required": ["layer_ids", "sql_query", "head_n_rows"],
                            "properties": {
                                "layer_ids": {
                                    "type": "array",
                                    "description": "Load these vector layer IDs as tables",
                                    "items": {"type": "string"},
                                },
                                "sql_query": {
                                    "type": "string",
                                    "description": "E.g. SELECT name_en,county FROM LCH6Na2SBvJr ORDER BY id",
                                },
                                "head_n_rows": {
                                    "type": "number",
                                    "description": "Truncate result to n rows (increase gingerly, MUST specify returned columns), n=20 is good",
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "query_postgis_database",
                        "description": "Execute SQL queries on connected PostgreSQL/PostGIS databases. Use for data analysis, spatial queries, and exploring database tables. The query should be safe and read-only.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "sql_query": {
                                    "type": "string",
                                    "description": "SQL query to execute. Examples: 'SELECT COUNT(*) FROM table_name', 'SELECT * FROM spatial_table LIMIT 10', 'SELECT column_name FROM information_schema.columns WHERE table_name = \"my_table\"'. Use standard SQL syntax.",
                                },
                                "limit_rows": {
                                    "type": "integer",
                                    "description": "Maximum number of rows to return (default: 100, max: 1000)",
                                    "default": 100,
                                    "maximum": 1000,
                                },
                            },
                            "required": ["sql_query"],
                            "additionalProperties": False,
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "zoom_to_bounds",
                        "description": "Zoom the map to a specific bounding box in WGS84 coordinates. This will save the current zoom location to history and navigate to the new bounds.",
                        "strict": True,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "bounds": {
                                    "type": "array",
                                    "description": "Bounding box in WGS84 format [west, south, east, north] or [xmin, ymin, xmax, ymax]",
                                    "items": {"type": "number"},
                                    "minItems": 4,
                                    "maxItems": 4,
                                },
                                "zoom_description": {
                                    "type": "string",
                                    "description": "Optional description of what this zoom operation shows (e.g. 'Downtown Seattle', 'Layer bounds')",
                                },
                            },
                            "required": ["bounds"],
                            "additionalProperties": False,
                        },
                    },
                },
            ]

            # Conditionally add OpenStreetMap tool if API key is configured
            if has_openstreetmap_api_key():
                tools_payload.append(
                    {
                        "type": "function",
                        "function": {
                            "name": "download_from_openstreetmap",
                            "description": "Download features from OSM and add to project as a cloud FlatGeobuf layer",
                            "strict": True,
                            "parameters": {
                                "type": "object",
                                "required": [
                                    "tags",
                                    "bbox",
                                    "new_layer_name",
                                ],
                                "properties": {
                                    "tags": {
                                        "type": "string",
                                        "description": "Tags to filter for e.g. leisure=park, use & to AND tags together e.g. highway=footway&name=*, no commas",
                                    },
                                    "bbox": {
                                        "type": "array",
                                        "description": "Bounding box in [xmin, ymin, xmax, ymax] format e.g. [9.023802,39.172149,9.280779,39.275211] for Cagliari, Italy",
                                        "items": {"type": "number"},
                                    },
                                    "new_layer_name": {
                                        "type": "string",
                                        "description": "Human-friendly name e.g. Walking paths or Liquor stores in Seattle",
                                    },
                                },
                                "additionalProperties": False,
                            },
                        },
                    }
                )

            if not layer_enum:
                add_layer_tool = next(
                    tool
                    for tool in tools_payload
                    if tool["function"]["name"] == "add_layer_to_map"
                )
                add_layer_tool["function"]["parameters"]["properties"]["layer_id"].pop(
                    "enum", None
                )

            # Replace the thinking ephemeral updates with context manager
            async with kue_ephemeral_action(map_id, "Kue is thinking..."):
                chat_completions_args = await chat_args.get_args(
                    user_id, "send_map_message_async"
                )
                response = await client.chat.completions.create(
                    **chat_completions_args,
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt_provider.get_system_prompt(),
                        }
                    ]
                    + openai_messages,
                    tools=tools_payload if tools_payload else None,
                    tool_choice="auto" if tools_payload else None,
                )

            assistant_message = response.choices[0].message

            # Store the assistant message in the database
            add_chat_completion_message(assistant_message)

            # If no tool calls, break
            if not assistant_message.tool_calls:
                break

            for tool_call in assistant_message.tool_calls:
                function_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                tool_result = {}
                if function_name == "new_layer_from_postgis":
                    postgis_connection_id = tool_args.get("postgis_connection_id")
                    query = tool_args.get("query")
                    layer_name = tool_args.get("layer_name")

                    if not postgis_connection_id or not query:
                        tool_result = {
                            "status": "error",
                            "error": "Missing required parameters (postgis_connection_id or query).",
                        }
                    else:
                        # Verify the PostGIS connection exists and user has access
                        cursor.execute(
                            """
                            SELECT connection_uri FROM project_postgres_connections
                            WHERE id = %s AND user_id = %s
                            """,
                            (postgis_connection_id, user_id),
                        )
                        connection_result = cursor.fetchone()

                        if not connection_result:
                            tool_result = {
                                "status": "error",
                                "error": f"PostGIS connection '{postgis_connection_id}' not found or you do not have access to it.",
                            }
                        else:
                            try:
                                # Validate the query before creating the layer
                                conn_uri = connection_result["connection_uri"]
                                pg = await asyncpg.connect(
                                    conn_uri,
                                    server_settings={
                                        "default_transaction_read_only": "on"
                                    },
                                )
                                try:
                                    # 1. Make sure the SQL parsers and planners are happy
                                    await pg.execute(
                                        f"EXPLAIN {query}"
                                    )  # catches typos & ambiguous refs

                                    # 2. Make sure it returns a geometry column called geom
                                    await pg.execute(
                                        f"""
                                        SELECT 1
                                        FROM   ({query}) AS sub
                                        WHERE  geom IS NOT NULL
                                        LIMIT 1
                                        """
                                    )
                                finally:
                                    await pg.close()

                                # Calculate feature count, bounds, and geometry type for the PostGIS layer
                                feature_count = None
                                bounds = None
                                geometry_type = None
                                try:
                                    pg_stats = await asyncpg.connect(
                                        conn_uri,
                                        server_settings={
                                            "default_transaction_read_only": "on"
                                        },
                                    )

                                    try:
                                        # Calculate feature count
                                        count_result = await pg_stats.fetchval(
                                            f"SELECT COUNT(*) FROM ({query}) AS sub"
                                        )
                                        feature_count = (
                                            int(count_result)
                                            if count_result is not None
                                            else None
                                        )

                                        # Find geometry column by trying common names
                                        geometry_column = None
                                        common_geom_names = [
                                            "geom",
                                            "geometry",
                                            "shape",
                                            "the_geom",
                                            "wkb_geometry",
                                        ]

                                        for geom_name in common_geom_names:
                                            try:
                                                await pg_stats.fetchval(
                                                    f"SELECT 1 FROM ({query}) AS sub WHERE {geom_name} IS NOT NULL LIMIT 1"
                                                )
                                                geometry_column = geom_name
                                                break
                                            except Exception:
                                                continue

                                        if geometry_column:
                                            # Detect geometry type for styling
                                            geometry_type_result = await pg_stats.fetchrow(
                                                f"""
                                                SELECT ST_GeometryType({geometry_column}) as geom_type, COUNT(*) as count
                                                FROM ({query}) AS sub
                                                WHERE {geometry_column} IS NOT NULL
                                                GROUP BY ST_GeometryType({geometry_column})
                                                ORDER BY count DESC
                                                LIMIT 1
                                                """
                                            )

                                            if (
                                                geometry_type_result
                                                and geometry_type_result["geom_type"]
                                            ):
                                                # Convert PostGIS geometry type to standard format
                                                geometry_type = (
                                                    geometry_type_result["geom_type"]
                                                    .replace("ST_", "")
                                                    .lower()
                                                )

                                            # Calculate bounds with proper SRID handling
                                            # ST_Extent returns BOX2D with SRID 0, so we need to set the SRID before transforming
                                            bounds_result = await pg_stats.fetchrow(
                                                f"""
                                                WITH extent_data AS (
                                                    SELECT
                                                        ST_Extent({geometry_column}) as extent_geom,
                                                        (SELECT ST_SRID({geometry_column}) FROM ({query}) AS sub2 WHERE {geometry_column} IS NOT NULL LIMIT 1) as original_srid
                                                    FROM ({query}) AS sub
                                                    WHERE {geometry_column} IS NOT NULL
                                                )
                                                SELECT
                                                    CASE
                                                        WHEN original_srid = 4326 THEN
                                                            ST_XMin(extent_geom)
                                                        ELSE
                                                            ST_XMin(ST_Transform(ST_SetSRID(extent_geom, original_srid), 4326))
                                                    END as xmin,
                                                    CASE
                                                        WHEN original_srid = 4326 THEN
                                                            ST_YMin(extent_geom)
                                                        ELSE
                                                            ST_YMin(ST_Transform(ST_SetSRID(extent_geom, original_srid), 4326))
                                                    END as ymin,
                                                    CASE
                                                        WHEN original_srid = 4326 THEN
                                                            ST_XMax(extent_geom)
                                                        ELSE
                                                            ST_XMax(ST_Transform(ST_SetSRID(extent_geom, original_srid), 4326))
                                                    END as xmax,
                                                    CASE
                                                        WHEN original_srid = 4326 THEN
                                                            ST_YMax(extent_geom)
                                                        ELSE
                                                            ST_YMax(ST_Transform(ST_SetSRID(extent_geom, original_srid), 4326))
                                                    END as ymax
                                                FROM extent_data
                                                WHERE extent_geom IS NOT NULL
                                                """
                                            )

                                            if bounds_result and all(
                                                v is not None for v in bounds_result
                                            ):
                                                bounds = [
                                                    float(bounds_result["xmin"]),
                                                    float(bounds_result["ymin"]),
                                                    float(bounds_result["xmax"]),
                                                    float(bounds_result["ymax"]),
                                                ]
                                        else:
                                            print(
                                                "Warning: No geometry column found in PostGIS query"
                                            )
                                    finally:
                                        await pg_stats.close()
                                except Exception as e:
                                    print(
                                        f"Warning: Failed to calculate feature count/bounds for PostGIS layer: {str(e)}"
                                    )
                                    feature_count = None
                                    bounds = None

                                # Generate a new layer ID
                                layer_id = generate_id(prefix="L")

                                # Generate default style if geometry type was detected
                                maplibre_layers = None
                                if geometry_type:
                                    try:
                                        maplibre_layers = (
                                            generate_maplibre_layers_for_layer_id(
                                                layer_id, geometry_type
                                            )
                                        )
                                        # PostGIS layers use MVT tiles, so source-layer is 'reprojectedfgb'
                                        # This matches the expectation in the style generation function
                                        print(
                                            f"Generated default style for PostGIS layer {layer_id} with geometry type {geometry_type}"
                                        )
                                    except Exception as e:
                                        print(
                                            f"Warning: Failed to generate default style for PostGIS layer: {str(e)}"
                                        )
                                        maplibre_layers = None

                                # Create the layer in the database
                                cursor.execute(
                                    """
                                    INSERT INTO map_layers
                                    (layer_id, owner_uuid, name, path, type, postgis_connection_id, postgis_query, feature_count, bounds, geometry_type, created_on, last_edited)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                                    """,
                                    (
                                        layer_id,
                                        user_id,
                                        layer_name,
                                        "",  # Empty path for PostGIS layers
                                        "postgis",
                                        postgis_connection_id,
                                        query,
                                        feature_count,
                                        bounds,
                                        geometry_type,
                                    ),
                                )

                                # Create default style in separate table if we have geometry type
                                if maplibre_layers:
                                    style_id = generate_id(prefix="S")
                                    cursor.execute(
                                        """
                                        INSERT INTO layer_styles
                                        (style_id, layer_id, style_json, created_by, created_on)
                                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                                        """,
                                        (
                                            style_id,
                                            layer_id,
                                            psycopg2.extras.Json(maplibre_layers),
                                            user_id,
                                        ),
                                    )

                                    cursor.execute(
                                        """
                                        INSERT INTO map_layer_styles
                                        (map_id, layer_id, style_id)
                                        VALUES (%s, %s, %s)
                                        """,
                                        (map_id, layer_id, style_id),
                                    )

                                cursor.execute(
                                    """
                                    UPDATE user_mundiai_maps
                                    SET layers = array_append(layers, %s)
                                    WHERE id = %s AND NOT (%s = ANY(layers))
                                    """,
                                    (layer_id, map_id, layer_id),
                                )

                                conn.commit()

                                tool_result = {
                                    "status": "success",
                                    "message": f"PostGIS layer created successfully with ID: {layer_id} and added to map",
                                    "layer_id": layer_id,
                                    "query": query,
                                    "added_to_map": True,
                                }
                            except Exception as e:
                                tool_result = {
                                    "status": "error",
                                    "error": f"Query validation failed: {str(e)}",
                                }

                    add_chat_completion_message(
                        ChatCompletionToolMessageParam(
                            role="tool",
                            tool_call_id=tool_call.id,
                            content=json.dumps(tool_result),
                        )
                    )
                elif function_name == "add_layer_to_map":
                    layer_id_to_add = tool_args.get("layer_id")
                    new_name = tool_args.get("new_name")

                    cursor.execute(
                        """
                        SELECT layer_id FROM map_layers
                        WHERE layer_id = %s AND owner_uuid = %s
                        """,
                        (layer_id_to_add, user_id),
                    )
                    layer_exists = cursor.fetchone()

                    if not layer_exists:
                        tool_result = {
                            "status": "error",
                            "error": f"Layer ID '{layer_id_to_add}' not found or you do not have permission to use it.",
                        }
                    else:
                        cursor.execute(
                            """
                            UPDATE map_layers SET name = %s WHERE layer_id = %s
                            """,
                            (new_name, layer_id_to_add),
                        )

                        cursor.execute(
                            """
                            UPDATE user_mundiai_maps
                            SET layers = array_append(layers, %s)
                            WHERE id = %s AND NOT (%s = ANY(layers))
                            """,
                            (layer_id_to_add, map_id, layer_id_to_add),
                        )
                        tool_result = {
                            "status": f"Layer '{new_name}' (ID: {layer_id_to_add}) added to map '{map_id}'.",
                            "layer_id": layer_id_to_add,
                            "name": new_name,
                        }

                    add_chat_completion_message(
                        ChatCompletionToolMessageParam(
                            role="tool",
                            tool_call_id=tool_call.id,
                            content=json.dumps(tool_result),
                        )
                    )
                elif function_name == "query_duckdb_sql":
                    layer_id = tool_args.get("layer_ids", [None])[
                        0
                    ]  # Use first layer or None
                    sql_query = tool_args.get("sql_query")
                    head_n_rows = tool_args.get("head_n_rows", 20)

                    cursor.execute(
                        """
                        SELECT layer_id FROM map_layers
                        WHERE layer_id = %s AND owner_uuid = %s
                        """,
                        (layer_id, user_id),
                    )
                    layer_exists = cursor.fetchone()

                    if not layer_exists:
                        tool_result = {
                            "status": "error",
                            "error": f"Layer ID '{layer_id}' not found or you do not have permission to access it.",
                        }
                        add_chat_completion_message(
                            ChatCompletionToolMessageParam(
                                role="tool",
                                tool_call_id=tool_call.id,
                                content=json.dumps(tool_result),
                            )
                        )
                        continue

                    try:
                        # Execute the query using the async function
                        async with kue_ephemeral_action(
                            map_id, "Querying with SQL...", layer_id=layer_id
                        ):
                            result = await execute_duckdb_query(
                                sql_query=sql_query,
                                layer_id=layer_id,
                                max_n_rows=head_n_rows,
                                timeout=10,
                            )

                        # Convert result to CSV format
                        df = pd.DataFrame(result["result"], columns=result["headers"])
                        result_text = df.to_csv(index=False)

                        if len(result_text) > 25000:
                            tool_result = {
                                "status": "error",
                                "error": f"DuckDB CSV result too large: {len(result_text)} characters exceeds 25,000 character limit, try reducing columns or head_n_rows",
                            }
                        else:
                            tool_result = {
                                "status": "success",
                                "result": result_text,
                                "row_count": result["row_count"],
                                "query": sql_query,
                            }
                    except HTTPException as e:
                        tool_result = {
                            "status": "error",
                            "error": f"DuckDB query error: {e.detail}",
                        }
                    except Exception as e:
                        tool_result = {
                            "status": "error",
                            "error": f"Error executing SQL query: {str(e)}",
                        }

                    add_chat_completion_message(
                        ChatCompletionToolMessageParam(
                            role="tool",
                            tool_call_id=tool_call.id,
                            content=json.dumps(tool_result),
                        )
                    )
                elif function_name == "create_layer_style":
                    layer_id = tool_args.get("layer_id")
                    maplibre_json_layers_str = tool_args.get("maplibre_json_layers_str")

                    if not layer_id or not maplibre_json_layers_str:
                        tool_result = {
                            "status": "error",
                            "error": "Missing required parameters (layer_id or maplibre_json_layers_str).",
                        }
                    else:
                        # Generate a new style ID
                        style_id = generate_id(prefix="S")

                        try:
                            layers = json.loads(maplibre_json_layers_str)

                            # Validate that layers is a list
                            if not isinstance(layers, list):
                                raise ValueError(
                                    f"Expected a JSON array of layer objects, but got {type(layers).__name__}: {repr(layers)[:200]}"
                                )

                            # Add source-layer property if missing to fix KeyError: 'source-layer'
                            for layer in layers:
                                if isinstance(layer, dict):
                                    layer["source-layer"] = "reprojectedfgb"
                                else:
                                    raise ValueError(
                                        f"Expected layer object to be a dict, but got {type(layer).__name__}: {repr(layer)[:200]}"
                                    )

                            # Get complete map style with our layer styling to validate it
                            base_map_provider = get_base_map_provider()
                            style_json = await get_map_style_internal(
                                map_id=map_id,
                                base_map=base_map_provider,
                                only_show_inline_sources=True,
                                override_layers=json.dumps({layer_id: layers}),
                            )

                            # Validate the complete style
                            verify_style_json_str(json.dumps(style_json))

                            # If validation passes, create the style in the database
                            cursor.execute(
                                """
                                INSERT INTO layer_styles
                                (style_id, layer_id, style_json, created_by)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (style_id, layer_id, json.dumps(layers), user_id),
                            )
                            conn.commit()

                            tool_result = {
                                "status": "success",
                                "style_id": style_id,
                                "layer_id": layer_id,
                            }
                        except json.JSONDecodeError as e:
                            print(f"JSON decode error: {str(e)}")
                            tool_result = {
                                "status": "error",
                                "error": f"Invalid JSON format: {str(e)}",
                                "layer_id": layer_id,
                            }
                        except ValueError as e:
                            print(f"Value error in layer style: {str(e)}")
                            tool_result = {
                                "status": "error",
                                "error": str(e),
                                "layer_id": layer_id,
                            }
                        except StyleValidationError as e:
                            print(
                                f"Style validation error: {str(e)}",
                                traceback.format_exc(),
                                type(e),
                            )
                            tool_result = {
                                "status": "error",
                                "error": f"Style validation failed: {str(e)}",
                                "layer_id": layer_id,
                            }

                    add_chat_completion_message(
                        ChatCompletionToolMessageParam(
                            role="tool",
                            tool_call_id=tool_call.id,
                            content=json.dumps(tool_result),
                        ),
                    )
                elif function_name == "set_active_style":
                    layer_id = tool_args.get("layer_id")
                    style_id = tool_args.get("style_id")

                    if not all([layer_id, style_id]):
                        tool_result = {
                            "status": "error",
                            "error": "Missing required parameters (layer_id, or style_id).",
                        }
                    else:
                        # Add or update the map_layer_styles entry
                        async with kue_ephemeral_action(
                            map_id,
                            "Choosing a new style",
                            update_style_json=True,
                        ):
                            cursor.execute(
                                """
                                INSERT INTO map_layer_styles (map_id, layer_id, style_id)
                                VALUES (%s, %s, %s)
                                ON CONFLICT (map_id, layer_id)
                                DO UPDATE SET style_id = %s
                                """,
                                (map_id, layer_id, style_id, style_id),
                            )
                            conn.commit()

                        tool_result = {
                            "status": "success",
                            "message": f"Style {style_id} set as active for layer {layer_id}, user can now see it",
                            "layer_id": layer_id,
                            "style_id": style_id,
                        }

                    add_chat_completion_message(
                        ChatCompletionToolMessageParam(
                            role="tool",
                            tool_call_id=tool_call.id,
                            content=json.dumps(tool_result),
                        ),
                    )
                elif function_name == "download_from_openstreetmap":
                    tags = tool_args.get("tags")
                    bbox = tool_args.get("bbox")
                    new_layer_name = tool_args.get("new_layer_name")

                    if not all([tags, bbox, new_layer_name]):
                        tool_result = {
                            "status": "error",
                            "error": "Missing required parameters for OpenStreetMap download.",
                        }
                    else:
                        try:
                            # Keep context manager only around the specific API call
                            async with kue_ephemeral_action(
                                map_id, f"Downloading data from OpenStreetMap: {tags}"
                            ):
                                tool_result = await download_from_openstreetmap(
                                    request=request,
                                    map_id=map_id,
                                    bbox=bbox,
                                    tags=tags,
                                    new_layer_name=new_layer_name,
                                    session=session,
                                )
                        except Exception as e:
                            print(traceback.format_exc())
                            print(e)
                            tool_result = {
                                "status": "error",
                                "error": f"Error downloading from OpenStreetMap: {str(e)}",
                            }
                    # Add instructions to tool result if download was successful
                    if tool_result.get("status") == "success" and tool_result.get(
                        "uploaded_layers"
                    ):
                        uploaded_layers = tool_result.get("uploaded_layers")
                        layer_names = [
                            f"{new_layer_name}_{layer['geometry_type']}"
                            for layer in uploaded_layers
                        ]
                        layer_ids = [layer["layer_id"] for layer in uploaded_layers]
                        tool_result["kue_instructions"] = (
                            f"New layers available: {', '.join(layer_names)} "
                            f"(IDs: {', '.join(layer_ids)}), all currently invisible. "
                            'To make any of these visible to the user on their map, use "add_layer_to_map" with the layer_id and a descriptive new_name.'
                        )

                    add_chat_completion_message(
                        ChatCompletionToolMessageParam(
                            role="tool",
                            tool_call_id=tool_call.id,
                            content=json.dumps(tool_result),
                        ),
                    )
                elif function_name == "query_postgis_database":
                    sql_query = tool_args.get("sql_query")
                    limit_rows = tool_args.get("limit_rows", 100)

                    if not sql_query:
                        tool_result = {
                            "status": "error",
                            "error": "Missing required parameter: sql_query",
                        }
                    else:
                        # Get the project's PostgreSQL connection URIs
                        cursor.execute(
                            """
                            SELECT ppc.connection_uri
                            FROM project_postgres_connections ppc
                            JOIN user_mundiai_maps m ON m.project_id = ppc.project_id
                            WHERE m.id = %s
                            ORDER BY ppc.created_at ASC
                            LIMIT 1
                            """,
                            (map_id,),
                        )
                        project_result = cursor.fetchone()

                        if not project_result:
                            tool_result = {
                                "status": "error",
                                "error": "No PostgreSQL connections configured for this project",
                            }
                        else:
                            # Use the first connection URI
                            connection_uri = project_result["connection_uri"]

                            try:
                                # Clamp limit_rows to be between 1 and 1000
                                limit_rows = max(1, min(limit_rows, 1000))

                                # Add LIMIT clause if not already present
                                limited_query = sql_query.strip()
                                if not limited_query.upper().endswith(
                                    ("LIMIT", f"LIMIT {limit_rows}")
                                ):
                                    if "LIMIT" not in limited_query.upper():
                                        limited_query += f" LIMIT {limit_rows}"

                                async with kue_ephemeral_action(
                                    map_id, "Querying PostgreSQL database..."
                                ):
                                    postgres_conn = await asyncpg.connect(
                                        connection_uri,
                                        server_settings={
                                            "default_transaction_read_only": "on"
                                        },
                                    )
                                    try:
                                        # Execute the query
                                        rows = await postgres_conn.fetch(limited_query)

                                        if not rows:
                                            tool_result = {
                                                "status": "success",
                                                "message": "Query executed successfully but returned no rows",
                                                "row_count": 0,
                                                "query": limited_query,
                                            }
                                        else:
                                            # Convert rows to list of dicts
                                            result_data = [dict(row) for row in rows]

                                            # Format the result as a readable string
                                            if (
                                                len(result_data) == 1
                                                and len(result_data[0]) == 1
                                            ):
                                                # Single value result
                                                single_value = list(
                                                    result_data[0].values()
                                                )[0]
                                                result_text = (
                                                    f"Query result: {single_value}"
                                                )
                                            else:
                                                # Table format
                                                if result_data:
                                                    headers = list(
                                                        result_data[0].keys()
                                                    )
                                                    result_lines = ["\t".join(headers)]
                                                    for row in result_data:
                                                        result_lines.append(
                                                            "\t".join(
                                                                str(row.get(h, ""))
                                                                for h in headers
                                                            )
                                                        )
                                                    result_text = "\n".join(
                                                        result_lines
                                                    )
                                                else:
                                                    result_text = "No results"

                                            # Check if result is too large
                                            if len(result_text) > 25000:
                                                tool_result = {
                                                    "status": "error",
                                                    "error": f"Query result too large: {len(result_text)} characters exceeds 25,000 character limit. Try reducing the number of columns or rows.",
                                                }
                                            else:
                                                tool_result = {
                                                    "status": "success",
                                                    "result": result_text,
                                                    "row_count": len(result_data),
                                                    "query": limited_query,
                                                }
                                    finally:
                                        await postgres_conn.close()

                            except Exception as e:
                                tool_result = {
                                    "status": "error",
                                    "error": f"PostgreSQL query error: {str(e)}",
                                    "query": limited_query,
                                }

                    add_chat_completion_message(
                        ChatCompletionToolMessageParam(
                            role="tool",
                            tool_call_id=tool_call.id,
                            content=json.dumps(tool_result),
                        ),
                    )
                elif function_name == "zoom_to_bounds":
                    bounds = tool_args.get("bounds")
                    description = tool_args.get("zoom_description", "")

                    if not bounds or len(bounds) != 4:
                        tool_result = {
                            "status": "error",
                            "error": "Invalid bounds. Must be an array of 4 numbers [west, south, east, north]",
                        }
                    else:
                        try:
                            # Validate bounds format
                            west, south, east, north = bounds
                            if not all(
                                isinstance(coord, (int, float)) for coord in bounds
                            ):
                                raise ValueError(
                                    "All bounds coordinates must be numbers"
                                )

                            if west >= east or south >= north:
                                raise ValueError(
                                    "Invalid bounds: west must be < east and south must be < north"
                                )

                            if not (
                                -180 <= west <= 180
                                and -180 <= east <= 180
                                and -90 <= south <= 90
                                and -90 <= north <= 90
                            ):
                                raise ValueError("Bounds must be in valid WGS84 range")

                            # Send ephemeral action to trigger zoom on frontend
                            async with kue_ephemeral_action(
                                map_id,
                                f"Zooming to bounds{': ' + description if description else ''}",
                                update_style_json=False,
                            ):
                                # Send zoom action via WebSocket
                                zoom_action = {
                                    "map_id": map_id,
                                    "ephemeral": True,
                                    "action_id": str(uuid.uuid4()),
                                    "action": "zoom_to_bounds",
                                    "bounds": bounds,
                                    "description": description,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "status": "zoom_action",
                                }

                                zoom_payload_str = json.dumps(zoom_action)

                                # Broadcast zoom action to WebSocket subscribers
                                async with subscribers_lock:
                                    queues = list(subscribers_by_map.get(map_id, []))
                                for q in queues:
                                    q.put_nowait(zoom_payload_str)

                            tool_result = {
                                "status": "success",
                                "message": f"Zoomed to bounds {bounds}{': ' + description if description else ''}",
                                "bounds": bounds,
                            }
                        except ValueError as e:
                            tool_result = {
                                "status": "error",
                                "error": str(e),
                            }
                        except Exception as e:
                            tool_result = {
                                "status": "error",
                                "error": f"Error zooming to bounds: {str(e)}",
                            }

                    add_chat_completion_message(
                        ChatCompletionToolMessageParam(
                            role="tool",
                            tool_call_id=tool_call.id,
                            content=json.dumps(tool_result),
                        ),
                    )
                else:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

            # Commit all DB changes for this turn (OpenAI response + all tool calls/responses + system msgs)
            conn.commit()

        # Unlock the map when processing is complete
        redis.delete(f"map_lock:{map_id}")


class MessageSendResponse(BaseModel):
    job_id: str
    message_id: str
    status: str


@router.post(
    "/{map_id}/messages/send",
    response_model=MessageSendResponse,
    operation_id="send_map_message_async",
)
async def send_map_message_async(
    request: Request,
    map_id: str,
    message: ChatCompletionUserMessageParam,
    background_tasks: BackgroundTasks,
    session: UserContext = Depends(verify_session_required),
    postgis_provider: Callable = Depends(get_postgis_provider),
    layer_describer: LayerDescriber = Depends(get_layer_describer),
    chat_args: ChatArgsProvider = Depends(get_chat_args_provider),
    map_state: MapStateProvider = Depends(get_map_state_provider),
    system_prompt_provider: SystemPromptProvider = Depends(get_system_prompt_provider),
):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Authenticate and check map
        cursor.execute(
            "SELECT owner_uuid FROM user_mundiai_maps WHERE id = %s AND soft_deleted_at IS NULL",
            (map_id,),
        )
        map_result = cursor.fetchone()

        if not map_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
            )

        user_id = session.get_user_id()
        if user_id != str(map_result["owner_uuid"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )

        # Check if map is already being processed
        lock_key = f"map_lock:{map_id}"
        if redis.get(lock_key):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Map is currently being processed by another request",
            )

        # Lock the map for processing
        redis.set(lock_key, "locked", ex=60)  # 60 second expiry

        # Use map state provider to generate system messages
        messages_response = await get_all_map_messages(map_id, session)
        current_messages = [
            msg["message_json"] for msg in messages_response["messages"]
        ]

        current_map_description = await get_map_description(
            request,
            map_id,
            session,
            postgis_provider=postgis_provider,
            layer_describer=layer_describer,
        )
        description_text = current_map_description.body.decode("utf-8")

        # Get system messages from the provider
        system_messages = await map_state.get_system_messages(
            current_messages, description_text
        )

        # Add any generated system messages to the database
        for system_msg in system_messages:
            system_message = ChatCompletionSystemMessageParam(
                role="system",
                content=system_msg["content"],
            )
            add_chat_completion_message_args(cursor, map_id, user_id, system_message)

        # Add user's message to DB
        user_msg_db = add_chat_completion_message_args(
            cursor,
            map_id,
            user_id,
            message,
        )
        conn.commit()

        job_id = str(uuid.uuid4())
        chat_channels[job_id] = asyncio.Queue()

        # Start background task
        background_tasks.add_task(
            process_chat_interaction_task,
            request,
            map_id,
            session,
            user_id,
            chat_args,
            map_state,
            system_prompt_provider,
        )

        return MessageSendResponse(
            job_id=job_id,
            message_id=str(user_msg_db["id"]),
            status="processing_started",
        )


@router.post(
    "/{map_id}/messages/cancel",
    operation_id="cancel_map_message",
    response_class=JSONResponse,
)
async def cancel_map_message(
    request: Request,
    map_id: str,
    session: UserContext = Depends(verify_session_required),
):
    async with get_async_db_connection() as conn:
        # Authenticate and check map
        map_result = await conn.fetchrow(
            "SELECT owner_uuid FROM user_mundiai_maps WHERE id = $1 AND soft_deleted_at IS NULL",
            map_id,
        )

        if not map_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
            )

        if session.get_user_id() != str(map_result["owner_uuid"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        redis.set(f"messages:{map_id}:cancelled", "true", ex=300)  # 5 minute expiry

        return JSONResponse(content={"status": "cancelled"})


CHAT_CH = "chat_completion_messages_notify"
chat_q: asyncio.Queue[str] = asyncio.Queue()
# Initialize listener task at module level
listener_task = None


def start_chat_listener():
    global listener_task

    if listener_task is None or listener_task.done():
        user = os.environ["POSTGRES_USER"]
        password = os.environ["POSTGRES_PASSWORD"]
        host = os.environ["POSTGRES_HOST"]
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ["POSTGRES_DB"]
        dsn = f"postgresql://{user}:{password}@{host}:{port}/{db}"
        listener_task = asyncio.create_task(_chat_pg_listener(dsn=dsn))

    return listener_task


@router.on_event("startup")
async def startup_listener():
    start_chat_listener()
    # Start cleanup task for recently disconnected users
    asyncio.create_task(cleanup_recently_disconnected_users())


async def _chat_pg_listener(dsn: str):
    try:
        conn = await asyncpg.connect(dsn)

        await conn.add_listener(
            CHAT_CH,
            lambda _conn, _pid, _channel, payload: asyncio.create_task(
                _broadcast_payload(payload)
            ),
        )

        while True:
            await asyncio.sleep(3600)
    except Exception:
        traceback.print_exc()
    finally:
        try:
            await conn.close()
        except Exception:
            pass


async def cleanup_recently_disconnected_users():
    """Periodically clean up expired disconnected users"""
    while True:
        try:
            await asyncio.sleep(60)  # Run cleanup every minute
            now = time.time()

            # Clean up users who disconnected too long ago
            users_to_remove = []
            for (user_id, map_id), user_data in recently_disconnected_users.items():
                if now - user_data["disconnect_time"] > DISCONNECT_TTL:
                    users_to_remove.append((user_id, map_id))

            # Remove expired users
            for user_key in users_to_remove:
                del recently_disconnected_users[user_key]

        except Exception:
            logger.exception("Error in cleanup_recently_disconnected_users")


@router.websocket("/ws/{map_id}/messages/updates")
async def ws_map_chat(
    ws: WebSocket, map_id: str, user_context: UserContext = Depends(verify_websocket)
):
    # In edit mode, we don't require tokens for WebSocket connections
    auth_mode = os.environ.get("MUNDI_AUTH_MODE")
    token = ws.query_params.get("token")

    if not token and auth_mode != "edit":
        await ws.close(code=4401, reason="No token")
        return

    user_id = user_context.get_user_id()

    # Check if user owns the map (skip in edit mode since all maps are accessible)
    async with get_async_db_connection() as conn:
        map_result = await conn.fetchrow(
            """
            SELECT owner_uuid FROM user_mundiai_maps
            WHERE id = $1 AND soft_deleted_at IS NULL
            """,
            map_id,
        )

        # Only enforce ownership when running in view_only or production mode
        if not map_result or str(map_result["owner_uuid"]) != user_id:
            await ws.close(code=4403, reason="Unauthorized")
            return

    await ws.accept()
    queue = asyncio.Queue()
    async with subscribers_lock:
        subscribers_by_map[map_id].add(queue)

    # Check if this user recently disconnected from this specific map and replay their missed messages
    user_map_key = (user_id, map_id)
    if user_map_key in recently_disconnected_users:
        user_data = recently_disconnected_users[user_map_key]
        missed_messages = user_data["missed_messages"]

        # Replay all missed messages for this specific user on this specific map
        for ts, missed_payload in missed_messages:
            queue.put_nowait(missed_payload)

        # Remove user from recently disconnected since they've reconnected to this map
        del recently_disconnected_users[user_map_key]
    try:
        while True:
            queue_task = asyncio.create_task(queue.get())
            recv_task = asyncio.create_task(ws.receive())

            done, pending = await asyncio.wait(
                {queue_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
            )

            # client closed
            if recv_task in done:
                for task in pending:
                    task.cancel()
                break

            # got a payload
            payload = queue_task.result()
            recv_task.cancel()

            notification = json.loads(payload)

            # Check if this is an ephemeral message
            if notification.get("ephemeral"):
                # Send ephemeral message directly without DB lookup
                await ws.send_json(notification)
                continue
            # Get the full message from the database using the id from notification
            async with get_async_db_connection() as conn:
                message = await conn.fetchrow(
                    """
                    SELECT * FROM chat_completion_messages
                    WHERE id = $1 AND map_id = $2
                    """,
                    notification["id"],
                    notification["map_id"],
                )

                if message:
                    # Convert datetime and UUID objects to JSON serializable format
                    message_dict = dict(message)
                    for key, value in message_dict.items():
                        if isinstance(value, datetime):
                            message_dict[key] = value.isoformat()
                        elif (
                            hasattr(value, "__class__")
                            and value.__class__.__name__ == "UUID"
                        ):
                            message_dict[key] = str(value)
                        elif key == "message_json":
                            message_dict[key] = json.loads(value)

                    # Only send if message_json role is user or assistant and no tool_calls
                    message_json = message_dict.get("message_json", {})
                    role = message_json.get("role")
                    tool_calls = message_json.get("tool_calls")
                    if role in ("user", "assistant") and not tool_calls:
                        await ws.send_json(message_dict)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Unexpected WebSocket error for map {map_id}: {e}")
    finally:
        # Track this user as recently disconnected from this specific map
        user_map_key = (user_id, map_id)
        recently_disconnected_users[user_map_key] = {
            "disconnect_time": time.time(),
            "missed_messages": deque(),
        }

        async with subscribers_lock:
            subscribers_by_map[map_id].discard(queue)
            if not subscribers_by_map[map_id]:
                del subscribers_by_map[map_id]


async def _broadcast_payload(payload: str):
    try:
        record = json.loads(payload)
        map_id = record.get("map_id")
        now = time.time()

        # Store messages for recently disconnected users who might reconnect to this specific map
        users_to_remove = []
        for (
            user_id,
            disconnected_map_id,
        ), user_data in recently_disconnected_users.items():
            # Clean up users who disconnected too long ago
            if now - user_data["disconnect_time"] > DISCONNECT_TTL:
                users_to_remove.append((user_id, disconnected_map_id))
                continue

            # Only store messages for users who were disconnected from this specific map
            if disconnected_map_id == map_id:
                # Add message to their missed messages buffer
                missed_messages = user_data["missed_messages"]
                missed_messages.append((now, payload))

                # Limit buffer size
                while len(missed_messages) > MAX_MISSED_MESSAGES:
                    missed_messages.popleft()

        # Remove expired users
        for user_key in users_to_remove:
            del recently_disconnected_users[user_key]

        # Broadcast to live subscribers
        async with subscribers_lock:
            queues = list(subscribers_by_map.get(map_id, []))
        for q in queues:
            q.put_nowait(payload)
    except Exception:
        logger.exception("Error broadcasting payload")


@asynccontextmanager
async def kue_ephemeral_action(
    map_id: str,
    action_description: str,
    layer_id: str | None = None,
    update_style_json: bool = False,
):
    """
    Async context manager for ephemeral actions.
    Sends a websocket message with the action when entering,
    and automatically removes it when exiting the context.
    """
    action_id = str(uuid.uuid4())
    payload = {
        "map_id": map_id,
        "ephemeral": True,
        "action_id": action_id,
        "layer_id": layer_id,
        "action": action_description,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "status": "active",
        "updates": {
            "style_json": update_style_json,
        },
    }

    try:
        # Send the action started message
        payload_str = json.dumps(payload)

        # Store for recently disconnected users from this specific map
        now = time.time()
        users_to_remove = []
        for (
            user_id,
            disconnected_map_id,
        ), user_data in recently_disconnected_users.items():
            # Clean up users who disconnected too long ago
            if now - user_data["disconnect_time"] > DISCONNECT_TTL:
                users_to_remove.append((user_id, disconnected_map_id))
                continue

            # Only store messages for users who were disconnected from this specific map
            if disconnected_map_id == map_id:
                # Add message to their missed messages buffer
                missed_messages = user_data["missed_messages"]
                missed_messages.append((now, payload_str))

                # Limit buffer size
                while len(missed_messages) > MAX_MISSED_MESSAGES:
                    missed_messages.popleft()

        # Remove expired users
        for user_key in users_to_remove:
            del recently_disconnected_users[user_key]

        # Broadcast to live subscribers
        async with subscribers_lock:
            queues = list(subscribers_by_map.get(map_id, []))
        for q in queues:
            q.put_nowait(payload_str)

        # Yield control back to the caller
        yield payload

    finally:
        # Always send the action completed message
        payload["status"] = "completed"
        payload["completed_at"] = datetime.now(timezone.utc).isoformat()

        payload_str = json.dumps(payload)

        # Store completion for recently disconnected users from this specific map
        now = time.time()
        users_to_remove = []
        for (
            user_id,
            disconnected_map_id,
        ), user_data in recently_disconnected_users.items():
            # Clean up users who disconnected too long ago
            if now - user_data["disconnect_time"] > DISCONNECT_TTL:
                users_to_remove.append((user_id, disconnected_map_id))
                continue

            # Only store messages for users who were disconnected from this specific map
            if disconnected_map_id == map_id:
                # Add message to their missed messages buffer
                missed_messages = user_data["missed_messages"]
                missed_messages.append((now, payload_str))

                # Limit buffer size
                while len(missed_messages) > MAX_MISSED_MESSAGES:
                    missed_messages.popleft()

        # Remove expired users
        for user_key in users_to_remove:
            del recently_disconnected_users[user_key]

        # Broadcast to live subscribers
        async with subscribers_lock:
            queues = list(subscribers_by_map.get(map_id, []))
        for q in queues:
            q.put_nowait(payload_str)
