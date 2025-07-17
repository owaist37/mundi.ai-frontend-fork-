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
from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Request,
    Depends,
    BackgroundTasks,
)
from fastapi.responses import Response
from pydantic import BaseModel
from ..dependencies.session import (
    verify_session_required,
    UserContext,
)
from typing import List, Optional
import logging
from datetime import datetime
from PIL import Image
from redis import Redis
import asyncio
import botocore

from src.utils import (
    get_bucket_name,
    get_async_s3_client,
)
import io
from opentelemetry import trace
from ..structures import get_async_db_connection
from ..dependencies.base_map import BaseMapProvider, get_base_map_provider
from ..dependencies.database_documenter import (
    DatabaseDocumenter,
    get_database_documenter,
)
from ..dependencies.postgres_connection import (
    PostgresConnectionManager,
    get_postgres_connection_manager,
    PostgresConnectionURIError,
    PostgresConfigurationError,
)
from src.routes.postgres_routes import (
    generate_id,
    get_map_style_internal,
    render_map_internal,
)

# Global semaphore to limit concurrent social image renderings
# This prevents OOM issues when many maps load simultaneously
SOCIAL_RENDER_SEMAPHORE = asyncio.Semaphore(2)  # Max 2 concurrent renders

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

redis = Redis(
    host=os.environ["REDIS_HOST"],
    port=int(os.environ["REDIS_PORT"]),
    decode_responses=True,
)

project_router = APIRouter()


class MostRecentVersion(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    last_edited: Optional[str] = None


class PostgresConnectionDetails(BaseModel):
    connection_id: str
    table_count: int
    friendly_name: str
    last_error_text: Optional[str] = None
    last_error_timestamp: Optional[datetime] = None


class ProjectResponse(BaseModel):
    id: str
    owner_uuid: str
    link_accessible: bool
    maps: Optional[List[str]] = None
    created_on: str
    most_recent_version: Optional[MostRecentVersion] = None
    postgres_connections: List[PostgresConnectionDetails] = []
    soft_deleted_at: Optional[datetime] = None


class UserProjectsResponse(BaseModel):
    projects: List[ProjectResponse]
    total_pages: int
    total_items: int


@project_router.get(
    "/", response_model=UserProjectsResponse, operation_id="list_user_projects"
)
async def list_user_projects(
    session: UserContext = Depends(verify_session_required),
    connection_manager: PostgresConnectionManager = Depends(
        get_postgres_connection_manager
    ),
    page: int = 1,
    limit: int = 12,
    include_deleted: bool = False,
):
    """
    List all projects associated with the authenticated user.
    A project is associated if the user is the owner, an editor, or a viewer.
    """
    user_id = session.get_user_id()

    # Calculate offset for pagination
    offset = (page - 1) * limit

    async with get_async_db_connection() as conn:
        # Get total count for pagination
        total_items = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM user_mundiai_projects p
            WHERE (
                p.owner_uuid = $1 OR
                $2 = ANY(p.editor_uuids) OR
                $3 = ANY(p.viewer_uuids)
            ) AND ($4 OR p.soft_deleted_at IS NULL)
            """,
            user_id,
            user_id,
            user_id,
            include_deleted,
        )

        # Calculate total pages
        total_pages = (total_items + limit - 1) // limit

        projects_data = await conn.fetch(
            """
            SELECT p.id, p.owner_uuid, p.link_accessible, p.maps, p.created_on, p.soft_deleted_at
            FROM user_mundiai_projects p
            WHERE (
                p.owner_uuid = $1 OR
                $2 = ANY(p.editor_uuids) OR
                $3 = ANY(p.viewer_uuids)
            ) AND ($4 OR p.soft_deleted_at IS NULL)
            ORDER BY p.created_on DESC
            LIMIT $5 OFFSET $6
            """,
            user_id,
            user_id,
            user_id,
            include_deleted,
            limit,
            offset,
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
                WHERE project_id = $1 AND soft_deleted_at IS NULL
                ORDER BY created_at ASC
                """,
                project_data["id"],
            )

            for postgres_conn_result in postgres_conn_results:
                connection_id = postgres_conn_result["id"]

                # Get AI-generated friendly name and table_count, fallback to connection_name if not available
                summary_result = await conn.fetchrow(
                    """
                    SELECT friendly_name, table_count
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
                table_count = (
                    summary_result["table_count"]
                    if summary_result and summary_result["table_count"] is not None
                    else 0
                )

                # Get error details from the database (they were stored during the connection attempt)
                connection_details = await connection_manager.get_connection(
                    connection_id
                )

                postgres_connections.append(
                    PostgresConnectionDetails(
                        connection_id=connection_id,
                        table_count=table_count,
                        friendly_name=friendly_name,
                        last_error_text=connection_details["last_error_text"],
                        last_error_timestamp=connection_details["last_error_timestamp"],
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
                    soft_deleted_at=project_data["soft_deleted_at"],
                )
            )

    return UserProjectsResponse(
        projects=projects_response,
        total_pages=total_pages,
        total_items=total_items,
    )


@project_router.get(
    "/{project_id}", response_model=ProjectResponse, operation_id="get_project"
)
async def get_project(
    project_id: str,
    session: UserContext = Depends(verify_session_required),
    connection_manager: PostgresConnectionManager = Depends(
        get_postgres_connection_manager
    ),
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
            WHERE project_id = $1 AND soft_deleted_at IS NULL
            ORDER BY created_at ASC
            """,
            project_data["id"],
        )

        for postgres_conn_result in postgres_conn_results:
            connection_id = postgres_conn_result["id"]

            # Get AI-generated friendly name and table_count, fallback to connection_name if not available
            summary_result = await conn.fetchrow(
                """
                SELECT friendly_name, table_count
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
            table_count = (
                summary_result["table_count"]
                if summary_result and summary_result["table_count"] is not None
                else 0
            )

            # Get error details from the database (they were stored during the connection attempt)
            connection_details = await connection_manager.get_connection(connection_id)

            postgres_connections.append(
                PostgresConnectionDetails(
                    connection_id=connection_id,
                    table_count=table_count,
                    friendly_name=friendly_name,
                    last_error_text=connection_details["last_error_text"],
                    last_error_timestamp=connection_details["last_error_timestamp"],
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

    async with get_async_db_connection() as conn:
        # First check if user is the owner
        project_data = await conn.fetchrow(
            """
            SELECT owner_uuid
            FROM user_mundiai_projects
            WHERE id = $1 AND soft_deleted_at IS NULL
            """,
            project_id,
        )

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
        await conn.execute(
            """
            UPDATE user_mundiai_projects
            SET link_accessible = $1
            WHERE id = $2
            """,
            update_data.link_accessible,
            project_id,
        )

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
    connection_manager: PostgresConnectionManager = Depends(
        get_postgres_connection_manager
    ),
):
    """
    Add a PostgreSQL connection URI to a project.
    Only the project owner or editors can add connections.
    """
    user_id = session.get_user_id()

    async with get_async_db_connection() as conn:
        # Check if user has access to the project
        project = await conn.fetchrow(
            """
            SELECT owner_uuid, editor_uuids
            FROM user_mundiai_projects
            WHERE id = $1 AND soft_deleted_at IS NULL
            """,
            project_id,
        )

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

        # Validate the connection URI format and accessibility
        connection_uri = connection_data.connection_uri.strip()

        # Handle demo database
        if connection_uri == "DEMO":
            demo_uri = os.environ.get("DEMO_POSTGIS_URI")
            if not demo_uri:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Demo database is not available",
                )
            connection_uri = demo_uri

        try:
            processed_uri, was_rewritten = connection_manager.verify_postgresql_uri(
                connection_uri
            )
            # Use the processed URI (which may have been rewritten for Docker)
            connection_uri = processed_uri
        except PostgresConnectionURIError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=e.message,
            )
        except PostgresConfigurationError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Check if connection already exists
        existing_conn = await conn.fetchrow(
            """
            SELECT id FROM project_postgres_connections
            WHERE project_id = $1 AND user_id = $2 AND connection_uri = $3 AND soft_deleted_at IS NULL
            """,
            project_id,
            user_id,
            connection_uri,
        )

        if not existing_conn:
            # Generate new connection ID
            connection_id = generate_id(prefix="C")

            # Insert the new connection
            await conn.execute(
                """
                INSERT INTO project_postgres_connections
                (id, project_id, user_id, connection_uri, connection_name)
                VALUES ($1, $2, $3, $4, $5)
                """,
                connection_id,
                project_id,
                user_id,
                connection_uri,
                connection_data.connection_name,
            )

            # Start background task to generate database documentation
            background_tasks.add_task(
                database_documenter.generate_documentation,
                connection_id,
                connection_uri,
                connection_data.connection_name or "Database",
                connection_manager,
            )

            return PostgresConnectionResponse(
                success=True, message="PostgreSQL connection added successfully"
            )
        else:
            return PostgresConnectionResponse(
                success=True, message="Connection URI already exists"
            )


@project_router.delete(
    "/{project_id}/postgis-connections/{connection_id}",
    response_model=PostgresConnectionResponse,
    operation_id="soft_delete_postgis_connection",
)
async def soft_delete_postgis_connection(
    project_id: str,
    connection_id: str,
    session: UserContext = Depends(verify_session_required),
):
    """
    Soft delete a PostgreSQL connection from a project.
    Only the project owner or editors can delete connections.
    """
    user_id = session.get_user_id()

    async with get_async_db_connection() as conn:
        # Check if user has access to the project
        project = await conn.fetchrow(
            """
            SELECT owner_uuid, editor_uuids
            FROM user_mundiai_projects
            WHERE id = $1 AND soft_deleted_at IS NULL
            """,
            project_id,
        )

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

        # Check if the connection exists and belongs to this project
        connection = await conn.fetchrow(
            """
            SELECT id, soft_deleted_at
            FROM project_postgres_connections
            WHERE id = $1 AND project_id = $2
            """,
            connection_id,
            project_id,
        )

        if not connection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"PostgreSQL connection {connection_id} not found in project {project_id}.",
            )

        if connection["soft_deleted_at"] is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PostgreSQL connection is already deleted.",
            )

        # Soft delete the connection by setting the timestamp
        await conn.execute(
            """
            UPDATE project_postgres_connections
            SET soft_deleted_at = CURRENT_TIMESTAMP
            WHERE id = $1 AND project_id = $2
            """,
            connection_id,
            project_id,
        )

        return PostgresConnectionResponse(
            success=True, message="PostgreSQL connection deleted successfully"
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

    async with get_async_db_connection() as conn:
        # Check if user has access to the project
        project = await conn.fetchrow(
            """
            SELECT owner_uuid, editor_uuids, viewer_uuids
            FROM user_mundiai_projects
            WHERE id = $1 AND soft_deleted_at IS NULL
            """,
            project_id,
        )

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
        connection = await conn.fetchrow(
            """
            SELECT
                ppc.id,
                ppc.connection_name,
                pps.friendly_name,
                pps.summary_md,
                pps.generated_at
            FROM project_postgres_connections ppc
            LEFT JOIN project_postgres_summary pps ON ppc.id = pps.connection_id
            WHERE ppc.id = $1 AND ppc.project_id = $2 AND ppc.soft_deleted_at IS NULL
            ORDER BY pps.generated_at DESC
            LIMIT 1
            """,
            connection_id,
            project_id,
        )

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


@project_router.post(
    "/{project_id}/postgis-connections/{connection_id}/regenerate-documentation",
    response_model=PostgresConnectionResponse,
    operation_id="regenerate_database_documentation",
)
async def regenerate_database_documentation(
    project_id: str,
    connection_id: str,
    background_tasks: BackgroundTasks,
    session: UserContext = Depends(verify_session_required),
    database_documenter: DatabaseDocumenter = Depends(get_database_documenter),
    connection_manager: PostgresConnectionManager = Depends(
        get_postgres_connection_manager
    ),
):
    """
    Regenerate the database documentation for a specific PostgreSQL connection.
    Only the project owner or editors can regenerate documentation.
    """
    user_id = session.get_user_id()

    async with get_async_db_connection() as conn:
        # Check if user has access to the project
        project = await conn.fetchrow(
            """
            SELECT owner_uuid, editor_uuids
            FROM user_mundiai_projects
            WHERE id = $1 AND soft_deleted_at IS NULL
            """,
            project_id,
        )

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

        # Get the database connection
        connection = await conn.fetchrow(
            """
            SELECT id, connection_uri, connection_name
            FROM project_postgres_connections
            WHERE id = $1 AND project_id = $2 AND soft_deleted_at IS NULL
            """,
            connection_id,
            project_id,
        )

        if not connection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Database connection {connection_id} not found.",
            )

        # Start background task to regenerate database documentation
        background_tasks.add_task(
            database_documenter.generate_documentation,
            connection_id,
            connection["connection_uri"],
            connection["connection_name"] or "Database",
            connection_manager,
        )

        return PostgresConnectionResponse(
            success=True, message="Database documentation regeneration started"
        )


class SocialImageCacheBustedError(Exception):
    pass


@project_router.get("/{project_id}/social.webp", response_class=Response)
async def get_project_social_preview(
    request: Request,
    project_id: str,
    session: UserContext = Depends(verify_session_required),
    base_map_provider: BaseMapProvider = Depends(get_base_map_provider),
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
    async with get_async_db_connection() as conn:
        # Check if the project exists
        project_result = await conn.fetchrow(
            """
            SELECT id, owner_uuid
            FROM user_mundiai_projects
            WHERE id = $1 AND soft_deleted_at IS NULL
            """,
            project_id,
        )
        if not project_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
            )

        # Check if user owns the project
        if session.get_user_id() != str(project_result["owner_uuid"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete this project",
            )

        # Soft delete the project
        updated_project = await conn.fetchrow(
            """
            UPDATE user_mundiai_projects
            SET soft_deleted_at = CURRENT_TIMESTAMP
            WHERE id = $1
            RETURNING id
            """,
            project_id,
        )

        if not updated_project:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete project",
            )

        return {
            "message": "Project successfully deleted",
            "project_id": project_id,
        }


class DemoPostgisConfigResponse(BaseModel):
    available: bool
    description: str = ""


@project_router.get(
    "/config/demo-postgis-available", response_model=DemoPostgisConfigResponse
)
async def get_demo_postgis_config():
    demo_uri = os.environ.get("DEMO_POSTGIS_URI")
    demo_description = os.environ.get("DEMO_POSTGIS_DESCRIPTION", "")

    if not demo_uri:
        return DemoPostgisConfigResponse(available=False)

    return DemoPostgisConfigResponse(available=True, description=demo_description)
