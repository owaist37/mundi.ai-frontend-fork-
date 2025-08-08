# Backend Architecture

This document provides a detailed explanation of the backend architecture for the Mundi application, located in the `src` directory. The backend is built with **Python**, using the **FastAPI** framework for the web server and **SQLAlchemy** for the Object-Relational Mapper (ORM).

## Core Technologies

-   **FastAPI**: A modern, high-performance web framework for building APIs with Python.
-   **SQLAlchemy**: The database toolkit for Python, used to define the database schema and interact with the PostgreSQL database.
-   **Alembic**: A database migration tool used with SQLAlchemy to manage schema changes.
-   **PostgreSQL with PostGIS**: The primary database, with the PostGIS extension for storing and querying geospatial data.

## Directory Structure

The `src` directory is organized into modules with specific responsibilities:

-   **`wsgi.py`**: The main entry point for the FastAPI application. It initializes the app, includes the various API routers, configures middleware, and sets up the lifespan events (like running database migrations on startup).
-   **`database/`**: Contains all database-related code.
    -   `models.py`: Defines the application's data structures using SQLAlchemy declarative models (e.g., `MundiProject`, `MundiMap`, `MapLayer`).
    -   `connection.py`: Manages the database session and connection pool.
    -   `migrate.py`: Contains the logic to run Alembic migrations.
-   **`routes/`**: Contains the API endpoint definitions. Each file (e.g., `project_routes.py`, `layer_router.py`) defines a `fastapi.APIRouter` for a specific part of the API, which are then included in the main `app` in `wsgi.py`.
-   **`dependencies/`**: A key part of the architecture, this directory uses FastAPI's dependency injection system to provide services and business logic to the API routes. For example, `auth.py` provides user authentication, and `db_pool.py` provides database sessions.
-   **`geoprocessing/`**: Handles heavy-duty geospatial processing tasks, such as converting data formats or reprojecting layers.
-   **`symbology/`**: Manages the visual styling of map layers, including logic to create and validate MapLibre-compatible styles.
-   **`renderer/`**: Contains server-side JavaScript code that uses MapLibre GL to render maps into static PNG images.

## Data and Versioning Model

The application's data model is designed around a non-destructive, Git-like versioning system for maps.

-   **`MundiProject`**: The top-level container. A project has a title, owner, and a list of associated maps.
-   **`MundiMap`**: Represents a specific version of a map. Each map has a list of layers and their styles. Crucially, a `MundiMap` can have a `parent_map_id`, creating a tree-like history of changes. Every edit (like adding a layer or changing a style) results in the creation of a new `MundiMap` instance that points to its parent.
-   **`MapLayer`**: Represents a single geospatial dataset (e.g., a file upload or a PostGIS query).
-   **`LayerStyle`**: Represents the MapLibre styling rules for a `MapLayer`.
-   **`MapLayerStyle`**: An association table that links a specific `MundiMap`, `MapLayer`, and `LayerStyle`, effectively defining which style is used for a given layer on a particular map version.

This structure allows for a complete history of the map to be preserved, enabling features like viewing past versions and understanding the evolution of the map.

## Request Lifecycle and Dependency Injection

A typical API request flows through the system as follows:

1.  The request hits one of the endpoints defined in a router in the `src/routes/` directory.
2.  FastAPI's dependency injection system resolves the dependencies for that endpoint. For example, it might inject an authenticated user object from `dependencies/auth.py` and a database session from `dependencies/db_pool.py`.
3.  The route handler function executes its business logic, using the injected dependencies to interact with the database or other services.
4.  The handler returns a response, which FastAPI serializes to JSON and sends back to the client.

This architecture promotes a clean separation of concerns, keeping the API routing logic separate from the business logic and database interactions.

## Serving the Frontend

The backend also serves the compiled frontend Single-Page Application (SPA). The `wsgi.py` file configures a `StaticFiles` mount for the frontend assets and includes an exception handler that serves the `index.html` file for any non-API routes. This allows the frontend and backend to be served from the same domain in a production environment.
