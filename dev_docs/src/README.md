# `src` Directory Overview

This directory contains the complete backend for the Mundi.ai application, a web-based Geographic Information System (GIS). The backend is built using Python and the [FastAPI](https://fastapi.tiangolo.com/) web framework, providing a robust API for all frontend operations.

## Key Components

The `src` directory is organized into several key subdirectories, each with a specific responsibility:

-   **`database/`**: This directory manages all database interactions. It contains SQLAlchemy models in `models.py` that define the database schema, along with connection and migration logic.

-   **`dependencies/`**: This section holds FastAPI dependencies that inject business logic into the application. It includes functionalities like user authentication, session management, and access to various geospatial and database services.

-   **`geoprocessing/`**: This directory contains tools and scripts for processing geospatial data. It handles tasks such as data format conversion, projection, and other complex GIS operations.

-   **`routes/`**: All API endpoints are defined in this directory. Each file corresponds to a specific feature set (e.g., `project_routes.py`, `layer_router.py`), making the API modular and easy to maintain.

-   **`symbology/`**: This component is responsible for managing the visual styling of map layers. It includes logic for applying and verifying MapLibre-compatible styles.

-   **`renderer/`**: The `renderer/` directory contains server-side JavaScript code for rendering maps into static images (e.g., PNGs) using MapLibre GL.

-   **`wsgi.py`**: This is the main entry point for the FastAPI application, where all the components and routes are brought together.

## Overall Architecture

The backend is designed to be a modular and scalable system. It leverages FastAPI's dependency injection to manage complex dependencies and to separate business logic from the API layer. The application is built to handle a variety of geospatial data formats and to provide a flexible and powerful API for the Mundi.ai frontend.
