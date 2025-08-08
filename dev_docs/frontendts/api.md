# Frontend API Documentation

This document provides a comprehensive overview of the API endpoints that the Mundi frontend application communicates with.

---

## Authentication

Authentication is handled by SuperTokens. The frontend uses the `supertokens-auth-react` library, which communicates with the backend's SuperTokens middleware. The specific API calls are managed by the library and are not detailed here.

---

## Projects

### `GET /api/projects/`

-   **Description:** Lists all projects associated with the authenticated user.
-   **Request:** None.
-   **Response:** A JSON object containing a list of `MapProject` objects.

### `GET /api/projects/{projectId}`

-   **Description:** Retrieves a single project by its ID.
-   **Request:** None.
-   **Response:** A `MapProject` object.

### `POST /api/projects/{projectId}`

-   **Description:** Updates a project's properties, such as its title or whether it's accessible via a link.
-   **Request Body:**
    ```json
    {
      "link_accessible": boolean,
      "title": "string"
    }
    ```
-   **Response:**
    ```json
    {
      "updated": boolean
    }
    ```

### `DELETE /api/projects/{projectId}`

-   **Description:** Soft deletes a project.
-   **Request:** None.
-   **Response:** A confirmation message.

---

## Maps

### `POST /api/maps/create`

-   **Description:** Creates a new map project.
-   **Request Body:**
    ```json
    {
      "title": "string",
      "description": "string"
    }
    ```
-   **Response:** A `MapResponse` object containing the new map's details.

### `GET /api/maps/{map_id}`

-   **Description:** Retrieves the data for a specific map, including its layers and changelog.
-   **Request:** None.
-   **Response:** A `MapData` object.

### `GET /api/maps/{map_id}/tree`

-   **Description:** Retrieves the version history (tree) for a map.
-   **Request:** None.
-   **Response:** A `MapTreeResponse` object.

### `GET /api/maps/{map_id}/style.json`

-   **Description:** Gets the MapLibre style JSON for a map.
-   **Request:** None.
-   **Response:** A MapLibre style JSON object.

---

## Layers

### `POST /api/maps/{map_id}/layers`

-   **Description:** Uploads a new layer to a map. The file should be sent as `multipart/form-data`.
-   **Request:** `FormData` containing the file.
-   **Response:** A `LayerUploadResponse` object with the new layer's details.

### `DELETE /api/maps/{map_id}/layer/{layer_id}`

-   **Description:** Removes a layer from a map.
-   **Request:** None.
-   **Response:** A confirmation message.

### `POST /api/layers/{layer_id}/style`

-   **Description:** Sets the MapLibre style for a layer.
-   **Request Body:**
    ```json
    {
      "maplibre_json_layers": [...],
      "map_id": "string"
    }
    ```
-   **Response:**
    ```json
    {
      "style_id": "string",
      "layer_id": "string"
    }
    ```

---

## Conversations and Messages

### `POST /api/conversations`

-   **Description:** Creates a new conversation within a project.
-   **Request Body:**
    ```json
    {
      "project_id": "string"
    }
    ```
-   **Response:** A `ConversationResponse` object.

### `GET /api/conversations?project_id={projectId}`

-   **Description:** Lists all conversations for a user in a specific project.
-   **Request:** None.
-   **Response:** An array of `ConversationResponse` objects.

### `GET /api/conversations/{conversation_id}/messages`

-   **Description:** Retrieves all messages in a conversation.
-   **Request:** None.
-   **Response:** An array of `SanitizedMessage` objects.

### `POST /api/conversations/{conversation_id}/maps/{map_id}/send`

-   **Description:** Sends a message from the user to the chat. This triggers the backend AI to process the message and respond.
-   **Request Body:**
    ```json
    {
      "message": { ... },
      "selected_feature": { ... }
    }
    ```
-   **Response:** A `MessageSendResponse` object.

---

## Real-time Communication

### `GET /api/maps/{map_id}/room`

-   **Description:** Gets or creates a DriftDB room ID for a map to enable real-time collaboration features.
-   **Request:** None.
-   **Response:**
    ```json
    {
      "room_id": "string"
    }
    ```

### `WS /api/ws/{conversation_id}/messages/updates`

-   **Description:** A WebSocket endpoint for receiving real-time updates for a conversation. This includes new messages from the AI and ephemeral actions like progress indicators.
-   **Protocol:** WebSocket.
-   **Messages:** The client receives JSON messages representing new messages or actions.

---

## PostGIS Connections

### `POST /api/projects/{project_id}/postgis-connections`

-   **Description:** Adds a new PostGIS connection to a project.
-   **Request Body:**
    ```json
    {
      "connection_uri": "string",
      "connection_name": "string"
    }
    ```
-   **Response:**
    ```json
    {
      "message": "string",
      "connection_id": "string"
    }
    ```

### `DELETE /api/projects/{project_id}/postgis-connections/{connection_id}`

-   **Description:** Soft deletes a PostGIS connection.
-   **Request:** None.
-   **Response:** A confirmation message.
