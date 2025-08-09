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
import base64
import json
import time
import uuid
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


app = FastAPI(
    title="Mundi.ai Frontend",
    description="Frontend-only application serving React SPA",
    version="0.0.1",
    # Don't show OpenAPI spec, docs, redoc
    openapi_url=None,
)


# Mount static assets for the React application
app.mount("/assets", StaticFiles(directory="frontendts/dist/assets"), name="spa-assets")


@app.post("/supertokens/session/refresh")
async def mock_session_refresh(request: Request):
    """Mock SuperTokens session refresh for basic auth compatibility"""
    # Simple mock for self-hosted environments without full auth
    if os.environ.get("MUNDI_AUTH_MODE", "edit") == "edit":
        # Create fake refresh response
        expiry = int(time.time() * 1000) + 3600 * 1000  # 1 hour
        front_token = base64.b64encode(
            json.dumps({"uid": "demo", "ate": expiry, "up": {}}).encode()
        ).decode()

        id_refresh = str(uuid.uuid4())
        anti_csrf = str(uuid.uuid4())
        access_tok = f"dummyAccess.{uuid.uuid4()}"
        refresh_tok = f"dummyRefresh.{uuid.uuid4()}"

        response = JSONResponse(status_code=200, content={})

        # Headers
        response.headers["front-token"] = front_token
        response.headers["id-refresh-token"] = id_refresh
        response.headers["anti-csrf"] = anti_csrf
        response.headers["access-control-expose-headers"] = (
            "front-token, id-refresh-token, anti-csrf"
        )
        response.headers["access-control-allow-credentials"] = "true"

        # Cookies
        response.set_cookie("sAccessToken", access_tok, httponly=True)
        response.set_cookie("sRefreshToken", refresh_tok, httponly=True)
        response.set_cookie("sIdRefreshToken", id_refresh, httponly=True)

        return response
    
    # Return 401 for view-only mode or other auth modes
    return JSONResponse(status_code=401, content={"detail": "Session refresh not available"})


@app.exception_handler(StarletteHTTPException)
async def spa_server(request: Request, exc: StarletteHTTPException):
    """SPA fallback handler - serve index.html for all non-API routes"""
    # Don't handle API 404s - let them bubble up as real 404s
    if (
        request.url.path.startswith("/api/")
        or request.url.path.startswith("/supertokens/")
    ):
        # Return standard 404 response for API routes
        return JSONResponse(
            status_code=exc.status_code, content={"detail": str(exc.detail)}
        )

    # For all other routes, return the SPA's index.html
    return FileResponse("frontendts/dist/index.html")