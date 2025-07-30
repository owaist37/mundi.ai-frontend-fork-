# Copyright (C) 2025 Bunting Labs, Inc.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from abc import ABC, abstractmethod
from typing import List, Dict, Any
from pydantic import BaseModel


class SelectedFeature(BaseModel):
    layer_id: str
    attributes: Dict[str, Any]


class MapStateProvider(ABC):
    @abstractmethod
    async def get_system_messages(
        self,
        messages: List[Dict[str, Any]],
        current_map_description: str,
        selected_feature: SelectedFeature | None,
    ) -> List[Dict[str, Any]]:
        pass


class DefaultMapStateProvider(MapStateProvider):
    async def get_system_messages(
        self,
        messages: List[Dict[str, Any]],
        current_map_description: str,
        selected_feature: SelectedFeature | None,
    ) -> List[Dict[str, Any]]:
        tagged_description = f"<MapState>\n{current_map_description}\n</MapState>"
        if selected_feature:
            tagged_description += f"\n<SelectedFeature>\n{selected_feature.model_dump_json()}\n</SelectedFeature>"
        else:
            tagged_description += "\n<NoSelectedFeature />"

        return [{"role": "system", "content": tagged_description}]


def get_map_state_provider() -> MapStateProvider:
    return DefaultMapStateProvider()
