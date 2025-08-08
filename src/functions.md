# Frontend Utility Functions

This document provides an overview of the key utility functions and custom hooks used in the Mundi.ai frontend, primarily from the `frontendts/src/lib/` directory.

---

### `cn(...inputs)`

**Source**: `utils.ts`

**Purpose**: This function is a utility for conditionally joining CSS class names together. It's a combination of `clsx` and `tailwind-merge`, which makes it easy to build dynamic and responsive class strings for Tailwind CSS.

**Parameters**:
-   `...inputs`: `ClassValue[]` - A variable number of arguments that can be strings, arrays, or objects representing CSS classes.

**Returns**:
-   `string` - A merged and optimized string of CSS class names.

**Usage**:
```typescript
import { cn } from '@/lib/utils';

const MyComponent = ({ isActive, className }) => {
  return (
    <div className={cn('base-class', { 'active-class': isActive }, className)}>
      ...
    </div>
  );
};
```

---

### `formatRelativeTime(isoString)`

**Source**: `utils.ts`

**Purpose**: This function takes an ISO date string and returns a human-readable relative time string (e.g., "5 minutes ago", "2 days ago").

**Parameters**:
-   `isoString`: `string | undefined` - The date in ISO format.

**Returns**:
-   `string` - The formatted relative time string.

**Usage**:
```typescript
import { formatRelativeTime } from '@/lib/utils';

const lastEdited = '2023-10-27T10:00:00Z';
const relativeTime = formatRelativeTime(lastEdited); // e.g., "2 days ago"
```

---

### `formatShortRelativeTime(isoString)`

**Source**: `utils.ts`

**Purpose**: Similar to `formatRelativeTime`, but returns a more compact relative time string (e.g., "5 min", "2 hr").

**Parameters**:
-   `isoString`: `string | undefined` - The date in ISO format.

**Returns**:
-   `string` - The formatted short relative time string.

**Usage**:
```typescript
import { formatShortRelativeTime } from '@/lib/utils';

const lastUpdated = '2023-10-27T12:00:00Z';
const shortTime = formatShortRelativeTime(lastUpdated); // e.g., "2 hr"
```

---

### `usePersistedState(baseKey, deps, initial, storage)`

**Source**: `usePersistedState.tsx`

**Purpose**: This is a custom React hook that provides a state variable that is persisted to the browser's storage (session storage by default). This allows the state to be preserved across page reloads.

**Parameters**:
-   `baseKey`: `string` - The base key for the storage item.
-   `deps`: `(string | number | boolean)[]` - An array of dependencies that are combined with the base key to create a unique storage key.
-   `initial`: `T` - The initial value of the state if nothing is found in storage.
-   `storage`: `Storage` - (Optional) The storage medium to use, defaults to `window.sessionStorage`.

**Returns**:
-   `[T, React.Dispatch<React.SetStateAction<T>>]` - A state variable and a function to update it, similar to `useState`.

**Usage**:
```typescript
import { usePersistedState } from '@/lib/usePersistedState';

const MyComponent = ({ conversationId }) => {
  const [lastMessage, setLastMessage] = usePersistedState(
    'lastMessage',
    [conversationId],
    ''
  );
  // ...
};
```
