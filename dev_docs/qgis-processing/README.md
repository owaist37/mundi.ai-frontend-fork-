# `qgis-processing` Directory Overview

This directory contains a standalone FastAPI service for running QGIS processing algorithms. It allows you to execute any QGIS processing algorithm in a separate, containerized environment.

## Key Components

-   **`Dockerfile`**: Defines the Docker image for the service, including the installation of QGIS and other dependencies.
-   **`server.py`**: The FastAPI application that exposes the QGIS processing functionality through a web API.

## API

The service provides the following endpoints:

### `POST /run_qgis_process`

This endpoint runs a specified QGIS processing algorithm.

**Request Body:**

-   `algorithm_id` (string, required): The ID of the QGIS algorithm to run (e.g., `native:buffer`).
-   `qgis_inputs` (object, required): A dictionary of input parameters for the algorithm.
-   `input_urls` (object, optional): A dictionary where keys are parameter names and values are URLs to download input files from.
-   `output_presigned_put_urls` (object, optional): A dictionary where keys are parameter names and values are pre-signed URLs to upload output files to.

**Response:**

A JSON object containing the results of the QGIS process, including any output files and execution metadata.

### `GET /health`

A standard health check endpoint that returns `{"status": "healthy"}` if the service is running.

## How to Use

1.  **Build the Docker image:**

    ```bash
    docker build -t qgis-processing-service qgis-processing/
    ```

2.  **Run the Docker container:**

    ```bash
    docker run -p 8000:8000 qgis-processing-service
    ```

3.  **Send requests to the service:**

    You can now send requests to `http://localhost:8000/run_qgis_process` with the appropriate request body to execute QGIS algorithms.
