# Frontend Functions and Hooks

This document provides an overview of the utility functions and custom hooks used in the `frontendts/src/lib` and `frontendts/src/hooks` directories.

---

## Hooks (`src/hooks`)

### `use-mobile.ts`

-   **`useMobile()`**: A custom hook that returns `true` if the user is on a mobile device (screen width less than 768px), and `false` otherwise. It uses the `useMediaQuery` hook from `usehooks-ts`.

---

## Library Functions (`src/lib`)

### `ee-loader.tsx`

-   **`loadEe()`**: A function that loads the Google Earth Engine API script. It returns a promise that resolves when the script is loaded.

### `posthog.ts`

-   **`initPostHog()`**: Initializes the PostHog analytics library with the provided API key and configuration. It also identifies the user to PostHog if a session exists.

### `supertokens.ts`

-   **`initSupertokens()`**: Initializes the SuperTokens authentication client with the necessary configuration, including the API domain, app name, and recipe list.

### `usePersistedState.tsx`

-   **`usePersistedState(key, compositeKey, defaultValue)`**: A custom hook that provides a state variable that persists in the browser's local storage.
    -   `key`: The primary key for the local storage entry.
    -   `compositeKey`: An array of strings that, when changed, will reset the state to its `defaultValue`.
    -   `defaultValue`: The initial value of the state if no value is found in local storage.

### `utils.ts`

This file contains various utility functions. Some of the key functions include:

-   **`cn(...inputs)`**: A utility function from the `clsx` and `tailwind-merge` libraries that merges multiple class names into a single string, resolving any Tailwind CSS class conflicts.
-   Other miscellaneous helper functions.

### `qgis.tsx` & `types.tsx` & `frontend-types.ts`

These files primarily contain type definitions and interfaces for the data structures used throughout the application. They don't export functions, but are critical for ensuring type safety.
