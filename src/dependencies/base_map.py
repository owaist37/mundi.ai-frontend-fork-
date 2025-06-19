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
from typing import Dict, Any


class BaseMapProvider(ABC):
    """Abstract base class for base map providers."""

    @abstractmethod
    async def get_base_style(self) -> Dict[str, Any]:
        """Return the base MapLibre GL style JSON."""
        pass


class OpenStreetMapProvider(BaseMapProvider):
    """Default base map provider using OpenStreetMap tiles."""

    async def get_base_style(self) -> Dict[str, Any]:
        """Return a basic MapLibre GL style using OpenStreetMap tiles."""
        return {
            "version": 8,
            "name": "OpenStreetMap",
            "metadata": {
                "maplibre:logo": "https://maplibre.org/",
            },
            "glyphs": "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
            "sources": {
                "osm": {
                    "type": "raster",
                    "tiles": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
                    "tileSize": 256,
                    "attribution": "© OpenStreetMap contributors",
                    "maxzoom": 19,
                }
            },
            "layers": [
                {
                    "id": "osm",
                    "type": "raster",
                    "source": "osm",
                    "layout": {"visibility": "visible"},
                    "paint": {},
                }
            ],
            "center": [0, 0],
            "zoom": 2,
            "bearing": 0,
            "pitch": 0,
        }


# Default dependency - can be overridden in closed source
def get_base_map_provider() -> BaseMapProvider:
    """Default base map provider dependency."""
    return OpenStreetMapProvider()
