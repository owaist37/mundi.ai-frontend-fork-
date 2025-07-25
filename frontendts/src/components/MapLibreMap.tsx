// Copyright Bunting Labs, Inc. 2025

import { useConnectionStatus, usePresence } from 'driftdb-react';
import legendSymbol, { type RenderElement } from 'legend-symbol-ts';

function renderTree(tree: RenderElement | null): JSX.Element | null {
  if (!tree) return null;
  return React.createElement(tree.element, tree.attributes, tree.children?.map(renderTree));
}

import { COORDINATE_SYSTEM } from '@deck.gl/core';
import { PointCloudLayer } from '@deck.gl/layers';
import { MapboxOverlay } from '@deck.gl/mapbox';
import { LASLoader } from '@loaders.gl/las';
import { Matrix4 } from '@math.gl/core';
import { Activity, Brain, Database, MessagesSquare, Send, X } from 'lucide-react';
import { type IControl, type MapGeoJSONFeature, type MapOptions, Map as MLMap, NavigationControl, ScaleControl } from 'maplibre-gl';
import type {
  ChatCompletionMessageParam,
  ChatCompletionMessageToolCall,
  ChatCompletionUserMessageParam,
} from 'openai/resources/chat/completions';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Download } from 'react-bootstrap-icons';
import ReactMarkdown from 'react-markdown';
import { useNavigate } from 'react-router-dom';
import useWebSocket from 'react-use-websocket';
import remarkGfm from 'remark-gfm';
import { toast } from 'sonner';
import Session from 'supertokens-auth-react/recipe/session';
import AttributeTable from '@/components/AttributeTable';
import LayerList from '@/components/LayerList';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Input } from '@/components/ui/input';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { EphemeralAction, MapData, MapLayer, MapProject, PointerPosition, PresenceData } from '../lib/types';

// Define the type for chat completion messages from the database
interface ChatCompletionMessageRow {
  id: number;
  map_id: string;
  sender_id: string;
  message_json: ChatCompletionMessageParam;
  created_at: string;
}

// Import styles in the parent component
const KUE_MESSAGE_STYLE = `
  text-sm
  [&_table]:w-full [&_table]:border-collapse [&_table]:text-left
  [&_thead]:border-b-1 [&_thead]:border-gray-600
  [&_thead_th]:font-semibold
  [&_tbody_tr]:border-b [&_tbody_tr]:border-gray-200 last:[&_tbody_tr]:border-b-0
  [&_td]:align-top
  [&_a]:text-blue-200 [&_a]:underline
`;

const SWAP_XY = new Matrix4().set(0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1);

// Custom Globe Control class
class GlobeControl implements IControl {
  private _container: HTMLDivElement | undefined;
  private _availableBasemaps: string[];
  private _currentBasemap: string;
  private _onBasemapChange: (basemap: string) => void;

  constructor(availableBasemaps: string[], currentBasemap: string, onBasemapChange: (basemap: string) => void) {
    this._availableBasemaps = availableBasemaps;
    this._currentBasemap = currentBasemap;
    this._onBasemapChange = onBasemapChange;
  }

  onAdd(_map: MLMap): HTMLElement {
    this._container = document.createElement('div');
    this._container.className = 'maplibregl-ctrl maplibregl-ctrl-group';

    const button = document.createElement('button');
    button.className = 'maplibregl-ctrl-globe';
    button.type = 'button';
    button.title = 'Toggle satellite basemap';
    button.setAttribute('aria-label', 'Toggle satellite basemap');

    // Create globe icon (SVG)
    button.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="#333">
        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.94-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
      </svg>
    `;
    button.style.border = 'none';
    button.style.background = 'transparent';
    button.style.cursor = 'pointer';
    button.style.padding = '5px';
    button.style.display = 'flex';
    button.style.alignItems = 'center';
    button.style.justifyContent = 'center';

    button.addEventListener('click', this._onClickGlobe.bind(this));

    this._container.appendChild(button);
    return this._container;
  }

  onRemove(): void {
    if (this._container && this._container.parentNode) {
      this._container.parentNode.removeChild(this._container);
    }
  }

  private _onClickGlobe(): void {
    if (!this._availableBasemaps.length) return;

    // Cycle to next basemap
    const currentIndex = this._availableBasemaps.indexOf(this._currentBasemap);
    const nextIndex = (currentIndex + 1) % this._availableBasemaps.length;
    const nextBasemap = this._availableBasemaps[nextIndex];

    this._currentBasemap = nextBasemap;
    this._onBasemapChange(nextBasemap);
  }

  updateBasemap(basemap: string): void {
    this._currentBasemap = basemap;
  }
}

// Custom Export PDF Control class
class ExportPDFControl implements IControl {
  private _container: HTMLDivElement | undefined;
  private _button: HTMLButtonElement | undefined;
  private _map: MLMap | undefined;
  private _mapId: string;

  constructor(mapId: string) {
    this._mapId = mapId;
  }

  onAdd(map: MLMap): HTMLElement {
    this._map = map;
    this._container = document.createElement('div');
    this._container.className = 'maplibregl-ctrl maplibregl-ctrl-group';

    const button = document.createElement('button');
    this._button = button;
    button.className = 'maplibregl-ctrl-export-pdf';
    button.type = 'button';
    button.title = 'Export map screenshot';
    button.setAttribute('aria-label', 'Export map screenshot');

    // Create camera icon (SVG)
    button.innerHTML = `
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#333" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-camera-icon lucide-camera"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/></svg>
    `;
    button.style.border = 'none';
    button.style.background = 'transparent';
    button.style.cursor = 'pointer';
    button.style.padding = '5px';
    button.style.display = 'flex';
    button.style.alignItems = 'center';
    button.style.justifyContent = 'center';

    button.addEventListener('click', this._onClickExportPDF.bind(this));

    this._container.appendChild(button);
    return this._container;
  }

  onRemove(): void {
    if (this._container && this._container.parentNode) {
      this._container.parentNode.removeChild(this._container);
    }
  }

  private async _onClickExportPDF(): Promise<void> {
    if (!this._map || !this._button) return;

    // Store original content
    const originalContent = this._button.innerHTML;

    // Replace with spinning loader
    this._button.innerHTML = `
      <svg class="animate-spin" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#333" stroke-width="2">
        <circle cx="12" cy="12" r="10" stroke-opacity="0.25"/>
        <path d="M12 2a10 10 0 0 1 10 10" stroke-opacity="1"/>
      </svg>
    `;
    this._button.disabled = true;

    try {
      // Get current map bounds
      const bounds = this._map.getBounds();
      const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

      // Get map container dimensions and double resolution
      const container = this._map.getContainer();
      const width = container.offsetWidth * 2;
      const height = container.offsetHeight * 2;

      // Call the render API endpoint to get PNG
      const response = await fetch(`/api/maps/${this._mapId}/render.png?bbox=${bbox}&width=${width}&height=${height}`);

      if (!response.ok) {
        throw new Error('Failed to render map');
      }

      // Get the PNG blob
      const blob = await response.blob();

      // For now, just download the PNG (PDF conversion can be added later)
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `map-${this._mapId}-${new Date().toISOString().split('T')[0]}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Error exporting to PDF:', error);
      alert('Failed to export map. Please try again.');
    } finally {
      // Restore original content
      this._button.innerHTML = originalContent;
      this._button.disabled = false;
    }
  }
}

interface ErrorEntry {
  id: string;
  message: string;
  timestamp: Date;
  shouldOverrideMessages: boolean;
}

// Add interface for tracking upload progress
interface UploadingFile {
  id: string;
  file: File;
  progress: number;
  status: 'uploading' | 'completed' | 'error';
  error?: string;
}

interface MapLibreMapProps {
  mapId: string;
  width?: string;
  height?: string;
  className?: string;
  project: MapProject;
  mapData?: MapData | null;
  openDropzone?: () => void;
  updateMapData: (mapId: string) => void;
  updateProjectData: (projectId: string) => void;
  uploadingFiles?: UploadingFile[];
  hiddenLayerIDs: string[];
  toggleLayerVisibility: (layerId: string) => void;
}

export default function MapLibreMap({
  mapId,
  width = '100%',
  height = '500px',
  className = '',
  project,
  mapData,
  openDropzone,
  updateMapData,
  updateProjectData,
  uploadingFiles,
  hiddenLayerIDs,
  toggleLayerVisibility,
}: MapLibreMapProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const globeControlRef = useRef<GlobeControl | null>(null);
  const exportPDFControlRef = useRef<ExportPDFControl | null>(null);
  const deckOverlayRef = useRef<MapboxOverlay | null>(null);
  const [errors, setErrors] = useState<ErrorEntry[]>([]);
  const [hasZoomed, setHasZoomed] = useState(false);
  const [layerSymbols, setLayerSymbols] = useState<{
    [layerId: string]: JSX.Element;
  }>({});
  const [zoomHistory, setZoomHistory] = useState<Array<{ bounds: [number, number, number, number] }>>([]);
  const [zoomHistoryIndex, setZoomHistoryIndex] = useState(-1);
  const processedBoundsActionIds = useRef<Set<string>>(new Set());
  const [currentBasemap, setCurrentBasemap] = useState<string>('');
  const [availableBasemaps, setAvailableBasemaps] = useState<string[]>([]);
  const [demoConfig, setDemoConfig] = useState<{
    available: boolean;
    description: string;
  }>({ available: false, description: '' });

  const pointCloudLayers = useMemo(() => {
    return mapData?.layers?.filter((layer) => layer.type === 'point_cloud') || [];
  }, [mapData?.layers]);

  const createPointCloudLayer = useCallback((pclayer: MapLayer) => {
    // some projection-foo to compensate for web mercator (gross!) and
    // latitude-longitude disagreements (SWAP_XY)
    const { lon, lat } = pclayer.metadata?.pointcloud_anchor as { lon: number; lat: number };
    if (!lon || !lat) {
      console.error('no anchor', pclayer);
      return;
    }
    const R = 6378137;
    const d2r = Math.PI / 180;
    const cosA = Math.cos(lat * d2r);

    const mPerDegLon = R * d2r * cosA;
    const mPerDegLat = R * d2r;
    const translate = new Matrix4().translate([-lon, -lat, 0]);
    const scale = new Matrix4().scale([mPerDegLon, mPerDegLat, 1]);
    const modelMatrix = scale.multiplyRight(translate).multiplyRight(SWAP_XY);

    const layer = new PointCloudLayer({
      id: `point-cloud-layer-${pclayer.id}`,
      data: `/api/layer/${pclayer.id}.laz`,
      loaders: [LASLoader],
      loadOptions: {
        las: {
          fp64: true,
        },
      },
      modelMatrix: modelMatrix,
      coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
      coordinateOrigin: [lon, lat, 0],
      getColor: (_d, dinfo) => {
        const mesh = (dinfo.data as any).loaderData;

        if (!mesh.maxs || !mesh.mins) {
          return [100, 100, 255, 255];
        }

        // TODO: improve this. its a fast percentile approximation
        // but life can always be better. pastures are greener
        const pointData = dinfo.data as any;
        const currentZ = pointData.attributes.POSITION.value[dinfo.index * 3 + 2];

        if (!mesh.percentileCache) {
          const numPoints = pointData.attributes.POSITION.value.length / 3;
          const sampleSize = Math.min(5000, numPoints);
          const zValues = [];

          for (let i = 0; i < sampleSize; i++) {
            const idx = Math.floor((i / sampleSize) * numPoints) * 3 + 2;
            zValues.push(pointData.attributes.POSITION.value[idx]);
          }

          zValues.sort((a, b) => a - b);
          mesh.percentileCache = {
            p5: zValues[Math.floor(sampleSize * 0.05)],
            p95: zValues[Math.floor(sampleSize * 0.95)],
          };
        }

        const { p5, p95 } = mesh.percentileCache;
        const range = p95 - p5;

        if (range === 0) {
          return [100, 100, 255, 255];
        }

        const clampedZ = Math.max(p5, Math.min(p95, currentZ));
        const normalizedZ = (clampedZ - p5) / range;

        // TODO: interpolate between two pretty colors
        const r = Math.round(normalizedZ * 255);
        const g = Math.round(normalizedZ * 255);
        const b = Math.round((1 - normalizedZ) * 255);
        return [r, g, b, 255];
      },
      pointSize: 1,
      onError: (error: any) => {
        console.error('Point cloud loading error: ' + error.message);
      },
    });
    return layer;
  }, []);

  // Helper function to add a new error
  const addError = useCallback((message: string, shouldOverrideMessages: boolean = false) => {
    setErrors((prevErrors) => {
      // if it already exists, bail out
      if (prevErrors.some((err) => err.message === message)) {
        return prevErrors;
      }

      // otherwise create & push
      const newError: ErrorEntry = {
        id: Date.now().toString() + Math.random().toString(36).substr(2, 9),
        message,
        timestamp: new Date(),
        shouldOverrideMessages,
      };

      console.error(message);
      if (!shouldOverrideMessages) toast.error(message);

      // schedule the auto-dismiss
      setTimeout(() => {
        setErrors((current) => current.filter((e) => e.id !== newError.id));
      }, 30000);

      return [...prevErrors, newError];
    });
  }, []);

  // Helper function to dismiss a specific error
  const dismissError = (errorId: string) => {
    setErrors((prev) => prev.filter((error) => error.id !== errorId));
  };
  const [loading, setLoading] = useState(true);
  const [pointerPosition, setPointerPosition] = useState<PointerPosition | null>(null);
  const otherClientPositions = usePresence<PointerPosition | null>('cursors', pointerPosition);
  const navigate = useNavigate();
  const [showAttributeTable, setShowAttributeTable] = useState(false);
  const [selectedLayer, setSelectedLayer] = useState<MapLayer | null>(null);
  const [activeActions, setActiveActions] = useState<EphemeralAction[]>([]);

  const [isSaving, setIsSaving] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);

  // Function to handle basemap changes
  const handleBasemapChange = useCallback(async (newBasemap: string) => {
    setCurrentBasemap(newBasemap);
  }, []);

  // Function to get the appropriate icon for an action
  const getActionIcon = (action: string) => {
    if (action.includes('thinking')) {
      return <Brain className="animate-pulse w-4 h-4 mr-2" />;
    } else if (action.includes('Downloading data from OpenStreetMap')) {
      return <Download className="animate-pulse w-4 h-4 mr-2" />;
    } else if (action.includes('SQL')) {
      return <Database className="animate-pulse w-4 h-4 mr-2" />;
    } else if (action.includes('Sending message')) {
      return <Send className="animate-pulse w-4 h-4 mr-2" />;
    } else {
      return <Activity className="w-4 h-4 mr-2 animate-pulse" />;
    }
  };

  // State for changelog entries
  // State for changelog entries from map data
  const [changelog, setChangelog] = useState<
    Array<{
      summary: string;
      timestamp: string;
      mapState: string;
    }>
  >([]);
  const [messages, setMessages] = useState<ChatCompletionMessageRow[]>([]);
  const [showMessages, setShowMessages] = useState(true);

  useEffect(() => {
    if (updateMapData) {
      updateMapData(mapId);
    }
  }, [mapId, updateMapData]);

  // Process changelog data when mapData changes
  useEffect(() => {
    if (mapData?.changelog) {
      const formattedChangelog = mapData.changelog.map((entry) => ({
        summary: entry.message,
        timestamp: new Date(entry.last_edited).toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        }),
        mapState: entry.map_state,
      }));
      setChangelog(formattedChangelog);
    }
  }, [mapData]);

  useEffect(() => {
    if (isCancelling) {
      const cancelActions = async () => {
        await fetch(`/api/maps/${mapId}/messages/cancel`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({}),
        });

        toast.success('Actions cancelled');
        setIsCancelling(false);
      };

      cancelActions();
    }
  }, [isCancelling, mapId]);

  const [selectedFeature, setSelectedFeature] = useState<MapGeoJSONFeature | null>(null);

  const UPDATE_KUE_POINTER_MSEC = 40;
  const KUE_CURVE_DURATION_MS = 2000;

  // State for Kue's animated positions (indexed by action_id)
  const [kuePositions, setKuePositions] = useState<Record<string, { lng: number; lat: number }>>({});
  const [kueTargetPoints, setKueTargetPoints] = useState<Record<string, Array<{ lng: number; lat: number }>>>({});

  // Generate random points within layer bounds
  const generateRandomPointsInBounds = useCallback((bounds: number[], count: number = 3) => {
    const [minLng, minLat, maxLng, maxLat] = bounds;
    const points = [];

    for (let i = 0; i < count; i++) {
      points.push({
        lng: minLng + Math.random() * (maxLng - minLng),
        lat: minLat + Math.random() * (maxLat - minLat),
      });
    }

    return points;
  }, []);

  // Quadratic Bezier curve interpolation from p0 to p2 through p1
  const bezierInterpolate = useCallback(
    (p0: { lng: number; lat: number }, p1: { lng: number; lat: number }, p2: { lng: number; lat: number }, t: number) => {
      const invT = 1 - t;
      return {
        lng: invT * invT * p0.lng + 2 * invT * t * p1.lng + t * t * p2.lng,
        lat: invT * invT * p0.lat + 2 * invT * t * p1.lat + t * t * p2.lat,
      };
    },
    [],
  );

  // Update Kue's target points when active actions change
  useEffect(() => {
    const activeLayerActions = activeActions.filter((action) => action.status === 'active' && action.layer_id);

    // Get current action IDs
    const currentActionIds = new Set(activeLayerActions.map((action) => action.action_id));

    // Remove state for actions that are no longer active
    setKuePositions((prev) => {
      const filtered = Object.fromEntries(Object.entries(prev).filter(([actionId]) => currentActionIds.has(actionId)));
      return filtered;
    });
    setKueTargetPoints((prev) => {
      const filtered = Object.fromEntries(Object.entries(prev).filter(([actionId]) => currentActionIds.has(actionId)));
      return filtered;
    });

    // Add state for new actions
    if (mapData?.layers) {
      activeLayerActions.forEach((action) => {
        const layer = mapData.layers.find((l) => l.id === action.layer_id);
        if (layer?.bounds && layer.bounds.length >= 4) {
          const actionId = action.action_id;

          // Only initialize if not already present
          setKueTargetPoints((prev) => {
            if (prev[actionId]) return prev;
            const newTargetPoints = generateRandomPointsInBounds(layer.bounds!);
            return { ...prev, [actionId]: newTargetPoints };
          });

          setKuePositions((prev) => {
            if (prev[actionId]) return prev;
            const newTargetPoints = generateRandomPointsInBounds(layer.bounds!);
            return { ...prev, [actionId]: newTargetPoints[0] };
          });
        }
      });
    }
  }, [activeActions, mapData, generateRandomPointsInBounds]);

  // Animate Kue's positions based on timestamp
  useEffect(() => {
    const activeActionIds = Object.keys(kueTargetPoints);
    if (activeActionIds.length === 0) return;

    const interval = setInterval(() => {
      const now = Date.now();

      activeActionIds.forEach((actionId) => {
        const targetPoints = kueTargetPoints[actionId];

        if (targetPoints && targetPoints.length >= 2) {
          // Calculate progress based on timestamp modulo curve duration
          const progress = (now % KUE_CURVE_DURATION_MS) / KUE_CURVE_DURATION_MS;

          // Check if we've started a new curve cycle
          const currentCycle = Math.floor(now / KUE_CURVE_DURATION_MS);
          const lastCycle = Math.floor((now - UPDATE_KUE_POINTER_MSEC) / KUE_CURVE_DURATION_MS);

          if (currentCycle !== lastCycle) {
            // Generate new random points for the new curve
            const layer = mapData?.layers?.find((l) => activeActions.find((a) => a.action_id === actionId)?.layer_id === l.id);
            if (layer?.bounds) {
              const newTargetPoints = generateRandomPointsInBounds(layer.bounds);
              setKueTargetPoints((prev) => ({
                ...prev,
                [actionId]: newTargetPoints,
              }));
              return; // Skip position update this frame to use new points next frame
            }
          }

          const startPoint = targetPoints[0];
          const middlePoint = targetPoints[1];
          const endPoint = targetPoints[2];

          const interpolatedPosition = bezierInterpolate(startPoint, middlePoint, endPoint, progress);

          setKuePositions((prev) => ({
            ...prev,
            [actionId]: interpolatedPosition,
          }));
        }
      });
    }, UPDATE_KUE_POINTER_MSEC);

    return () => clearInterval(interval);
  }, [kueTargetPoints, activeActions, mapData, bezierInterpolate, generateRandomPointsInBounds]);

  // Generate GeoJSON from pointer positions
  const pointsGeoJSON = useMemo(() => {
    const features: GeoJSON.Feature[] = [];

    // Add real user pointer positions
    Object.entries(otherClientPositions)
      .filter(([, data]) => data !== null && data.value !== null && 'lng' in data.value && 'lat' in data.value)
      .forEach(([id, data]) => {
        const presenceData = data as unknown as PresenceData;
        features.push({
          type: 'Feature' as const,
          geometry: {
            type: 'Point' as const,
            coordinates: [presenceData.value.lng, presenceData.value.lat],
          },
          properties: {
            user: id,
            abbrev: id.substring(0, 6),
            color: '#' + id.substring(0, 6),
          },
        });
      });

    // Add Kue's animated positions
    Object.entries(kuePositions).forEach(([actionId, position]) => {
      features.push({
        type: 'Feature' as const,
        geometry: {
          type: 'Point' as const,
          coordinates: [position.lng, position.lat],
        },
        properties: { user: 'Kue', abbrev: 'Kue', color: '#ff69b4', actionId },
      });
    });

    return {
      type: 'FeatureCollection' as const,
      features,
    };
  }, [otherClientPositions, kuePositions]);

  const loadLegendSymbols = useCallback(
    (map: MLMap) => {
      const style = map.getStyle();

      // Check if style and style.layers exist before proceeding
      if (!style || !style.layers) return;

      mapData?.layers.forEach((layer) => {
        const layerId = layer.id;

        const mapLayer = style.layers.find((styleLayer) => 'source' in styleLayer && (styleLayer as any).source === layerId);

        if (mapLayer) {
          const tree: RenderElement | null = legendSymbol({
            sprite: style.sprite,
            zoom: map.getZoom(),
            layer: mapLayer as any,
          });
          // long lasting bug
          if (tree?.attributes?.style?.backgroundImage === 'url(null)') {
            tree.attributes.style.backgroundImage = 'none';
            tree.attributes.style.width = '16px';
            tree.attributes.style.height = '16px';
            tree.attributes.style.opacity = '1.0';
          }

          const symbolElement = renderTree(tree);
          if (symbolElement) {
            setLayerSymbols((prev) => ({
              ...prev,
              [layerId]: symbolElement as JSX.Element,
            }));
          }
        }
      });
    },
    [mapData],
  );

  // effect runs when map initializes AND when new point clouds are added
  useEffect(() => {
    if (!mapContainerRef.current) return;

    // need to nuke in order to re-draw, TODO this can be improved
    if (mapRef.current) {
      mapRef.current.remove();
      mapRef.current = null;
    }

    try {
      // Initialize the map with a basic style first
      const mapOptions: MapOptions = {
        container: mapContainerRef.current,
        style: {
          version: 8,
          sources: {},
          layers: [],
        }, // Start with empty style so map loads
        attributionControl: {
          compact: false,
        },
      };

      const newMap = new MLMap(mapOptions);
      mapRef.current = newMap;

      // Define cursor image loading function
      const loadCursorImage = () => {
        const cursorImage = new Image();
        cursorImage.onload = () => {
          if (newMap.isStyleLoaded()) {
            if (newMap.hasImage('remote-cursor')) {
              newMap.removeImage('remote-cursor');
            }
            newMap.addImage('remote-cursor', cursorImage);
          }
        };
        cursorImage.src =
          'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIAAAAyCAYAAAAeP4ixAAAACXBIWXMAAAsTAAALEwEAmpwYAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAIRSERBVHgB7dnNsdowFAXgQ5INO9OBt9m5BKUDOsAl0AHuIO4AUgF0YKgAOrCpwLDL7kbnPUHAETEY8yy98TejsWf8fnQsc3UBoNfr9WrkZoTwnMxmM8EnCCP0GcLIyXw+P4WJ4CG5tFwuZTQalfAwjFRtt1sJgoCrM4FHxCbPcwnDkGGm8ITcchFmBg/I//gURur4EkbuUZalRFHEMD/hKLkXw4zHY4aZw0HyqMlkwjBbPQI4RJowLQ3DhHCENOVafybPcCmMPMuVMNIGFzpnaUvXnbO0qcvOWdrWVecsr9BFfyav0iTMAM3xf+JZh8PhPIqieDvu93vsdjusVqu75/gNH2iz2SBN0/OEzTjoS6dRmOPeHHf4APIodsH8PT0U3jfB1prHL3gR3nXzaJzp8oo4jnmq8Pfud672xcpRlWUZV4SbnzOtvDXExcYW65Fx4lVKqdN1J1hDmFZjbH4m5qRvrEoGR1xNbrFY2PolPj4lA95YFQUHXIXA7Q42mU6nTq/K24SSJKl7TxFwpVh6q8zurdCCr2guGQwG0EEKff4D7+XU5rf2fTgcRvpxurpwPB6xXq9DffoLHXrkGyvFSlbFVTIV7p6/4QxrKTaPZgqPKFsp5qqYaufUZ111StuqsKrpawk8Yi3FbGngWNtS559SzBUym2MOz6R8gfNjIBOAm2IMD3H3591nAIVez21/ACUSSP4DF2G8AAAAAElFTkSuQmCC';
      };

      newMap.on('load', () => {
        // Add navigation controls
        newMap.addControl(new NavigationControl(), 'top-right');
        newMap.addControl(new ScaleControl(), 'bottom-left');

        // Add export PDF control below the navigation controls
        const exportPDFControl = new ExportPDFControl(mapId);
        exportPDFControlRef.current = exportPDFControl;
        newMap.addControl(exportPDFControl, 'top-right');

        newMap.on('click', (e) => {
          const features = newMap.queryRenderedFeatures(e.point);
          if (!features.length) return;

          const feature = features[0];

          setSelectedFeature((prev: MapGeoJSONFeature | null) => {
            if (prev) {
              newMap.setFeatureState({ source: prev.source, sourceLayer: prev.sourceLayer, id: prev.id }, { selected: false });
            }

            newMap.setFeatureState({ source: feature.source, sourceLayer: feature.sourceLayer, id: feature.id }, { selected: true });
            return feature;
          });
        });

        const overlaidPCLayers = pointCloudLayers.map((layer) => createPointCloudLayer(layer));

        const deckOverlay = new MapboxOverlay({
          interleaved: true,
          layers: overlaidPCLayers,
        });
        deckOverlayRef.current = deckOverlay;
        newMap.addControl(deckOverlay);

        // Load cursor image initially
        loadCursorImage();

        setLoading(false);
      });

      newMap.on('mousemove', (e) => {
        const wrapped = e.lngLat.wrap();
        setPointerPosition({
          lng: wrapped.lng,
          lat: wrapped.lat,
        });
      });

      newMap.on('error', (e) => {
        console.error('MapLibre GL error:', e);
        const message = e.error?.message || 'Unknown error';
        if (message.indexOf('AJAXError') !== -1 && message.indexOf('(502)') !== -1 && message.indexOf('.mvt') !== -1) {
          // This just means database is slow
          addError('PostGIS query took 60+ seconds, database might be overloaded', true);
        } else {
          addError('Error loading map: ' + message, true);
        }
        setLoading(false);
      });

      newMap.on('style.load', () => {
        loadLegendSymbols(newMap);
        loadCursorImage();
      });

      // Clean up on unmount
      return () => {
        newMap.remove();
        mapRef.current = null;
      };
    } catch (err) {
      console.error('Error initializing map:', err);
      addError('Failed to initialize map: ' + (err instanceof Error ? err.message : String(err)), true);
      setLoading(false);
    }
  }, [addError, loadLegendSymbols, mapId, pointCloudLayers, createPointCloudLayer]); // listen to point cloud layers

  // Separate effect for style updates
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    // Prevent multiple simultaneous style updates
    let isUpdating = false;

    // Wait for map to be loaded before updating style
    const updateStyle = async () => {
      if (isUpdating) {
        return;
      }

      isUpdating = true;

      try {
        // Fetch the new style with current basemap
        const url = new URL(`/api/maps/${mapId}/style.json`, window.location.origin);
        if (currentBasemap) {
          url.searchParams.set('basemap', currentBasemap);
        }
        const response = await fetch(url.toString());
        if (!response.ok) {
          throw new Error(`Failed to fetch style: ${response.statusText}`);
        }
        const newStyle = await response.json();

        // Update the style using setStyle
        map.setStyle(newStyle);
        loadLegendSymbols(map);

        // If we haven't zoomed yet, zoom to the style's center and zoom level
        // setStyle on purpose does not reset the zoom/center, but it's nice to load a map
        // and be correctly positioned on the data
        if (!hasZoomed) {
          if (newStyle.center && newStyle.zoom !== undefined) {
            map.jumpTo({
              center: newStyle.center,
              zoom: newStyle.zoom,
              pitch: newStyle.pitch || 0,
              bearing: newStyle.bearing || 0,
            });
          }
          setHasZoomed(true);
        }

        isUpdating = false; // Reset flag when done
      } catch (err) {
        console.error('Error updating style:', err);
        addError('Failed to update map style: ' + (err instanceof Error ? err.message : String(err)), true);
        isUpdating = false; // Reset flag on error
      }
    };

    // If map is already loaded, update immediately, otherwise wait for load
    updateStyle();
  }, [mapId, currentBasemap, addError, loadLegendSymbols, hasZoomed]); // Update when these dependencies change

  useEffect(() => {
    if (!mapRef.current) return;

    const map = mapRef.current;
    if (!map.isStyleLoaded()) return;

    const style = map.getStyle();
    if (!style || !style.layers) return;

    style.layers.forEach((layer) => {
      if ('source' in layer && layer.source) {
        const visibility = hiddenLayerIDs.includes(layer.source as string) ? 'none' : 'visible';
        map.setLayoutProperty(layer.id, 'visibility', visibility);
      }
    });
  }, [hiddenLayerIDs]);

  // Update the points source when pointer positions change
  useEffect(() => {
    const map = mapRef.current;
    if (map && map.isStyleLoaded()) {
      const source = map.getSource('pointer-positions');
      if (source) {
        (source as maplibregl.GeoJSONSource).setData(pointsGeoJSON);
      }
    }
  }, [pointsGeoJSON]);

  const status = useConnectionStatus();
  const [inputValue, setInputValue] = useState('');

  // Function to fetch messages
  const fetchMessages = useCallback(async () => {
    try {
      const response = await fetch(`/api/maps/${mapId}/messages`);
      if (response.ok) {
        const data = await response.json();
        // Ensure messages from fetch are sorted by message_index
        const fetchedMessages: ChatCompletionMessageRow[] = data.messages.sort(
          (a: ChatCompletionMessageRow, b: ChatCompletionMessageRow) => a.id - b.id,
        );

        setMessages(fetchedMessages);
      } else {
        console.error('Error fetching messages:', response.statusText);
      }
    } catch (error) {
      console.error('Error fetching messages:', error);
    }
  }, [mapId]);

  // Function to send a message
  const sendMessage = async (text: string) => {
    if (!text.trim()) return;

    setInputValue(''); // Clear input after preparing to send

    const userMessage: ChatCompletionUserMessageParam = {
      role: 'user',
      content: text,
    };
    // Create and add ephemeral action
    const actionId = `send-message-${Date.now()}`;
    const sendingAction: EphemeralAction = {
      map_id: mapId,
      ephemeral: true,
      action_id: actionId,
      action: 'Sending message to Kue...',
      timestamp: new Date().toISOString(),
      completed_at: null,
      layer_id: null,
      status: 'active',
      updates: {
        style_json: false,
      },
    };
    setActiveActions((prev) => [...prev, sendingAction]);

    try {
      const response = await fetch(`/api/maps/${mapId}/messages/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(userMessage),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(errorData.detail || response.statusText);
      }

      // const data: ChatProcessingResponse = await response.json();
    } catch (error) {
      addError(error instanceof Error ? error.message : 'Network error', true);
    } finally {
      // Remove the ephemeral action when done
      setActiveActions((prev) => prev.filter((a) => a.action_id !== actionId));
    }
  };
  // WebSocket using react-use-websocket
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const [jwt, setJwt] = useState<string | undefined>(undefined);
  const sessionContext = Session.useSessionContext();
  // authenticating web sockets
  useEffect(() => {
    const getSessionData = async () => {
      if (await Session.doesSessionExist()) {
        const accessToken = await Session.getAccessToken();

        setJwt(accessToken);
      }
    };
    getSessionData();
  }, []);

  const wsUrl = useMemo(() => {
    if (!mapId) {
      return null;
    } else if (!jwt) {
      return `${wsProtocol}//${window.location.host}/api/maps/ws/${mapId}/messages/updates`;
    }

    return `${wsProtocol}//${window.location.host}/api/maps/ws/${mapId}/messages/updates?token=${jwt}`;
  }, [mapId, wsProtocol, jwt]);

  // Track page visibility and allow socket to remain open for 10 minutes after hidden
  const WS_REMAIN_OPEN_FOR_MS = 10 * 60 * 1000; // 10 minutes
  const [isTabVisible, setIsTabVisible] = useState<boolean>(document.visibilityState === 'visible');
  const [hiddenTimeoutExpired, setHiddenTimeoutExpired] = useState<boolean>(false);
  const hiddenTimerRef = useRef<number | null>(null);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        setIsTabVisible(true);
        setHiddenTimeoutExpired(false);
        if (hiddenTimerRef.current !== null) {
          clearTimeout(hiddenTimerRef.current);
          hiddenTimerRef.current = null;
        }
      } else {
        setIsTabVisible(false);
        hiddenTimerRef.current = window.setTimeout(() => {
          setHiddenTimeoutExpired(true);
          hiddenTimerRef.current = null;
        }, WS_REMAIN_OPEN_FOR_MS);
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      if (hiddenTimerRef.current !== null) {
        clearTimeout(hiddenTimerRef.current);
      }
    };
  }, []);

  // WebSocket using react-use-websocket
  const shouldConnect = !sessionContext.loading && (isTabVisible || !hiddenTimeoutExpired);
  const { lastMessage, readyState } = useWebSocket(
    wsUrl,
    {
      onError: () => {
        addError('Chat connection error.', false);
      },
      shouldReconnect: () => true,
      reconnectAttempts: 2880, // 24 hours of continuous work, at 30 seconds each = 2,880
      reconnectInterval: 30, // interval *between* reconnects, 30 milliseconds
    },
    shouldConnect,
  );

  // Process incoming messages
  useEffect(() => {
    if (lastMessage) {
      try {
        const update = JSON.parse(lastMessage.data as string);

        // Check if this is an ephemeral action
        if (update.ephemeral === true) {
          const action = update as EphemeralAction;

          // Check if this is an error notification
          if (action.error_message) {
            // Don't add error notifications to active actions, instead treat as error
            addError(action.error_message, true);
            return; // Early return to skip normal ephemeral action handling
          }

          // Handle bounds zooming only when action becomes active (not on completion)
          if (action.bounds && action.bounds.length === 4 && mapRef.current && action.status === 'active') {
            // Check if we've already processed this action
            if (processedBoundsActionIds.current.has(action.action_id)) {
              return;
            }
            processedBoundsActionIds.current.add(action.action_id);
            // Save current bounds to history before zooming
            const currentBounds = mapRef.current.getBounds();
            const currentBoundsArray: [number, number, number, number] = [
              currentBounds.getWest(),
              currentBounds.getSouth(),
              currentBounds.getEast(),
              currentBounds.getNorth(),
            ];

            // Add both current bounds and new bounds to history in a single update
            setZoomHistory((prev) => {
              const historyUpToCurrent = prev.slice(0, zoomHistoryIndex + 1);
              return [...historyUpToCurrent, { bounds: currentBoundsArray }, { bounds: action.bounds as [number, number, number, number] }];
            });

            // Update index to point to the final new bounds (current + 2 positions)
            setZoomHistoryIndex((prev) => prev + 2);

            // Zoom to new bounds
            const [west, south, east, north] = action.bounds;
            mapRef.current.fitBounds(
              [
                [west, south],
                [east, north],
              ],
              { animate: true, padding: 50 },
            );
          }

          if (action.status === 'active') {
            // Add to active actions
            setActiveActions((prev) => [...prev, action]);
          } else if (action.status === 'completed') {
            // Remove from active actions
            setActiveActions((prev) => prev.filter((a) => a.action_id !== action.action_id));

            // Style updates are handled by the currentBasemap dependency
          }
        } else {
          // Regular message
          setMessages((prevMessages) => {
            const newMessages = [...prevMessages, update as ChatCompletionMessageRow];
            return newMessages;
          });
        }
      } catch (e) {
        console.error('Error processing WebSocket message:', e);
        addError('Failed to process update from server.', false);
      }
    }
  }, [lastMessage, addError, zoomHistoryIndex]);

  // Handle input submission
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && inputValue.trim()) {
      sendMessage(inputValue);
      setInputValue('');
    }
  };

  // Fetch messages on component mount
  useEffect(() => {
    if (mapId) {
      fetchMessages();
    }
  }, [mapId, fetchMessages]);

  // Fetch available basemaps on component mount
  useEffect(() => {
    const fetchAvailableBasemaps = async () => {
      try {
        const response = await fetch('/api/basemaps/available');
        if (response.ok) {
          const data = await response.json();
          setAvailableBasemaps(data.styles);
          if (data.styles.length > 0) {
            setCurrentBasemap(data.styles[0]); // Set first style as default
          }
        }
      } catch (error) {
        console.error('Error fetching available basemaps:', error);
      }
    };

    fetchAvailableBasemaps();
  }, []);

  // Fetch demo config on component mount
  useEffect(() => {
    const fetchDemoConfig = async () => {
      try {
        const response = await fetch('/api/projects/config/demo-postgis-available');
        if (response.ok) {
          const data = await response.json();
          setDemoConfig(data);
        }
      } catch (error) {
        console.error('Error fetching demo config:', error);
      }
    };

    fetchDemoConfig();
  }, []);

  // Add globe control when map and basemaps are available
  useEffect(() => {
    const map = mapRef.current;
    if (map && availableBasemaps.length > 0 && currentBasemap && !globeControlRef.current) {
      const globeControl = new GlobeControl(availableBasemaps, currentBasemap, handleBasemapChange);
      globeControlRef.current = globeControl;
      map.addControl(globeControl);
    }
  }, [availableBasemaps, currentBasemap, handleBasemapChange]);

  // Update globe control when basemap changes
  useEffect(() => {
    if (globeControlRef.current && currentBasemap) {
      globeControlRef.current.updateBasemap(currentBasemap);
    }
  }, [currentBasemap]);

  // Function to fork the current map
  const saveAndForkMap = async () => {
    setIsSaving(true);
    try {
      const response = await fetch(`/api/maps/${mapId}/save_fork`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        toast.success('Map forked successfully');
        // Navigate to the new forked map
        navigate(`/project/${data.project_id}/${data.map_id}`);
      } else {
        addError('Failed to fork map', false);
        console.error('Error forking map:', response.statusText);
      }
    } catch (error) {
      addError('Failed to fork map', false);
      console.error('Error forking map:', error);
    } finally {
      setIsSaving(false);
    }
  };

  // Effect to log when attribute table is opened/closed
  useEffect(() => {
    if (showAttributeTable && selectedLayer) {
      // Debug: Opening attributes for layer
    }
  }, [showAttributeTable, selectedLayer]);
  // Find the last message in the conversation history
  const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null;

  // Determine the last assistant message to display. Only show if it's the very
  // last message in the conversation and has text content.
  const lastAssistantMsg: string | null =
    lastMsg && lastMsg.message_json.role === 'assistant' && typeof lastMsg.message_json.content === 'string'
      ? (lastMsg.message_json.content as string)
      : null;

  // Determine the last user message for the input placeholder.
  const lastUserMsg: string | null =
    lastMsg && lastMsg.message_json.role === 'user' && typeof lastMsg.message_json.content === 'string'
      ? (lastMsg.message_json.content as string)
      : null;

  // especially chat disconnected errors happen all the time and shouldn't
  // override the text box
  const criticalErrors = errors.filter((e) => e.shouldOverrideMessages);

  return (
    <>
      <div className={`relative map-container ${className} grow max-h-screen`} style={{ width, height }}>
        <div ref={mapContainerRef} style={{ width: '100%', height: '100%', minHeight: '100vh' }} className="bg-slate-950" />

        {/* Render the attribute table if showAttributeTable is true */}
        {selectedLayer && (
          <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 z-50 w-4/5 max-w-4xl">
            <AttributeTable layer={selectedLayer} isOpen={showAttributeTable} onClose={() => setShowAttributeTable(false)} />
          </div>
        )}

        {mapData && openDropzone && saveAndForkMap && (
          <LayerList
            project={project}
            currentMapData={mapData}
            mapRef={mapRef}
            openDropzone={openDropzone}
            saveAndForkMap={saveAndForkMap}
            isSaving={isSaving}
            readyState={readyState}
            activeActions={activeActions}
            driftDbConnected={status.connected}
            setShowAttributeTable={setShowAttributeTable}
            setSelectedLayer={setSelectedLayer}
            updateMapData={updateMapData}
            updateProjectData={updateProjectData}
            layerSymbols={layerSymbols}
            zoomHistory={zoomHistory}
            zoomHistoryIndex={zoomHistoryIndex}
            setZoomHistoryIndex={setZoomHistoryIndex}
            uploadingFiles={uploadingFiles}
            demoConfig={demoConfig}
            hiddenLayerIDs={hiddenLayerIDs}
            toggleLayerVisibility={toggleLayerVisibility}
          />
        )}
        {selectedFeature && (
          <Card className="absolute bottom-10 left-4 max-h-[60vh] overflow-auto py-2 rounded-sm border-0 gap-2 max-w-72 w-full">
            <CardHeader className="px-2">
              <CardTitle className="text-base flex justify-between items-center gap-2">
                <div className="flex gap-2 items-baseline">
                  {mapData?.layers.find((l) => l.id === selectedFeature.source) ? (
                    <>
                      <span>{mapData?.layers.find((l) => l.id === selectedFeature.source)?.name}</span>
                      <span className="text-xs text-gray-500 dark:text-gray-400">{mapData?.layers.find((l) => l.id === selectedFeature.source)?.type}</span>
                    </>
                  ) : (
                    <span>Selected feature</span>
                  )}
                </div>
                <button
                  onClick={() => setSelectedFeature(null)}
                  className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                  title="Close"
                >
                  <X className="h-4 w-4 cursor-pointer" />
                </button>
              </CardTitle>
            </CardHeader>
            <CardContent className="px-2 max-h-[50vh] overflow-auto">
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left py-1 pr-2 font-medium">Property</th>
                      <th className="text-left py-1 font-medium">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedFeature.properties &&
                      Object.entries(selectedFeature.properties).map(([key, value]) => (
                        <tr key={key} className="border-b border-gray-100 dark:border-gray-700" title={`Type: ${typeof value}`}>
                          <td className="py-1 pr-2 font-mono text-gray-600 dark:text-gray-400 break-all">{key}</td>
                          <td className="py-1 font-mono break-all">{String(value)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )}
        <Command
          className={`z-30 absolute bottom-4 left-4 max-h-[18vh] hover:max-h-[70vh] transition-all duration-300 ring ring-black hover:ring-white max-w-72 overflow-auto py-2 rounded-sm bg-white dark:bg-gray-800 shadow-md ${selectedFeature ? 'hidden' : ''}`}
        >
          <CommandInput placeholder={`Search ${changelog.length} versions...`} />
          {/* Apply flex properties to CommandList to align content to the bottom */}
          {/* This should push the CommandGroup towards the bottom of the scrollable area */}
          <CommandList className="flex flex-col justify-end">
            <CommandEmpty>No versions found.</CommandEmpty>
            <CommandGroup>
              {/* Map in original order. Newest items (assuming they are last in the array) */}
              {/* will be rendered last, appearing at the bottom due to justify-end. */}
              {changelog.map((entry) => (
                <CommandItem
                  key={entry.mapState} // Use a stable unique key like mapState
                  onSelect={() => {
                    if (entry.mapState) {
                      navigate(`/project/${mapData?.project_id}/${entry.mapState}`);
                    }
                  }}
                  className={`cursor-pointer ${entry.mapState === mapId ? 'bg-gray-900 hover:bg-gray-900 data-[selected=true]:bg-gray-900' : 'data-[selected=true]:bg-gray-700'}`}
                >
                  <span className="font-medium">{entry.summary}</span>
                  <span className="text-xs text-slate-500 dark:text-gray-400 ml-auto shrink-0">{entry.timestamp}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
        {/* Message display component - always show parent div, animate height */}
        {(criticalErrors.length > 0 || activeActions.length > 0 || lastAssistantMsg) && (
          <div
            className={`z-30 absolute bottom-12 mb-[34px] opacity-90 left-3/5 transform -translate-x-1/2 w-4/5 max-w-lg overflow-auto bg-white dark:bg-gray-800 rounded-t-md shadow-md p-2 text-sm transition-all duration-300 max-h-40 h-auto ${errors.length > 0 ? 'border-red-800' : ''}`}
          >
            {criticalErrors.length > 0 ? (
              <div className="space-y-1 max-h-20">
                {criticalErrors.map((error) => (
                  <div key={error.id} className="flex items-center justify-between">
                    <div className="flex flex-col flex-1 mr-2">
                      <span className="text-red-400">{error.message}</span>
                      <span className="text-xs text-slate-500 dark:text-gray-400">{error.timestamp.toLocaleTimeString()}</span>
                    </div>
                    <button
                      onClick={() => dismissError(error.id)}
                      className="text-white cursor-pointer hover:underline shrink-0"
                      title="Dismiss error"
                    >
                      Dismiss
                    </button>
                  </div>
                ))}
              </div>
            ) : activeActions.length > 0 ? (
              <div className="flex items-center justify-between">
                <ol className="space-y-1">
                  {activeActions.map((action, actionIndex) => (
                    <li key={`${action.action_id}-${actionIndex}`} className="flex items-center">
                      {getActionIcon(action.action)}
                      <span>{action.action}</span>
                    </li>
                  ))}
                </ol>
                {isCancelling ? (
                  <span className="text-white ml-2 shrink-0">Cancelling...</span>
                ) : (
                  <button className="text-white cursor-pointer ml-2 shrink-0 hover:underline" onClick={() => setIsCancelling(true)}>
                    Cancel
                  </button>
                )}
              </div>
            ) : lastAssistantMsg ? (
              <div className={KUE_MESSAGE_STYLE}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{lastAssistantMsg}</ReactMarkdown>
              </div>
            ) : null}
          </div>
        )}
        <div
          className={`z-30 absolute bottom-12 left-3/5 transform -translate-x-1/2 w-4/5 max-w-xl bg-white dark:bg-gray-800 shadow-md focus-within:ring-2 focus-within:ring-white/30 flex items-center border border-input bg-input rounded-md ${!showMessages ? 'rounded-l-md' : 'rounded-md'}`}
        >
          <Input
            className={`flex-1 border-none shadow-none !bg-transparent focus:!ring-0 focus:!ring-offset-0 focus-visible:!ring-0 focus-visible:!ring-offset-0 focus-visible:!outline-none`}
            placeholder={lastUserMsg || 'Type in for Kue to do something...'}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={showMessages ? () => setShowMessages(false) : () => setShowMessages(true)}
                className={`p-2 hover:cursor-pointer ${
                  showMessages ? 'text-gray-600 hover:text-gray-500' : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                <MessagesSquare className="h-4 w-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent>
              <p>{showMessages ? 'Hide chat' : 'Show chat'}</p>
            </TooltipContent>
          </Tooltip>
        </div>

        {loading && (
          <div className="flex items-center justify-center">
            <div className="text-gray-700">Loading map...</div>
          </div>
        )}
      </div>

      {/* Chat sidebar */}
      {showMessages && (
        <div className="z-30 max-h-screen h-full w-120 bg-white dark:bg-gray-800 shadow-md flex flex-col text-sm">
          <div className="p-2 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
            <h3 className="font-semibold">Chat with Kue</h3>
            <button
              onClick={() => setShowMessages(false)}
              className="text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:cursor-pointer"
            >
              Hide
            </button>
          </div>
          <div className="flex-1 overflow-auto p-2">
            {messages.map((msg, index) => {
              let messageClass = '';
              let contentDisplay = '';

              const messageJson = msg.message_json;

              if (messageJson.role === 'user') {
                messageClass = 'bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600';

                // Handle content that could be string or array with image
                if (typeof messageJson.content === 'string') {
                  contentDisplay = messageJson.content;
                } else if (Array.isArray(messageJson.content)) {
                  // Process array content (text + images)
                  const textParts = (messageJson.content as any[])
                    .filter((part: any) => part.type === 'text')
                    .map((part: any) => part.text)
                    .join('\n');

                  contentDisplay = textParts;
                } else {
                  contentDisplay = '';
                }
              } else if (messageJson.role === 'assistant') {
                messageClass = '';

                // Merge assistant text content with any tool_calls
                const parts: string[] = [];
                // include text content if present
                if (typeof messageJson.content === 'string' && messageJson.content) {
                  parts.push(messageJson.content);
                }
                // include any tool calls
                if (messageJson.tool_calls && messageJson.tool_calls.length > 0) {
                  parts.push(
                    ...messageJson.tool_calls.map(
                      (tc: ChatCompletionMessageToolCall) => `Using tool: ${tc.function.name}(${tc.function.arguments})`,
                    ),
                  );
                }
                contentDisplay = parts.join('\n');
              } else if (messageJson.role === 'tool') {
                messageClass = 'bg-purple-100 dark:bg-purple-900';
                contentDisplay = typeof messageJson.content === 'string' ? messageJson.content : '';
              } else if (messageJson.role === 'system') {
                messageClass = 'bg-yellow-100 dark:bg-yellow-900 italic whitespace-pre-wrap';
                contentDisplay = typeof messageJson.content === 'string' ? messageJson.content : '';
              }

              // Skip rendering if contentDisplay is falsy and there are no images
              const hasImages =
                Array.isArray(messageJson.content) && (messageJson.content as any[]).some((part: any) => part.type === 'image_url');

              if (!contentDisplay && !hasImages) {
                return null;
              }

              return (
                <div
                  key={`msg-${msg.id || index}-${index}`}
                  className={`mb-3 ${messageClass ? `p-2 rounded ${messageClass}` : ''} text-sm`}
                >
                  {messageJson.role === 'assistant' ? (
                    <div className={KUE_MESSAGE_STYLE}>
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{contentDisplay}</ReactMarkdown>
                    </div>
                  ) : (
                    <span>{contentDisplay}</span>
                  )}

                  {/* Render images if present */}
                  {Array.isArray(messageJson.content) &&
                    (messageJson.content as any[])
                      .filter((part: any) => part.type === 'image_url')
                      .map((part: any, imgIndex: number) => (
                        <div key={`msg-${msg.id || index}-img-${imgIndex}`} className="mt-2">
                          <img
                            src={part.image_url.url}
                            alt="Message attachment"
                            className="max-w-full rounded-md"
                            style={{ maxHeight: '200px' }}
                          />
                        </div>
                      ))}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}
