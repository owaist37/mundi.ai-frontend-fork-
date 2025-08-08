# Frontend Components

This document provides an overview of the key React components used in the Mundi.ai frontend.

---

### `AddRemoteDataSource.tsx`

**Purpose**: This component provides a dialog for adding a remote data source (e.g., a GeoJSON or PMTiles file from a URL) to a map.

**Props**:
-   `isOpen`: `boolean` - Controls whether the dialog is open or closed.
-   `onClose`: `() => void` - A callback function to close the dialog.
-   `projectId`: `string` - The ID of the project to which the data source will be added.
-   `onSuccess`: `() => void` - A callback function that is called when the data source is successfully added.

**Usage**:
This component is used within the `LayerList` component to allow users to add new layers from remote URLs.

---

### `AttributeTable.tsx`

**Purpose**: This component displays the attribute data of a map layer in a table format. It also allows users to query the data using natural language.

**Props**:
-   `layer`: `MapLayer` - The layer whose attributes are to be displayed.
-   `isOpen`: `boolean` - Controls whether the attribute table is visible.
-   `onClose`: `() => void` - A callback function to close the attribute table.

**Usage**:
The attribute table is shown when a user chooses to view the attributes of a layer from the `LayerList`.

---

### `DatabaseDetailsDialog.tsx`

**Purpose**: This component displays the documentation for a connected PostGIS database, including its schema and tables. It also allows users to regenerate the documentation or delete the database connection.

**Props**:
-   `isOpen`: `boolean` - Controls whether the dialog is open.
-   `onClose`: `() => void` - A callback to close the dialog.
-   `databaseName`: `string` - The name of the database.
-   `connectionId`: `string` - The ID of the database connection.
-   `projectId`: `string` - The ID of the project.
-   `onDelete`: `() => void` - A callback that is called when the connection is deleted.

**Usage**:
This dialog is displayed when a user clicks on a database connection in the `LayerList`.

---

### `EditableTitle.tsx`

**Purpose**: This component provides an input field for editing the title of a project. It automatically saves the changes after a short delay.

**Props**:
-   `projectId`: `string` - The ID of the project being edited.
-   `title`: `string` - The current title of the project.
-   `placeholder`: `string` - The placeholder text for the input field.
-   `className`: `string` - Additional CSS classes for styling.

**Usage**:
This component is used in the `LayerList` to display and edit the map title.

---

### `LayerList.tsx`

**Purpose**: This is a major component that displays the list of layers in the current map. It provides functionality for managing layers, adding new data sources, and interacting with the map.

**Props**:
-   `project`: `MapProject` - The current map project.
-   `currentMapData`: `MapData` - The data for the current map version.
-   `mapRef`: `React.RefObject<MLMap | null>` - A reference to the MapLibre map instance.
-   `openDropzone`: `() => void` - A function to open the file dropzone for uploading layers.
-   ...and many more for handling state and interactions.

**Usage**:
This component is the main sidebar in the map view, providing a central place for layer management and map interaction.

---

### `LayerListItem.tsx`

**Purpose**: This component represents a single layer in the `LayerList`. It displays the layer's name, status, and provides a dropdown menu for actions like zooming to the layer, deleting it, or viewing its attributes.

**Props**:
-   `name`: `string` - The name of the layer.
-   `status`: `'added' | 'removed' | 'edited' | 'existing'` - The status of the layer, used for styling.
-   `isActive`: `boolean` - Indicates if there is an active process on the layer.
-   `layerId`: `string` - The ID of the layer.
-   `dropdownActions`: `object` - An object defining the actions available in the dropdown menu.
-   ...and other props for styling and display.

**Usage**:
This component is used within `LayerList` to render each layer in the list.

---

### `MapLibreMap.tsx`

**Purpose**: This is the core component that renders the interactive map using MapLibre GL. It manages the map state, layers, controls, and user interactions.

**Props**:
-   `mapId`: `string` - The ID of the map to be displayed.
-   `project`: `MapProject` - The current map project.
-   `mapData`: `MapData | null` - The data for the current map version.
-   `mapTree`: `MapTreeResponse | null` - The version history of the map.
-   ...and many more for managing state and interactions.

**Usage**:
This component is the main view of the application, displaying the map and all its related UI elements.

---

### `MapsList.tsx`

**Purpose**: This component displays a paginated list of all the user's map projects. It allows users to create new maps and delete existing ones.

**Props**:
-   `hideNewButton`: `boolean` - An optional prop to hide the "New Map" button.

**Usage**:
This component is used on the main dashboard to list all available maps.

---

### `MermaidComponent.tsx`

**Purpose**: A simple component to render Mermaid diagrams from a string.

**Props**:
-   `chart`: `string` - The Mermaid diagram definition as a string.

**Usage**:
This component is used in `DatabaseDetailsDialog.tsx` to render the database schema diagram.

---

### `ProjectView.tsx`

**Purpose**: This component is the main container for the map view. It fetches all the necessary data for a project and its maps, manages WebSocket connections for real-time updates, and handles file uploads.

**Props**:
-   This component does not receive props directly, but it uses `useParams` to get the `projectId` and `versionId` from the URL.

**Usage**:
This component is the entry point for viewing a specific map project.

---

### `VersionVisualization.tsx`

**Purpose**: This component displays the version history of a map as a timeline. It shows the different map versions, the actions that created them, and the chat messages associated with each version.

**Props**:
-   `mapTree`: `MapTreeResponse | null` - The version history of the map.
-   `conversationId`: `number | null` - The ID of the current conversation.
-   `currentMapId`: `string | null` - The ID of the currently displayed map.
-   `conversations`: `Conversation[]` - The list of all conversations for the project.
-   `setConversationId`: `(id: number | null) => void` - A function to change the active conversation.
-   `activeActions`: `EphemeralAction[]` - A list of active, ongoing actions.

**Usage**:
This component is displayed as a sidebar next to the map, providing context and history for the project.

---

### `app-sidebar.tsx`

**Purpose**: This component renders the main application sidebar, providing navigation to the home page, recent projects, and account-related pages.

**Props**:
-   `projects`: `ProjectState` - The state of the projects, used to display recent projects.

**Usage**:
This sidebar is displayed on the main dashboard and other non-map pages.
