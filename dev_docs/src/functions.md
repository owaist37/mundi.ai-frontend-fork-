# Backend Functions

This document provides an overview of key utility functions used in the Mundi backend. These functions encapsulate common, reusable logic, from data processing to interacting with external services.

---

## ID Generation

### `generate_id(length=12, prefix="")`

**Source**: `src/utils.py`

**Purpose**: This function generates a unique, human-readable ID for maps, layers, and other database objects. It uses a specific character set that excludes ambiguous characters (like `0`, `O`, `I`, `l`) to improve readability and reduce user error.

**Parameters**:
-   `length`: `int` - The total desired length of the ID.
-   `prefix`: `str` - An optional single-character prefix (e.g., `M` for maps, `L` for layers) to be added to the beginning of the ID.

**Returns**:
-   `str` - A unique string ID.

**Usage**: This function is called whenever a new entity that requires a unique identifier is created in the database.

---

## File and Data Processing

### `process_zip_with_shapefile(zip_file_path)`

**Source**: `src/utils.py`

**Purpose**: This asynchronous function handles the processing of a user-uploaded `.zip` file that is expected to contain an ESRI Shapefile. It extracts the archive, locates the `.shp` file, and uses the `ogr2ogr` command-line tool to convert it into a GeoPackage (`.gpkg`) file, which is a more modern and standardized format for storage and processing.

**Parameters**:
-   `zip_file_path`: `str` - The local filesystem path to the `.zip` archive.

**Returns**:
-   `tuple[str, str]` - A tuple containing the path to the newly created `.gpkg` file and the path to the temporary directory where the extraction occurred.

**Raises**:
-   `ValueError`: If the archive contains no Shapefiles or more than one Shapefile.
-   `Exception`: If the `ogr2ogr` conversion process fails.

### `process_kmz_to_kml(kmz_file_path)`

**Source**: `src/utils.py`

**Purpose**: This function processes a `.kmz` file by unzipping it and locating the primary `.kml` file within. Since KMZ is a zipped version of KML, this function is the first step in handling KMZ uploads.

**Parameters**:
-   `kmz_file_path`: `str` - The local filesystem path to the `.kmz` file.

**Returns**:
-   `tuple[str, str]` - A tuple containing the path to the extracted `.kml` file and the path to the temporary directory.

**Raises**:
-   `ValueError`: If no `.kml` file is found within the archive.

---

## External Service Clients

### `get_s3_client()` and `get_async_s3_client()`

**Source**: `src/utils.py`

**Purpose**: These functions provide singleton clients for interacting with an S3-compatible object storage service. This is where all user-uploaded files and generated data artifacts are stored.

-   `get_s3_client()`: Returns a synchronous `boto3` client. It is cached using `@lru_cache` to ensure that only one client instance is created.
-   `get_async_s3_client()`: Returns an asynchronous `aioboto3` client, suitable for use in `async` functions. It maintains a separate client instance for each running `asyncio` event loop.

**Configuration**: These functions are configured via environment variables (e.g., `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`).

### `get_openai_client(request: Request)`

**Source**: `src/utils.py`

**Purpose**: This function acts as a FastAPI dependency that provides an `AsyncOpenAI` client. This client is used to make calls to an OpenAI-compatible API for all Large Language Model (LLM) related tasks, such as generating symbology or describing layers.

**Parameters**:
-   `request`: `Request` - The incoming FastAPI request object.

**Returns**:
-   `AsyncOpenAI` - An asynchronous client for the OpenAI API.
