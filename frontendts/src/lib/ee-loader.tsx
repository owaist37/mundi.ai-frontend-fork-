// Copyright (C) 2025 Bunting Labs, Inc.

// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Affero General Public License for more details.

// You should have received a copy of the GNU Affero General Public License
// along with this program.  If not, see <http://www.gnu.org/licenses/>.

import React from 'react';

// we embed the frontend features for multi-tenancy in our frontend, and this function
// lets us load these features dynamically from the open source frontend, while keeping
// the build small for open source mundi
export const loadEEComponent = <T extends React.ComponentType<any>>(componentName: string): React.LazyExoticComponent<T> => {
  if (import.meta.env.VITE_EE_COMPONENTS_IMPORT_AT_BUILD === 'yes') {
    return React.lazy(() => import(`@ee/${componentName}.tsx`));
  }

  return React.lazy(async () => {
    try {
      const eeModule = await import(`@ee/${componentName}.tsx`);
      return { default: eeModule.default };
    } catch {
      return { default: (() => null) as unknown as T };
    }
  });
};

export const ScheduleCallButton = loadEEComponent<React.ComponentType>('ScheduleCallButton');
export const ShareEmbedModal =
  loadEEComponent<
    React.ComponentType<{
      isOpen: boolean;
      onClose: () => void;
      projectId?: string;
    }>
  >('ShareEmbedModal');
