# Frontend Components

This document provides an overview of the main application-specific components in the `frontendts/src/components` directory.

---

### `ProjectView`

**Purpose:** This is the main component for viewing and interacting with a map project. It serves as the central hub for most of the application's functionality.

**Key Responsibilities:**

-   Fetches and manages all data related to a project, including the map, layers, conversations, and version history, using `react-query`.
-   Handles file uploads via drag-and-drop for adding new layers.
-   Manages WebSocket connections for real-time updates from the backend.
-   Integrates with DriftDB for real-time collaborative features.
-   Renders the `MapLibreMap` component and passes down the necessary data and callbacks.

**Usage:** Rendered by `App.tsx` when the user navigates to a project URL (`/project/:projectId/:versionIdParam?`).

---

### `MapLibreMap`

**Purpose:** This component is responsible for rendering the interactive map using MapLibre GL.

**Props:**

-   `mapId`: The ID of the map to render.
-   `project`: The project data object.
-   `mapData`: The map data, including layers and style information.
-   `mapTree`: The version history tree for the map.
-   `conversationId`: The ID of the current conversation.
-   `conversations`: A list of all conversations in the project.
-   `setConversationId`: A callback to set the active conversation.
-   `openDropzone`: A function to programmatically open the file upload dropzone.
-   ...and various other props for managing state and interactivity.

**Usage:** Rendered within `ProjectView` to display the map.

---

### `AppSidebar`

**Purpose:** The main sidebar for the application, providing navigation and access to projects and maps.

**Props:**

-   `projects`: A `ProjectState` object containing the list of user's projects.

**Usage:** Rendered in `App.tsx` to provide the main navigation structure.

---

### `MapsList`

**Purpose:** Displays a list of all maps available to the user.

**Usage:** Rendered as the default view for authenticated users at the root URL (`/`).

---

### `LayerList`

**Purpose:** Renders a list of layers for the current map, allowing users to toggle their visibility.

**Props:**

-   `layers`: An array of layer objects.
-   `hiddenLayerIDs`: An array of IDs for layers that are currently hidden.
-   `toggleLayerVisibility`: A callback to toggle the visibility of a layer.

**Usage:** Typically displayed within the map view to provide layer control.

---

### `LayerListItem`

**Purpose:** Represents a single item in the `LayerList`.

**Props:**

-   `layer`: The layer object to display.
-   `isHidden`: A boolean indicating whether the layer is currently hidden.
-   `toggleLayerVisibility`: A callback to toggle the layer's visibility.

**Usage:** Rendered by `LayerList` for each layer in the map.

---

### `AddRemoteDataSource`

**Purpose:** A component that allows users to add a new remote data source, such as a PostGIS connection.

**Usage:** Used in the project view to allow users to connect to external databases.

---

### `AttributeTable`

**Purpose:** Displays the attribute data for a vector layer in a table format.

**Usage:** Can be used to inspect the data of a selected layer.

---

### `EditableTitle`

**Purpose:** A simple component that displays a title and allows it to be edited when clicked.

**Usage:** Used for renaming projects and maps.

---

### `VersionVisualization`

**Purpose:** Renders a visual representation of the map's version history (the "map tree").

**Props:**

-   `mapTree`: The map tree data structure.

**Usage:** Displayed in the project view to show the evolution of the map.
