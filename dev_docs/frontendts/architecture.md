# Frontend Architecture

This document provides a detailed explanation of the frontend architecture for the Mundi application.

## Folder Structure

The `frontendts/src` directory is organized to maintain a clean and scalable codebase:

-   **`main.tsx`**: The entry point of the application. It initializes essential services like PostHog for analytics and SuperTokens for authentication, and then renders the main `App` component.
-   **`App.tsx`**: The root component of the application. It sets up the main layout, including the router, authentication wrappers, and the main sidebar.
-   **`components/`**: This directory is divided into two main subdirectories:
    -   **`ui/`**: Contains generic, reusable UI components provided by Shadcn UI, such as buttons, dialogs, and forms.
    -   **`components/`**: Houses the application-specific components that implement the core features of Mundi, like `ProjectView`, `MapLibreMap`, and `LayerList`.
-   **`hooks/`**: Contains custom React hooks that encapsulate reusable logic, such as `use-mobile.ts` for detecting mobile devices.
-   **`lib/`**: A collection of utility modules, type definitions, and client-side library initializations.
    -   **`frontend-types.ts` & `types.tsx`**: Define the TypeScript interfaces and types for the data structures used throughout the application.
    -   **`supertokens.ts`**: Configures and initializes the SuperTokens client for authentication.
    -   **`posthog.ts`**: Initializes PostHog for product analytics.
    -   **`utils.ts`**: Contains miscellaneous utility functions.
-   **`pages/`**: Contains components that represent entire pages, such as the `PostGISDocumentation` page.

## Component Interaction and Data Flow

The application's data flow is primarily managed by `react-query`, which handles data fetching, caching, and synchronization with the backend.

1.  **Authentication**: The application is wrapped in `SuperTokensWrapper` to handle user authentication. Routes are protected using `SessionAuth`, which ensures that only authenticated users can access protected pages.

2.  **Project and Map Data**:
    -   When a user navigates to a project, the `ProjectView` component is rendered.
    -   `ProjectView` uses `react-query`'s `useQuery` hook to fetch project data from the `/api/projects/{projectId}` endpoint.
    -   It also fetches map data, conversations, and the map's version tree from their respective API endpoints.

3.  **Real-time Updates**:
    -   The `ProjectView` component establishes a WebSocket connection using `react-use-websocket` to receive real-time updates for the current conversation.
    -   For collaborative features like pointer positions, the application uses `DriftDBProvider` to connect to a DriftDB room associated with the map.

4.  **State Management**:
    -   **Server State**: `react-query` is the primary tool for managing server state. It handles fetching, caching, and updating data from the backend API.
    -   **Local State**: Local component state is managed using React's `useState` and `useReducer` hooks. For state that needs to be persisted across sessions, the custom `usePersistedState` hook is used.
    -   **URL State**: `react-router-dom` is used to manage the application's URL, with parameters like `projectId` and `versionId` used to determine what data to fetch and display.

## Rendering and Map Interaction

-   The `MapLibreMap` component is responsible for rendering the map using MapLibre GL. It receives map data and style information as props and handles user interactions with the map.
-   The map style is fetched from the `/api/maps/{map_id}/style.json` endpoint, which dynamically constructs the style JSON based on the map's layers and their symbology.
-   Layers are added to the map as sources, with vector data typically served as PMTiles and raster data as Cloud Optimized GeoTIFFs.

This architecture is designed to be modular and scalable, with a clear separation of concerns between components and a robust data flow managed by `react-query`.
