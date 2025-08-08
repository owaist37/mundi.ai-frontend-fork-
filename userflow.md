# Mundi User Flow

This document outlines the typical user workflow within the Mundi application, from creating a map to styling it with the help of the AI assistant, Kue. It also details the key frontend components involved in each step.

## 1. Creating a New Map

The user's journey begins on the main dashboard, where they can see a list of their existing map projects.

1.  **Action**: The user clicks the "New Map" button to start a new project.
2.  **System Response**: Mundi creates a new, empty map project and displays it as a card in the user's map list.
3.  **Action**: The user clicks the "Open" button on the new map card.
4.  **System Response**: The application navigates to the map view, loading a blank map canvas.

**Key Components**:
*   `MapsList.tsx`: Displays the list of the user's maps and includes the "New Map" button.
*   `ProjectView.tsx`: The main container for the map view, which is loaded when a user opens a map project.

## 2. Uploading Data

Once in the map view, the user can add their own geospatial data to the map.

1.  **Action**: The user drags and drops a data file (e.g., a `.gpkg`, `.zip` of a shapefile, etc.) onto the map canvas. Alternatively, they can use the "Add Data" button.
2.  **System Response**: Mundi uploads and processes the file. Once complete, the data is rendered on the map, and a new layer is added to the "Map Layers" panel. This new layer is highlighted to indicate it's an unsaved change.

**Key Components**:
*   `LayerList.tsx`: The sidebar component that displays the list of map layers and includes controls for adding new data.
*   `LayerListItem.tsx`: Represents a single layer within the `LayerList`.
*   `MapLibreMap.tsx`: The core map component that renders the data.

## 3. Inspecting and Querying Data

To better understand the data they've uploaded, the user can inspect its attributes and even query them using natural language.

1.  **Action**: The user right-clicks on a layer in the "Map Layers" panel and selects "View attributes".
2.  **System Response**: The attribute table opens, displaying the features of the layer in a tabular format.
3.  **Action**: The user types a natural language query into the search bar of the attribute table (e.g., "show me all features in California").
4.  **System Response**: Kue translates the natural language query into a SQL query, filters the attribute table, and highlights the corresponding features on the map.

**Key Components**:
*   `AttributeTable.tsx`: The component that displays the layer's attributes and provides the natural language querying interface.
*   `LayerListItem.tsx`: Provides the context menu to open the attribute table.

## 4. Styling the Map with AI

This is a core feature of Mundi, where the user can style their map by simply describing how they want it to look.

1.  **Action**: The user types a styling request into the Kue chat prompt at the bottom of the screen (e.g., "style the counties by population").
2.  **System Response**: Kue analyzes the data, identifies the relevant attributes (e.g., "population"), and applies an appropriate style to the map layer. The map updates automatically to reflect the new style.
3.  **Action**: The user can continue to send chat messages to refine the style (e.g., "use a blue color ramp").
4.  **System Response**: Kue updates the map style based on the new instructions.

**Key Components**:
*   `MapLibreMap.tsx`: The main map component where the styling changes are rendered.
*   The chat interface (part of the overall `ProjectView.tsx`) allows the user to communicate with Kue.

## 5. Saving Map Versions

Mundi uses a versioning system that allows users to save snapshots of their work, creating a history of their map.

1.  **Action**: The user clicks the "Save" button.
2.  **System Response**: A new version of the map is created and added to the version history list. This saves the current state of the map, including all data and styling.
3.  **Action**: The user can view the version history, click on previous versions to see them, and revert to a previous version if needed.

**Key Components**:
*   `VersionVisualization.tsx`: Displays the version history of the map, allowing the user to see the timeline of changes and navigate between different versions.
*   `ProjectView.tsx`: Manages the overall state of the project, including the current version being viewed.
