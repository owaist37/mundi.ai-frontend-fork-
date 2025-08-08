# Backend Components

This document provides an overview of the main backend components that make up the Mundi application. These are the core Python classes and modules that encapsulate the application's business logic and data structures.

---

## Data Models (`src/database/models.py`)

The SQLAlchemy models are the central components that define the application's data structure and relationships.

-   **`MundiProject`**: The top-level container for a user's work. It holds metadata like the title and owner, and maintains a list of associated `MundiMap` versions.

-   **`MundiMap`**: Represents a single, immutable version of a map. It contains a list of layers and their corresponding styles for that specific version. It points to a `parent_map_id` to form a historical tree of changes.

-   **`MapLayer`**: Represents a geospatial dataset. This could be a user-uploaded file (stored in S3) or a query from a PostGIS database. It stores metadata about the layer, such as its type (vector, raster), geometry type, and bounds.

-   **`LayerStyle`**: Defines the visual styling for a `MapLayer`. It contains a MapLibre-compatible JSON object that describes how the layer should be rendered.

-   **`MapLayerStyle`**: A critical association model that links a `MundiMap`, a `MapLayer`, and a `LayerStyle`. This "through" model specifies exactly which style is active for a given layer on a particular map version.

-   **`ProjectPostgresConnection`**: Stores the connection details for an external PostGIS database that a user has linked to their project.

-   **`Conversation` & `MundiChatCompletionMessage`**: These models store the history of the chat interactions between the user and the AI assistant for a given project.

---

## Service Dependencies (`src/dependencies/`)

The `dependencies` directory contains modules that provide services to the API routes using FastAPI's dependency injection system. This is where much of the core business logic resides.

-   **`auth.py`**: Handles user authentication and authorization. It provides dependencies that can be injected into routes to ensure that a user is logged in and has permission to access or modify a resource.

-   **`db_pool.py`**: Manages the database connection pool and provides a dependency for injecting a SQLAlchemy `Session` object into API routes, allowing them to perform database operations.

-   **`dag.py`**: Contains logic related to the Directed Acyclic Graph (DAG) of map versions. It provides functions for traversing the map history and managing the version tree.

-   **`database_documenter.py`**: A service that connects to a user's external PostGIS database, inspects its schema, and generates a summary of its contents, often using an LLM.

-   **`layer_describer.py`**: A service that uses an LLM to generate a human-readable description of a `MapLayer`'s contents based on its metadata and attributes.

---

## Other Key Modules

-   **`geoprocessing/dispatch.py`**: The entry point for running geospatial processing tasks. When a user uploads a file, this module dispatches it to the correct processing function based on its file type (e.g., converting a Shapefile, reprojecting a GeoTIFF).

-   **`renderer/render.js`**: A server-side JavaScript file that uses Node.js and MapLibre GL Native to render a map to a static PNG image. This is used for generating thumbnails or exports.

-   **`symbology/llm.py`**: Contains the logic for using a Large Language Model (LLM) to automatically generate `LayerStyle` objects based on a user's natural language request (e.g., "style this layer by population").
