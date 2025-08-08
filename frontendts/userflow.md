# Mundi Frontend User Flow

This document details the typical user workflows in the Mundi application, outlining the sequence of user actions and the corresponding frontend components and backend API calls involved.

---

## 1. Authentication and Dashboard

This flow describes the initial user experience, from logging in to viewing the main dashboard.

| User Action | Components | API Calls | Description |
| :--- | :--- | :--- | :--- |
| **1. Signs up or logs in** | `SuperTokensWrapper`, `EmailPasswordPreBuiltUI` | Handled by SuperTokens library | The user provides their credentials. Upon successful authentication, they are directed to the main dashboard. |
| **2. Views dashboard** | `MapsList` | `GET /api/projects/` | The dashboard displays a list of all map projects associated with the user's account. |

---

## 2. Map Creation and Data Upload

This flow covers the creation of a new map and the two primary ways of adding data to it.

| User Action | Components | API Calls | Description |
| :--- | :--- | :--- | :--- |
| **1. Creates a new map** | `MapsList` | `POST /api/maps/create` | The user clicks a "Create Map" button, which creates a new project and an initial map version. The dashboard updates to show the new map. |
| **2. Opens the map** | `ProjectView` | `GET /api/projects/{projectId}`, `GET /api/maps/{map_id}`, `GET /api/maps/{map_id}/tree`, `WS /api/ws/{...}` | The user is taken to the main project view, which loads all necessary data for the map, including layers, version history, and real-time connections. |
| **3a. Uploads a file** | `ProjectView` | `POST /api/maps/{map_id}/layers` | The user drags and drops a spatial file (e.g., GeoJSON, Shapefile .zip) onto the map. The file is uploaded and added as a new layer. |
| **3b. Connects to PostGIS** | `AddRemoteDataSource` | `POST /api/projects/{project_id}/postgis-connections` | The user provides a PostGIS connection string. The backend connects to the database and begins to document its schema. |

---

## 3. AI-Powered Interaction and Analysis

This flow demonstrates how a user interacts with their data using the AI assistant, Kue.

| User Action | Components | API Calls | Description |
| :--- | :--- | :--- | :--- |
| **1. Views layer attributes** | `LayerListItem`, `AttributeTable` | (None) | The user right-clicks a vector layer and opens its attribute table to inspect the data. |
| **2. Queries attributes with natural language** | `AttributeTable` | `POST /api/layer/{layer_id}/query` | The user types a query like "show me all features where population > 10000". The AI translates this to SQL, and the table is filtered accordingly. |
| **3. Styles map with chat** | Chat input in `MapLibreMap` | `POST /api/conversations/{...}/maps/{...}/send` | The user asks the AI to style a layer (e.g., "style cities by population"). The AI processes the request, which may result in a `POST /api/layers/{layer_id}/style` call to apply the new style. |
| **4. Creates layer with chat**| Chat input in `MapLibreMap` | `POST /api/conversations/{...}/maps/{...}/send` | The user asks the AI to create a new layer from a PostGIS source (e.g., "add a layer of rivers from my database"). The AI uses the `new_layer_from_postgis` tool, creating a new layer from a SQL query. |

---

## 4. Versioning

Mundi's workflow is built around a non-destructive, Git-like versioning system.

| User Action | Components | API Calls | Description |
| :--- | :--- | :--- | :--- |
| **1. Makes an edit** | `ProjectView` | Varies (e.g., `POST /api/maps/{map_id}/layers`) | Any action that modifies the map state (adding a layer, changing a style) automatically creates a new, temporary map version in the backend. |
| **2. Views version history** | `VersionVisualization` | (Data from `GET /api/maps/{map_id}/tree`) | The user can see a visual representation of the map's history, showing how different versions branch off from one another. |
| **3. Clicks "Save"** | `ProjectView` | (Handled by backend DAG logic) | The "Save" action effectively makes the current temporary version a permanent, named version in the project's history, ensuring no work is lost. |
