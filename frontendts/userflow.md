# Mundi.ai Frontend User Flows

This document provides a detailed breakdown of the key user workflows in the Mundi.ai frontend. It outlines the components involved and the API calls made at each step of the process.

## 1. Map Creation and Data Upload

This workflow covers the initial steps of creating a new map and adding data to it.

### a. Creating a New Map

**Goal**: The user wants to create a new, empty map project.

1.  **Entry Point**: The user starts on the main dashboard, which is rendered by the `MapsList` component.
2.  **User Action**: The user clicks the "New Map" button.
3.  **Component Interaction**:
    *   The `onClick` handler for the "New Map" button in `MapsList.tsx` calls the `handleCreateMap` function.
    *   This function triggers a mutation that sends a request to the backend.
4.  **API Call**:
    *   **Endpoint**: `POST /api/maps/create`
    *   **Component**: `MapsList.tsx`
    *   **Request Body**: `{ "title": "New Map", "description": "", "project": { "layers": [] } }`
    *   **Response**: A JSON object containing the new map's `id` and `project_id`.
5.  **State Update**:
    *   Upon a successful response, the `MapsList` component refetches the list of projects.
    *   The newly created map is now displayed on the dashboard.
6.  **Navigation**: The user clicks the "Open" button on the new map card, which is a `Link` that navigates them to `/project/{project.id}`.

### b. Uploading Data

**Goal**: The user wants to add a spatial data file to the map.

1.  **Entry Point**: The user is in the main map view, rendered by the `ProjectView` component.
2.  **User Action**: The user drags and drops a file (e.g., a `.zip` Shapefile or a `.gpkg` file) onto the map canvas.
3.  **Component Interaction**:
    *   The `ProjectView` component uses the `useDropzone` hook to handle the file drop.
    *   The `onDrop` callback is triggered, which initiates the upload process.
    *   The `uploadFile` mutation is called for each valid file.
4.  **API Call**:
    *   **Endpoint**: `POST /api/maps/{versionId}/layers`
    *   **Component**: `ProjectView.tsx`
    *   **Request Body**: A `FormData` object containing the file.
    *   **Response**: A JSON object with the details of the newly created layer, including a `dag_child_map_id` which represents the new map version.
5.  **State Update and UI Feedback**:
    *   While the file is uploading, the `LayerList` component displays a progress bar for the uploading file.
    *   After a successful upload, a success toast is displayed.
    *   The application then navigates the user to the new map version using the `dag_child_map_id` from the response (`/project/{projectId}/{dag_child_map_id}`).
    *   The new layer appears in the `LayerList`, highlighted in green to indicate it's a new addition.

## 2. Data Exploration and Styling with AI

This workflow describes how a user can inspect their data and use the AI assistant, Kue, to style the map.

### a. Querying Data in the Attribute Table

**Goal**: The user wants to inspect the attributes of a layer and filter it using natural language.

1.  **Entry Point**: The user is in the main map view (`ProjectView`).
2.  **User Action**: The user right-clicks a layer in the `LayerList` component and selects "View attributes".
3.  **Component Interaction**:
    *   This action calls `setSelectedLayer` and `setShowAttributeTable(true)` in the `LayerList` component.
    *   The `AttributeTable` component is rendered as a dialog.
    *   The user types a natural language query (e.g., "show me all data") into the input field in the `AttributeTable`.
4.  **API Call**:
    *   **Endpoint**: `POST /api/layer/{layer.id}/query`
    *   **Component**: `AttributeTable.tsx`
    *   **Request Body**: `{ "natural_language_query": "...", "max_n_rows": 100 }`
    *   **Response**: A JSON object containing the translated SQL query (`query`), the query duration (`duration_ms`), and the resulting data (`headers` and `result`).
5.  **State Update**:
    *   The `AttributeTable` component updates its state with the received data, displaying the SQL query and the filtered table of attributes.

### b. Styling the Map with AI

**Goal**: The user wants to change the visual style of a layer using a natural language command.

1.  **Entry Point**: The user is in the main map view (`ProjectView`).
2.  **User Action**: The user types a command into the main chat input at the bottom of the screen (e.g., "style this layer based on the 'county' attribute").
3.  **Component Interaction**:
    *   The chat input is part of the `MapLibreMap` component.
    *   Pressing "Enter" calls the `sendMessage` function.
4.  **API Call**:
    *   **Endpoint**: `POST /api/maps/conversations/{conversationId}/maps/{mapId}/send`
    *   **Component**: `MapLibreMap.tsx`
    *   **Request Body**: A JSON object containing the user's message, e.g., `{ "message": { "role": "user", "content": "..." } }`.
    *   **Response**: A `MessageSendResponse` object which includes the `conversation_id`. The actual map update is delivered via WebSocket.
5.  **Real-time Updates (WebSockets)**:
    *   The `ProjectView` component maintains a WebSocket connection.
    *   The backend sends ephemeral messages to the frontend to show the AI's progress (e.g., "Thinking...", "Analyzing data..."). These are displayed in the UI.
    *   Once the styling is complete, the backend sends a final message and triggers a refresh of the map's style data.
6.  **State Update**:
    *   The `MapLibreMap` component refetches the map style from `/api/maps/{mapId}/style.json`.
    *   The new style is applied to the map, and the visual representation of the layer changes.

## 3. Connecting to a PostGIS Database

This workflow explains how to connect Mundi.ai to an external PostGIS database and create layers from it.

### a. Connecting to the Database

**Goal**: The user wants to connect Mundi.ai to a new PostGIS database.

1.  **Entry Point**: The user is in the main map view (`ProjectView`).
2.  **User Action**: The user clicks the "Load PostGIS" button (database icon) in the footer of the `LayerList` component.
3.  **Component Interaction**:
    *   This action opens a dialog for entering PostGIS connection details. This dialog is part of the `LayerList` component.
    *   The user fills in the connection URI or the individual fields (host, port, etc.) and clicks "Add Connection".
4.  **API Call**:
    *   **Endpoint**: `POST /api/projects/{projectId}/postgis-connections`
    *   **Component**: `LayerList.tsx`
    *   **Request Body**: `{ "connection_uri": "..." }`
    *   **Response**: A confirmation message.
5.  **State Update and UI Feedback**:
    *   Upon success, a toast notification appears.
    *   The `LayerList` component refetches the project data.
    *   The new database connection appears in the "DATABASES" section of the `LayerList`.
    *   Initially, it shows a progress bar as the backend documents the database schema. The frontend polls for updates until documentation is complete.

### b. Viewing Database Documentation

**Goal**: The user wants to see the AI-generated documentation for their database.

1.  **Entry Point**: The user sees the completed database connection in the `LayerList`.
2.  **User Action**: The user clicks on the database name.
3.  **Component Interaction**:
    *   This action navigates the user to the `/postgis/{connectionId}` page.
    *   The `PostGISDocumentation` page is rendered.
4.  **API Call**:
    *   **Endpoint**: `GET /api/projects/{projectId}/postgis-connections/{connectionId}/documentation`
    *   **Component**: `DatabaseDetailsDialog.tsx` (Note: The docs are shown in a dedicated page, but the dialog component contains similar logic).
    *   **Response**: A JSON object containing the `documentation` as a Markdown string.
5.  **UI Display**:
    *   The `PostGISDocumentation` page renders the Markdown, including a Mermaid diagram of the database schema (rendered by the `MermaidComponent`).

### c. Creating a Layer from PostGIS

**Goal**: The user wants to create a new map layer from a table in their connected PostGIS database.

1.  **Entry Point**: The user is in the main map view (`ProjectView`).
2.  **User Action**: The user types a command into the main chat input, referencing the connected database (e.g., "add a layer for the wellbores from my postgis database").
3.  **Component Interaction and API Call**:
    *   This follows the same flow as styling the map with AI. The `MapLibreMap` component sends the message to the backend.
    *   **Endpoint**: `POST /api/maps/conversations/{conversationId}/maps/{mapId}/send`
4.  **Backend Process**:
    *   The AI assistant (Kue) understands the request, identifies the PostGIS data source, constructs a SQL query, and creates a new layer from the result.
5.  **Real-time and State Updates**:
    *   Similar to styling, the frontend receives WebSocket messages about the progress.
    *   Once complete, the map data is invalidated and refetched. The new layer, sourced directly from the PostGIS database, appears on the map and in the `LayerList`.

## 4. Map Versioning

This workflow outlines how Mundi.ai handles map versions, allowing users to track changes and maintain a history of their work. Mundi's versioning is designed to be non-destructive, similar to Git, where every significant action creates a new, immutable map state.

### a. How New Versions are Created

New map versions are not created by an explicit "Save" button. Instead, they are created automatically as a result of actions that modify the map's structure or content. These actions include:

*   Uploading a new layer.
*   Deleting a layer.
*   Applying a new style via the AI assistant.
*   Creating a new layer from a PostGIS query.

When one of these actions is performed, the backend creates a new map version (`dag_child_map_id`) and the frontend automatically navigates to this new version.

### b. Visualizing Versions

**Goal**: The user wants to understand the history of their map and see the changes between versions.

1.  **Entry Point**: The user is in the main map view (`ProjectView`).
2.  **Component Interaction**:
    *   The `VersionVisualization` component is displayed on the right side of the screen.
    *   It renders a timeline of all the map versions associated with the current conversation.
3.  **API Call (Data Source)**:
    *   The data for the timeline comes from the `mapTree` object, which is fetched from the backend.
    *   **Endpoint**: `GET /api/maps/{versionId}/tree?conversation_id={conversationId}`
    *   **Component**: `ProjectView.tsx`
    *   **Response**: A `MapTreeResponse` object containing a tree structure of all related map nodes and the messages associated with them.
4.  **UI Display**:
    *   The `VersionVisualization` component iterates through the `mapTree.tree` array.
    *   Each item in the array is a `MapNode`, representing a version of the map.
    *   For each node, it displays:
        *   Who made the change ("You" or "Kue").
        *   A description of the change (e.g., "Added layer: my_data").
        *   The chat messages that led to that version.
    *   The currently active map version is highlighted.
5.  **Navigating Versions**:
    *   While not explicitly implemented as a direct click-to-navigate feature in the timeline, the user can navigate between versions by using the browser's back and forward buttons, as each version has a unique URL (`/project/{projectId}/{versionId}`).
