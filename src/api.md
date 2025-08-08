# Mundi.ai API Documentation

This document provides a detailed overview of the Mundi.ai backend API endpoints. The information here is sourced from the OpenAPI specification and is intended for developers working with the Mundi.ai platform.

---

## Maps

### Create a map project

**POST** `/api/maps/create`

Creates a new map project. This endpoint returns both a map ID (`id`) and a project ID (`project_id`). Projects can contain multiple map versions ("maps"), and each edit creates a new map version.

**Request Body**:
-   `title`: `string` (optional) - The display name for the new map.
-   `description`: `string` (optional) - A description of the map's purpose.

**Responses**:
-   `200 OK`: Returns a `MapResponse` object with the new map's details.
-   `422 Unprocessable Entity`: If the request body is invalid.

---

### Upload file as layer

**POST** `/api/maps/{original_map_id}/layers`

Uploads spatial data, processes it, and adds it as a layer to the specified map.

**Path Parameters**:
-   `original_map_id`: `string` (required) - The ID of the map to which the layer will be added.

**Request Body** (`multipart/form-data`):
-   `file`: `file` (required) - The spatial data file to upload. Supported formats include Shapefile (as .zip), GeoJSON, GeoPackage, FlatGeobuf, GeoTIFF, DEM, LAZ, and LAS.
-   `layer_name`: `string` (optional) - A name for the new layer.
-   `add_layer_to_map`: `boolean` (optional, default: `true`) - If `false`, the layer is processed and stored but not added to the map.

**Responses**:
-   `200 OK`: Returns a `LayerUploadResponse` object with details of the new layer.
-   `422 Unprocessable Entity`: If the request is invalid.

---

### Render a map as PNG

**GET** `/api/maps/{map_id}/render.png`

Renders a map as a static PNG image, including all layers and their symbology.

**Path Parameters**:
-   `map_id`: `string` (required) - The ID of the map to render.

**Query Parameters**:
-   `bbox`: `string` (optional) - The bounding box to render, in the format `xmin,ymin,xmax,ymax` (EPSG:4326).
-   `width`: `integer` (optional, default: 1024) - The width of the output image in pixels.
-   `height`: `integer` (optional, default: 600) - The height of the output image in pixels.
-   `bgcolor`: `string` (optional, default: `#ffffff`) - The background color of the image.

**Responses**:
-   `200 OK`: Returns the rendered PNG image.
-   `422 Unprocessable Entity`: If the parameters are invalid.

---

## Layers

### Set layer style

**POST** `/api/layers/{layer_id}/style`

Sets a layer's active style using a MapLibre JSON layer list.

**Path Parameters**:
-   `layer_id`: `string` (required) - The ID of the layer to style.

**Request Body**:
-   `maplibre_json_layers`: `array` (required) - An array of MapLibre layer objects.
-   `map_id`: `string` (required) - The ID of the map where the new style will be applied.

**Responses**:
-   `200 OK`: Returns a `SetStyleResponse` object with the created style ID.
-   `422 Unprocessable Entity`: If the request is invalid.

---

## Projects

### Delete a map project

**DELETE** `/api/projects/{project_id}`

Marks a project as deleted (uses a soft delete).

**Path Parameters**:
-   `project_id`: `string` (required) - The ID of the project to delete.

**Responses**:
-   `200 OK`: Confirms that the project has been marked as deleted.
-   `422 Unprocessable Entity`: If the project ID is invalid.
