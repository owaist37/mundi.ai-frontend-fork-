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

import secrets
from pydantic import BaseModel, Field
from enum import Enum


class DAGEditOperationResponse(BaseModel):
    dag_child_map_id: str = Field(
        description="The ID of the new map created that contains the changes. Use this ID for further operations on the modified map."
    )
    dag_parent_map_id: str = Field(
        description="The ID of the original map which was copied to create the new map."
    )


def generate_id(length=12, prefix=""):
    """Generate a unique ID for the map or layer.

    Using characters [1-9A-HJ-NP-Za-km-z] (excluding 0, O, I, l)
    to avoid ambiguity in IDs.
    """
    assert len(prefix) in [0, 1], "Prefix must be at most 1 character"

    valid_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    result = "".join(secrets.choice(valid_chars) for _ in range(length - len(prefix)))
    return prefix + result


class ForkReason(Enum):
    """Reason for forking a map"""

    USER_EDIT = "user_edit"
    AI_EDIT = "ai_edit"


async def fork_map(map_id: str, user_id: str, fork_reason: ForkReason, conn) -> str:
    # Get the source map data
    source_map = await conn.fetchrow(
        """
        SELECT m.id, m.project_id, m.title, m.description, m.layers
        FROM user_mundiai_maps m
        WHERE m.id = $1 AND m.soft_deleted_at IS NULL
        """,
        map_id,
    )

    if not source_map:
        raise ValueError(f"Map {map_id} not found")

    # Generate new map ID
    new_map_id = generate_id(prefix="M")

    # Create new map as a copy of the source map
    await conn.fetchrow(
        """
        INSERT INTO user_mundiai_maps
        (id, project_id, owner_uuid, title, description, layers, display_as_diff, fork_reason)
        VALUES ($1, $2, $3, $4, $5, $6, TRUE, $7)
        RETURNING id, title, description, created_on, last_edited
        """,
        new_map_id,
        source_map["project_id"],
        user_id,
        source_map["title"],
        source_map["description"],
        source_map["layers"],
        fork_reason.value,
    )

    # Copy over all map_layer_styles to the new map
    if source_map["layers"]:
        await conn.execute(
            """
            INSERT INTO map_layer_styles (map_id, layer_id, style_id)
            SELECT $1, layer_id, style_id
            FROM map_layer_styles
            WHERE map_id = $2
            """,
            new_map_id,
            map_id,
        )

    # Update project to include the new map
    await conn.execute(
        """
        UPDATE user_mundiai_projects
        SET maps = array_append(maps, $1),
            map_diff_messages = array_append(map_diff_messages, $2)
        WHERE id = $3
        """,
        new_map_id,
        "N/A",
        source_map["project_id"],
    )

    return new_map_id
