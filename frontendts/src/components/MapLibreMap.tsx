// Copyright Bunting Labs, Inc. 2025

import { useConnectionStatus, usePresence } from 'driftdb-react';
import legendSymbol, { type RenderElement } from 'legend-symbol-ts';
import {
  Activity,
  AlertTriangle,
  Brain,
  ChevronLeft,
  ChevronRight,
  Database,
  Info,
  Loader2,
  MessagesSquare,
  MoreHorizontal,
  RotateCw,
  Send,
  SignalHigh,
  SignalLow,
} from 'lucide-react';
import { type IControl, type MapOptions, Map as MLMap, NavigationControl, ScaleControl } from 'maplibre-gl';
import type {
  ChatCompletionMessageParam,
  ChatCompletionMessageToolCall,
  ChatCompletionUserMessageParam,
} from 'openai/resources/chat/completions';
// Copyright Bunting Labs, Inc. 2025
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Download, Save, Upload } from 'react-bootstrap-icons';
import ReactMarkdown from 'react-markdown';
import { useNavigate } from 'react-router-dom';
import useWebSocket, { ReadyState } from 'react-use-websocket';
import remarkGfm from 'remark-gfm';
import { toast } from 'sonner';
import Session from 'supertokens-auth-react/recipe/session';
import AttributeTable from '@/components/AttributeTable';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import type {
  EphemeralAction,
  MapData,
  MapLayer,
  MapProject,
  PointerPosition,
  PostgresConnectionDetails,
  PresenceData,
} from '../lib/types';

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
}
interface LayerWithStatus extends MapLayer {
  status: 'added' | 'removed' | 'edited' | 'existing';
}

interface LayerListProps {
  project: MapProject;
  currentMapData: MapData;
  mapRef: React.RefObject<MLMap | null>;
  openDropzone: () => void;
  saveAndForkMap: () => void;
  isSaving: boolean;
  activeActions: EphemeralAction[];
  readyState: number;
  driftDbConnected: boolean;
  setShowAttributeTable: (show: boolean) => void;
  setSelectedLayer: (layer: MapLayer | null) => void;
  updateMapData: (mapId: string) => void;
  updateProjectData: (projectId: string) => void;
  layerSymbols: { [layerId: string]: JSX.Element };
  zoomHistory: Array<{ bounds: [number, number, number, number] }>;
  zoomHistoryIndex: number;
  setZoomHistoryIndex: React.Dispatch<React.SetStateAction<number>>;
  uploadingFiles?: UploadingFile[];
  demoConfig: { available: boolean; description: string };
}

function renderTree(tree: RenderElement | null): JSX.Element | null {
  if (!tree) return null;
  return React.createElement(tree.element, tree.attributes, tree.children?.map(renderTree));
}

const LayerList: React.FC<LayerListProps> = ({
  project,
  currentMapData,
  mapRef,
  openDropzone,
  saveAndForkMap,
  readyState,
  isSaving,
  activeActions,
  driftDbConnected,
  setShowAttributeTable,
  setSelectedLayer,
  updateMapData,
  updateProjectData,
  layerSymbols,
  zoomHistory,
  zoomHistoryIndex,
  setZoomHistoryIndex,
  uploadingFiles,
  demoConfig,
}) => {
  const navigate = useNavigate();
  const [showPostgisDialog, setShowPostgisDialog] = useState(false);

  // Component to render legend symbol for a layer
  const LayerLegendSymbol = ({ layerDetails }: { layerDetails: MapLayer }) => {
    // Return cached symbol if available, otherwise null
    return layerSymbols[layerDetails.id] || null;
  };
  const [connectionMethod, setConnectionMethod] = useState<'demo' | 'uri' | 'fields'>('uri');
  const [postgisForm, setPostgisForm] = useState({
    uri: '',
    host: '',
    port: '5432',
    database: '',
    username: '',
    password: '',
    schema: 'public',
  });
  const [postgisLoading, setPostgisLoading] = useState(false);
  const [postgisError, setPostgisError] = useState<string | null>(null);

  const handlePostgisConnect = async () => {
    if (!currentMapData?.project_id) {
      toast.error('No project ID available');
      return;
    }

    let connectionUri = '';
    if (connectionMethod === 'demo') {
      connectionUri = 'DEMO'; // Special marker for backend to use DEMO_POSTGIS_URI
    } else if (connectionMethod === 'uri') {
      connectionUri = postgisForm.uri;
    } else {
      // Build URI from form fields
      connectionUri = `postgresql://${postgisForm.username}:${postgisForm.password}@${postgisForm.host}:${postgisForm.port}/${postgisForm.database}`;
    }

    if (!connectionUri.trim() || (connectionMethod !== 'demo' && connectionUri === '')) {
      setPostgisError('Please provide connection details');
      return;
    }

    setPostgisLoading(true);
    setPostgisError(null);

    try {
      const response = await fetch(`/api/projects/${currentMapData.project_id}/postgis-connections`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ connection_uri: connectionUri }),
      });

      if (response.ok) {
        toast.success('PostgreSQL connection saved successfully! Refreshing...');
        setShowPostgisDialog(false);
        // Reset form
        setPostgisForm({
          uri: '',
          host: '',
          port: '5432',
          database: '',
          username: '',
          password: '',
          schema: 'public',
        });

        // Refresh immediately to show "Loading into AI..." in the database list
        updateProjectData(currentMapData.project_id);
        updateMapData(currentMapData.map_id);

        // Poll for updated connection details and refresh when AI naming is complete
        const pollForUpdatedConnection = async () => {
          let attempts = 0;
          const maxAttempts = 225; // 15 minutes max (225 * 4 seconds = 900 seconds)

          const pollInterval = setInterval(async () => {
            attempts++;

            try {
              // Fetch current project data to check connection names
              const response = await fetch(`/api/projects/${currentMapData.project_id}`);
              if (response.ok) {
                const projectData = await response.json();

                // Check if any connections no longer have "Loading..." as the name
                const hasUpdatedNames = projectData.postgres_connections?.some(
                  (conn: PostgresConnectionDetails) => conn.friendly_name && conn.friendly_name !== 'Loading...',
                );

                if (hasUpdatedNames || attempts >= maxAttempts) {
                  clearInterval(pollInterval);
                  // Refresh both project and map data
                  updateProjectData(currentMapData.project_id);
                  updateMapData(currentMapData.map_id);
                }
              }
            } catch (error) {
              console.error('Error polling for connection updates:', error);
            }

            if (attempts >= maxAttempts) {
              clearInterval(pollInterval);
              // Still refresh after max attempts as fallback
              updateProjectData(currentMapData.project_id);
              updateMapData(currentMapData.map_id);
            }
          }, 4000); // Check every 4 seconds
        };

        pollForUpdatedConnection();
      } else {
        const errorData = await response.json().catch(() => ({ detail: response.statusText }));
        setPostgisError(errorData.detail || response.statusText);
      }
    } catch (error) {
      setPostgisError(error instanceof Error ? error.message : 'Network error occurred');
    } finally {
      setPostgisLoading(false);
    }
  };

  const processedLayers = useMemo<LayerWithStatus[]>(() => {
    const currentLayersArray = currentMapData.layers || [];

    // Use diff from currentMapData to determine layer statuses
    if (currentMapData.diff && currentMapData.diff.layer_diffs) {
      const layerDiffMap = new globalThis.Map<string, string>(currentMapData.diff.layer_diffs.map((diff) => [diff.layer_id, diff.status]));

      // Start with current layers
      const layersWithStatus = currentLayersArray.map((layer) => ({
        ...layer,
        status: (layerDiffMap.get(layer.id) || 'existing') as 'added' | 'removed' | 'edited' | 'existing',
      }));

      // Add removed layers from diff
      const removedLayers = currentMapData.diff.layer_diffs
        .filter((diff) => diff.status === 'removed')
        .filter((diff) => !currentLayersArray.some((layer) => layer.id === diff.layer_id))
        .map((diff) => ({
          id: diff.layer_id,
          name: diff.name,
          path: '',
          // geometry_type: null,
          type: 'removed',
          // feature_count: null,
          status: 'removed' as const,
        }));

      return [...layersWithStatus, ...removedLayers];
    }

    // If no diff, all layers are existing
    return currentLayersArray.map((l) => ({
      ...l,
      status: 'existing' as const,
    }));
  }, [currentMapData]);

  return (
    <Card className="absolute top-4 left-4 max-h-[60vh] overflow-auto py-2 rounded-sm border-0 gap-2 max-w-72 w-full">
      <CardHeader className="px-2">
        <CardTitle className="text-base flex justify-between items-center gap-2">
          <div className="flex items-center gap-2">
            <Tooltip>
              <TooltipTrigger>
                {readyState === ReadyState.OPEN && driftDbConnected ? (
                  <span className="text-green-300 inline-block">
                    <SignalHigh />
                  </span>
                ) : (
                  <span className="text-red-300 inline-block">
                    <SignalLow />
                  </span>
                )}
              </TooltipTrigger>
              <TooltipContent>
                <div className="text-sm flex space-x-2">
                  <div className={readyState === ReadyState.OPEN ? 'text-green-300' : 'text-red-300'}>
                    chat:{' '}
                    {readyState === ReadyState.OPEN ? (
                      <SignalHigh className="inline-block h-4 w-4" />
                    ) : (
                      <SignalLow className="inline-block h-4 w-4" />
                    )}
                  </div>
                  <div className={driftDbConnected ? 'text-green-300' : 'text-red-300'}>
                    cursors:{' '}
                    {driftDbConnected ? <SignalHigh className="inline-block h-4 w-4" /> : <SignalLow className="inline-block h-4 w-4" />}
                  </div>
                </div>
              </TooltipContent>
            </Tooltip>
            Map Layers
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="px-0">
        {processedLayers.length > 0 ? (
          <ul className="text-sm">
            {processedLayers.map((layerWithStatus) => {
              const { status, ...layerDetails } = layerWithStatus;

              // Check if this layer has an active action
              const hasActiveAction = activeActions.some((action) => action.layer_id === layerDetails.id);

              let liClassName = '';
              if (currentMapData.display_as_diff) {
                if (status === 'added') {
                  liClassName += ' bg-green-100 dark:bg-green-900 hover:bg-green-200 dark:hover:bg-green-800';
                } else if (status === 'removed') {
                  liClassName += ' bg-red-100 dark:bg-red-900 hover:bg-red-200 dark:hover:bg-red-800';
                } else if (status === 'edited') {
                  liClassName += ' bg-yellow-100 dark:bg-yellow-800 hover:bg-yellow-200 dark:hover:bg-yellow-700';
                } else {
                  // existing
                  liClassName += ' hover:bg-slate-100 dark:hover:bg-gray-600 dark:focus:bg-gray-600';
                }
              } else {
                liClassName += ' hover:bg-slate-100 dark:hover:bg-gray-600 dark:focus:bg-gray-600';
              }

              // Add pulse animation if there's an active action for this layer
              if (hasActiveAction) {
                liClassName += ' animate-pulse';
              }
              const num_highlighted = 0;

              return (
                <DropdownMenu key={layerDetails.id}>
                  <DropdownMenuTrigger asChild>
                    <li className={`${liClassName} flex items-center justify-between px-2 py-1 gap-2 cursor-pointer group`}>
                      <div className="flex items-center gap-2">
                        <span className="font-medium truncate" title={layerDetails.name}>
                          {layerDetails.name.length > 26 ? layerDetails.name.slice(0, 26) + '...' : layerDetails.name}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-slate-500 dark:text-gray-400">
                          {(() => {
                            const sridDisplay = layerDetails.metadata?.original_srid
                              ? `EPSG:${layerDetails.metadata.original_srid}`
                              : 'N/A';
                            if (layerDetails.type === 'raster') {
                              return sridDisplay;
                            }
                            // For vector layers: show SRID on hover, feature count + highlighted when not hovering
                            return (
                              <>
                                <span className="group-hover:hidden">
                                  {num_highlighted > 0 ? (
                                    <>
                                      <span className="text-gray-300 font-bold">{num_highlighted} /</span>{' '}
                                      {layerDetails.feature_count ?? 'N/A'}
                                    </>
                                  ) : (
                                    (layerDetails.feature_count ?? 'N/A')
                                  )}
                                </span>
                                <span className="hidden group-hover:inline">{sridDisplay}</span>
                              </>
                            );
                          })()}
                        </span>
                        <div className="w-4 h-4 flex-shrink-0">
                          <div className="group-hover:hidden">
                            <LayerLegendSymbol layerDetails={layerDetails} />
                          </div>
                          <div className="hidden group-hover:block">
                            <MoreHorizontal className="w-4 h-4" />
                          </div>
                        </div>
                      </div>
                    </li>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent>
                    <DropdownMenuItem
                      disabled={status === 'removed'}
                      onClick={() => {
                        if (status === 'removed') return;
                        if (layerDetails.bounds && layerDetails.bounds.length === 4 && mapRef.current) {
                          mapRef.current.fitBounds(
                            [
                              [layerDetails.bounds[0], layerDetails.bounds[1]],
                              [layerDetails.bounds[2], layerDetails.bounds[3]],
                            ],
                            { padding: 50, animate: true },
                          );
                          toast.success('Zoomed to layer');
                        } else {
                          toast.info('Layer bounds not available for zoom.');
                        }
                      }}
                    >
                      Zoom to layer
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => {
                        if (status === 'removed') return;

                        // Set the selected layer and show the attribute table
                        setSelectedLayer(layerDetails);
                        setShowAttributeTable(true);
                      }}
                    >
                      View attributes
                    </DropdownMenuItem>
                    <DropdownMenuSub>
                      <DropdownMenuSubTrigger disabled={status === 'removed'}>Export layer as</DropdownMenuSubTrigger>
                      <DropdownMenuPortal>
                        <DropdownMenuSubContent>
                          <DropdownMenuItem>Shapefile</DropdownMenuItem>
                          <DropdownMenuItem>GeoPackage</DropdownMenuItem>
                        </DropdownMenuSubContent>
                      </DropdownMenuPortal>
                    </DropdownMenuSub>
                    <DropdownMenuItem
                      onClick={() => {
                        if (status === 'removed') {
                          toast.info('Layer is already removed.'); // Or implement restore functionality
                          return;
                        }
                        fetch(`/api/maps/${currentMapData.map_id}/layer/${layerDetails.id}`, {
                          method: 'DELETE',
                          headers: { 'Content-Type': 'application/json' },
                        })
                          .then((response) => {
                            if (response.ok) {
                              toast.success(`Layer "${layerDetails.name}" deletion process started.`);
                              // Consider a state update mechanism instead of reload for better UX
                              window.location.reload();
                            } else {
                              response.json().then((err) => toast.error(`Failed to delete layer: ${err.detail || response.statusText}`));
                            }
                          })
                          .catch((err) => {
                            console.error('Error deleting layer:', err);
                            toast.error(`Error deleting layer: ${err.message}`);
                          });
                      }}
                    >
                      {status === 'removed' ? 'Layer marked as removed' : 'Delete layer'}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-slate-500 px-2">No layers to display.</p>
        )}

        {/* Upload Progress section */}
        {uploadingFiles && uploadingFiles.length > 0 && (
          <>
            <div className="flex items-center px-2 py-2">
              <div className="flex-1 h-px bg-gray-300 dark:bg-gray-600"></div>
              <span className="px-3 text-xs font-medium text-gray-600 dark:text-gray-400">UPLOADING</span>
              <div className="flex-1 h-px bg-gray-300 dark:bg-gray-600"></div>
            </div>
            <ul className="space-y-2 text-sm px-2">
              {uploadingFiles.map((uploadingFile) => (
                <li key={uploadingFile.id} className="border border-gray-200 dark:border-gray-700 rounded-lg p-2">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{uploadingFile.file.name}</span>
                    <span className="text-xs text-gray-500 dark:text-gray-400 flex-shrink-0">
                      {uploadingFile.status === 'uploading' && `${uploadingFile.progress}%`}
                      {uploadingFile.status === 'completed' && '✓'}
                      {uploadingFile.status === 'error' && '✗'}
                    </span>
                  </div>

                  {uploadingFile.status === 'uploading' && (
                    <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-1.5">
                      <div
                        className="bg-blue-600 h-1.5 rounded-full transition-all duration-300"
                        style={{ width: `${uploadingFile.progress}%` }}
                      />
                    </div>
                  )}

                  {uploadingFile.status === 'completed' && (
                    <div className="text-xs text-green-600 dark:text-green-400">Upload completed</div>
                  )}

                  {uploadingFile.status === 'error' && (
                    <div className="text-xs text-red-600 dark:text-red-400">{uploadingFile.error || 'Upload failed'}</div>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}

        {/* Sources section */}
        {project?.postgres_connections && project.postgres_connections.length > 0 && (
          <>
            <div className="flex items-center px-2 py-2">
              <div className="flex-1 h-px bg-gray-300 dark:bg-gray-600"></div>
              <span className="px-3 text-xs font-medium text-gray-600 dark:text-gray-400">DATABASES</span>
              <div className="flex-1 h-px bg-gray-300 dark:bg-gray-600"></div>
            </div>
            <ul className="text-sm">
              {project.postgres_connections.map((connection, index) =>
                connection.last_error_text ? (
                  <TooltipProvider key={index}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <li
                          className={`flex items-center justify-between px-2 py-1 gap-2 hover:bg-slate-100 dark:hover:bg-gray-600 cursor-pointer group`}
                          onClick={async () => {
                            try {
                              const response = await fetch(`/api/projects/${project.id}/postgis-connections/${connection.connection_id}`, {
                                method: 'DELETE',
                                headers: {
                                  'Content-Type': 'application/json',
                                },
                              });

                              if (response.ok) {
                                toast.success('Database connection deleted successfully');
                                updateProjectData(project.id);
                                updateMapData(currentMapData.map_id);
                              } else {
                                const errorData = await response.json().catch(() => ({
                                  detail: response.statusText,
                                }));
                                toast.error(`Failed to delete connection: ${errorData.detail || response.statusText}`);
                              }
                            } catch (error) {
                              toast.error(`Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
                            }
                          }}
                        >
                          <span className="font-medium truncate flex items-center gap-2 text-red-400">
                            <span className="text-red-400">⚠</span>
                            Connection Error
                          </span>
                          <div className="flex-shrink-0">
                            <div className="group-hover:hidden">
                              <span className="text-xs text-red-400">Error</span>
                            </div>
                            <div className="hidden group-hover:block w-4 h-4">
                              <svg className="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={2}
                                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                                />
                              </svg>
                            </div>
                          </div>
                        </li>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>{connection.last_error_text}</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                ) : (
                  <li
                    key={index}
                    className={`flex items-center justify-between px-2 py-1 gap-2 hover:bg-slate-100 dark:hover:bg-gray-600 cursor-pointer group ${connection.friendly_name === 'Loading...' ? 'animate-pulse' : ''}`}
                    onClick={() => navigate(`/postgis/${connection.connection_id}`)}
                  >
                    <span className="font-medium truncate flex items-center gap-2" title={connection.friendly_name}>
                      <Database className="h-4 w-4" />
                      {connection.friendly_name}
                    </span>
                    <div className="flex-shrink-0">
                      <div className="group-hover:hidden">
                        <span className="text-xs text-slate-500 dark:text-gray-400">{connection.table_count} tables</span>
                      </div>
                      <div className="hidden group-hover:block w-4 h-4">
                        <Info className="w-4 h-4" />
                      </div>
                    </div>
                  </li>
                ),
              )}
            </ul>
          </>
        )}
      </CardContent>
      <CardFooter className="flex justify-between items-center px-2">
        <div className="flex items-center gap-1">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="sm"
                  variant="ghost"
                  className="p-0.5 hover:cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-600"
                  disabled={zoomHistoryIndex <= 0}
                  onClick={() => {
                    if (zoomHistoryIndex > 0 && mapRef.current) {
                      const newIndex = zoomHistoryIndex - 1;
                      const targetBounds = zoomHistory[newIndex].bounds;
                      mapRef.current.fitBounds(
                        [
                          [targetBounds[0], targetBounds[1]],
                          [targetBounds[2], targetBounds[3]],
                        ],
                        { animate: true },
                      );
                      setZoomHistoryIndex(newIndex);
                    }
                  }}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>Previous location</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <span className="text-xs text-slate-500 dark:text-gray-400">Zoom</span>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="sm"
                  variant="ghost"
                  className="p-0.5 hover:cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-600"
                  disabled={zoomHistoryIndex >= zoomHistory.length - 1}
                  onClick={() => {
                    if (zoomHistoryIndex < zoomHistory.length - 1 && mapRef.current) {
                      const newIndex = zoomHistoryIndex + 1;
                      const targetBounds = zoomHistory[newIndex].bounds;
                      mapRef.current.fitBounds(
                        [
                          [targetBounds[0], targetBounds[1]],
                          [targetBounds[2], targetBounds[3]],
                        ],
                        { animate: true },
                      );
                      setZoomHistoryIndex(newIndex);
                    }
                  }}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>Next location</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
        <div className="flex items-center gap-1">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="sm"
                  variant="ghost"
                  className="p-0.5 hover:cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-600"
                  onClick={openDropzone}
                >
                  <Upload className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>Upload file</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="sm"
                  variant="ghost"
                  className="p-0.5 hover:cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-600"
                  onClick={() => setShowPostgisDialog(true)}
                >
                  <Database className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>Load PostGIS</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          {currentMapData.display_as_diff ? (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="p-0.5 hover:cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-600"
                    onClick={saveAndForkMap}
                    disabled={isSaving}
                  >
                    {isSaving ? <RotateCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p>{isSaving ? 'Saving...' : 'Save'}</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          ) : null}
        </div>

        {/* PostGIS Connection Dialog */}
        <Dialog
          open={showPostgisDialog}
          onOpenChange={(open) => {
            setShowPostgisDialog(open);
            if (!open) {
              setPostgisError(null);
            }
          }}
        >
          <DialogContent className="sm:max-w-[500px]">
            <DialogHeader>
              <DialogTitle>Add a PostGIS Database</DialogTitle>
              <DialogDescription>
                Your database connection details will be stored on the server. Read-only access is best.{' '}
                <a
                  href="https://docs.mundi.ai/guides/connecting-to-postgis/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-300 hover:text-blue-400 underline"
                >
                  Read our tutorial on PostGIS here.
                </a>
              </DialogDescription>
            </DialogHeader>

            <div className="grid gap-4 py-4">
              {/* Connection Method Toggle */}
              <div className="flex space-x-2">
                {demoConfig.available && (
                  <Button
                    type="button"
                    variant={connectionMethod === 'demo' ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setConnectionMethod('demo')}
                    className="flex-1 hover:cursor-pointer"
                  >
                    Demo Database
                  </Button>
                )}
                <Button
                  type="button"
                  variant={connectionMethod === 'uri' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setConnectionMethod('uri')}
                  className="flex-1 hover:cursor-pointer"
                >
                  Database URI
                </Button>
                <Button
                  type="button"
                  variant={connectionMethod === 'fields' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setConnectionMethod('fields')}
                  className="flex-1 hover:cursor-pointer"
                >
                  Connection Details
                </Button>
              </div>

              {connectionMethod === 'demo' ? (
                <div className="space-y-2">
                  <p className="text-sm text-gray-300">
                    {demoConfig.description} We provide it as a demo to preview Mundi's capabilities, especially for users with sensitive
                    PostGIS databases who would rather self-host or use an on-premise deployment.
                  </p>
                </div>
              ) : connectionMethod === 'uri' ? (
                <div className="space-y-2">
                  <label htmlFor="uri" className="text-sm font-medium">
                    Database URI
                  </label>
                  <Input
                    id="uri"
                    placeholder="postgresql://username:password@host:port/database"
                    value={postgisForm.uri}
                    onChange={(e) => {
                      setPostgisForm((prev) => ({
                        ...prev,
                        uri: e.target.value,
                      }));
                      setPostgisError(null);
                    }}
                  />
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <label htmlFor="host" className="text-sm font-medium">
                        Host
                      </label>
                      <Input
                        id="host"
                        placeholder="localhost"
                        value={postgisForm.host}
                        onChange={(e) => {
                          setPostgisForm((prev) => ({
                            ...prev,
                            host: e.target.value,
                          }));
                          setPostgisError(null);
                        }}
                      />
                    </div>
                    <div className="space-y-2">
                      <label htmlFor="port" className="text-sm font-medium">
                        Port
                      </label>
                      <Input
                        id="port"
                        placeholder="5432"
                        value={postgisForm.port}
                        onChange={(e) => {
                          setPostgisForm((prev) => ({
                            ...prev,
                            port: e.target.value,
                          }));
                          setPostgisError(null);
                        }}
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <label htmlFor="database" className="text-sm font-medium">
                        Database
                      </label>
                      <Input
                        id="database"
                        placeholder="postgres"
                        value={postgisForm.database}
                        onChange={(e) => {
                          setPostgisForm((prev) => ({
                            ...prev,
                            database: e.target.value,
                          }));
                          setPostgisError(null);
                        }}
                      />
                    </div>
                    <div className="space-y-2">
                      <label htmlFor="schema" className="text-sm font-medium">
                        Schema
                      </label>
                      <Input
                        id="schema"
                        placeholder="public"
                        value={postgisForm.schema}
                        onChange={(e) => {
                          setPostgisForm((prev) => ({
                            ...prev,
                            schema: e.target.value,
                          }));
                          setPostgisError(null);
                        }}
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <label htmlFor="username" className="text-sm font-medium">
                        Username
                      </label>
                      <Input
                        id="username"
                        placeholder="postgres"
                        value={postgisForm.username}
                        onChange={(e) => {
                          setPostgisForm((prev) => ({
                            ...prev,
                            username: e.target.value,
                          }));
                          setPostgisError(null);
                        }}
                      />
                    </div>
                    <div className="space-y-2">
                      <label htmlFor="password" className="text-sm font-medium">
                        Password
                      </label>
                      <Input
                        id="password"
                        type="password"
                        placeholder="password"
                        value={postgisForm.password}
                        onChange={(e) => {
                          setPostgisForm((prev) => ({
                            ...prev,
                            password: e.target.value,
                          }));
                          setPostgisError(null);
                        }}
                      />
                    </div>
                  </div>
                </>
              )}

              {/* Error Callout */}
              {postgisError && (
                <div className="flex items-start gap-3 p-3 bg-red-50 border border-red-200 rounded-md">
                  <AlertTriangle className="h-5 w-5 text-red-500 mt-0.5 flex-shrink-0" />
                  <div className="text-sm text-red-700">
                    {postgisError}{' '}
                    <a
                      href="https://docs.mundi.ai/guides/connecting-to-postgis/#debugging-common-problems"
                      target="_blank"
                      className="text-blue-500 hover:text-blue-600 underline"
                      rel="noopener"
                    >
                      Refer to our documentation on PostGIS errors.
                    </a>
                  </div>
                </div>
              )}
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setShowPostgisDialog(false)} className="hover:cursor-pointer">
                Cancel
              </Button>
              <Button type="button" onClick={handlePostgisConnect} className="hover:cursor-pointer" disabled={postgisLoading}>
                {postgisLoading ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Adding Connection...
                  </>
                ) : (
                  'Add Connection'
                )}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardFooter>
    </Card>
  );
};

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
}: MapLibreMapProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const globeControlRef = useRef<GlobeControl | null>(null);
  const exportPDFControlRef = useRef<ExportPDFControl | null>(null);
  const [errors, setErrors] = useState<ErrorEntry[]>([]);
  const [hasZoomed, setHasZoomed] = useState(false);
  const [layerSymbols, setLayerSymbols] = useState<{
    [layerId: string]: JSX.Element;
  }>({});
  const [zoomHistory, setZoomHistory] = useState<Array<{ bounds: [number, number, number, number] }>>([]);
  const [zoomHistoryIndex, setZoomHistoryIndex] = useState(-1);
  const [currentBasemap, setCurrentBasemap] = useState<string>('');
  const [availableBasemaps, setAvailableBasemaps] = useState<string[]>([]);
  const [demoConfig, setDemoConfig] = useState<{
    available: boolean;
    description: string;
  }>({ available: false, description: '' });

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

  // Separate effect for map initialization (only runs once)
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

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

      newMap.on('load', () => {
        // Add navigation controls
        newMap.addControl(new NavigationControl(), 'top-right');
        newMap.addControl(new ScaleControl(), 'bottom-left');

        // Add export PDF control below the navigation controls
        const exportPDFControl = new ExportPDFControl(mapId);
        exportPDFControlRef.current = exportPDFControl;
        newMap.addControl(exportPDFControl, 'top-right');

        // Load cursor image early (doesn't need to wait for style)
        const cursorImage = new Image();
        cursorImage.onload = () => {
          if (newMap.hasImage('remote-cursor')) {
            newMap.removeImage('remote-cursor');
          }
          newMap.addImage('remote-cursor', cursorImage);
        };
        cursorImage.src =
          'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIAAAAyCAYAAAAeP4ixAAAACXBIWXMAAAsTAAALEwEAmpwYAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAIRSURBVHgB7dnNsdowFAXgQ5INO9OBt9m5BKUDOsAl0AHuIO4AUgF0YKgAOrCpwLDL7kbnPUHAETEY8yy98TejsWf8fnQsc3UBoNfr9WrkZoTwnMxmM8EnCCP0GcLIyXw+P4WJ4CG5tFwuZTQalfAwjFRtt1sJgoCrM4FHxCbPcwnDkGGm8ITcchFmBg/I//gURur4EkbuUZalRFHEMD/hKLkXw4zHY4aZw0HyqMlkwjBbPQI4RJowLQ3DhHCENOVafybPcCmMPMuVMNIGFzpnaUvXnbO0qcvOWdrWVecsr9BFfyav0iTMAM3xf+JZh8PhPIqieDvu93vsdjusVqu75/gNH2iz2SBN0/OEzTjoS6dRmOPeHHf4APIodsH8PT0U3jfB1prHL3gR3nXzaJzp8oo4jnmq8Pfud672xcpRlWUZV4SbnzOtvDXExcYW65Fx4lVKqdN1J1hDmFZjbH4m5qRvrEoGR1xNbrFY2PolPj4lA95YFQUHXIXA7Q42mU6nTq/K24SSJKl7TxFwpVh6q8zurdCCr2guGQwG0EEKff4D7+XU5rf2fTgcRvpxurpwPB6xXq9DffoLHXrkGyvFSlbFVTIV7p6/4QxrKTaPZgqPKFsp5qqYaufUZ111StuqsKrpawk8Yi3FbGngWNtS559SzBUym2MOz6R8gfNjIBOAm2IMD3H3591nAIVez21/ACUSSP4DF2G8AAAAAElFTkSuQmCC';

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
  }, [addError, loadLegendSymbols, mapId]); // Only run once on mount

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
    if (!mapId || !jwt) return null;

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

          // Handle bounds zooming for any ephemeral action that includes bounds
          if (action.bounds && action.bounds.length === 4 && mapRef.current) {
            // Save current bounds to history before zooming
            const currentBounds = mapRef.current.getBounds();
            const currentBoundsArray: [number, number, number, number] = [
              currentBounds.getWest(),
              currentBounds.getSouth(),
              currentBounds.getEast(),
              currentBounds.getNorth(),
            ];

            // Add current bounds to history
            setZoomHistory((prev) => {
              const newHistory = [...prev.slice(0, zoomHistoryIndex + 1), { bounds: currentBoundsArray }];
              return newHistory;
            });

            // Update index to point to the newly added current position
            setZoomHistoryIndex((prev) => prev + 1);

            // Zoom to new bounds
            const [west, south, east, north] = action.bounds;
            mapRef.current.fitBounds(
              [
                [west, south],
                [east, north],
              ],
              { animate: true, padding: 50 },
            );

            // Add the new bounds to history as well
            setZoomHistory((prev) => {
              const newHistory = [...prev, { bounds: action.bounds as [number, number, number, number] }];
              return newHistory;
            });

            // Update index to point to the new bounds
            setZoomHistoryIndex((prev) => prev + 1);
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
          />
        )}
        {/* Changelog */}
        {/* Apply flex flex-col justify-end to CommandList to anchor items to the bottom */}
        <Command className="z-30 absolute bottom-4 left-4 max-h-[18vh] hover:max-h-[70vh] transition-all duration-300 ring ring-black hover:ring-white max-w-72 overflow-auto py-2 rounded-sm bg-white dark:bg-gray-800 shadow-md">
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
        <div className="z-30 max-h-screen h-full w-80 bg-white dark:bg-gray-800 shadow-md flex flex-col text-sm">
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
                  const textParts = messageJson.content
                    .filter((part) => part.type === 'text')
                    .map((part) => part.text)
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
              const hasImages = Array.isArray(messageJson.content) && messageJson.content.some((part) => part.type === 'image_url');

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
                    messageJson.content
                      .filter((part) => part.type === 'image_url')
                      .map((part, imgIndex) => (
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
