// Copyright Bunting Labs, Inc. 2025
import { useEffect, useMemo, useRef, useState } from 'react';
import { Map, NavigationControl, ScaleControl, MapOptions } from 'maplibre-gl';
import Session from "supertokens-auth-react/recipe/session";
import { useConnectionStatus, usePresence } from 'driftdb-react';
import useWebSocket from 'react-use-websocket';
import React from 'react';

import legendSymbol, { RenderElement } from "legend-symbol-ts";

import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Upload, CheckCircleFill, XCircleFill, Download, Save } from 'react-bootstrap-icons';
import { ChevronDown, MessagesSquare } from 'lucide-react';

import { toast } from "sonner";
import AttributeTable from "@/components/AttributeTable";
import DatabaseDetailsDialog from "@/components/DatabaseDetailsDialog";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import { MapData, MapLayer, PointerPosition, PresenceData, EphemeralAction, MapProject, PostgresConnectionDetails } from '../lib/types';
import { useNavigate } from 'react-router-dom';

import type { ChatCompletionMessageParam, ChatCompletionUserMessageParam, ChatCompletionMessageToolCall } from "openai/resources/chat/completions";
import { Activity, Brain, Database, Send } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';


// Define the type for chat completion messages from the database
interface ChatCompletionMessageRow {
  id: number;
  map_id: string;
  sender_id: string;
  message_json: ChatCompletionMessageParam;
  created_at: string;
}

// Import styles in the parent component

interface ErrorEntry {
  id: string;
  message: string;
  timestamp: Date;
  shouldOverrideMessages: boolean;
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
}
interface LayerWithStatus extends MapLayer {
  status: 'added' | 'removed' | 'edited' | 'existing';
}

interface LayerListProps {
  project: MapProject;
  currentMapData: MapData;
  mapRef: React.RefObject<Map | null>;
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
}) => {
  const [showPostgisDialog, setShowPostgisDialog] = useState(false);

  // Component to render legend symbol for a layer
  const LayerLegendSymbol = ({ layerDetails }: { layerDetails: MapLayer }) => {
    // Return cached symbol if available, otherwise null
    return layerSymbols[layerDetails.id] || null;
  };
  const [showDatabaseDetails, setShowDatabaseDetails] = useState(false);
  const [selectedDatabase, setSelectedDatabase] = useState<{
    connection: PostgresConnectionDetails;
    projectId: string;
  } | null>(null);
  const [connectionMethod, setConnectionMethod] = useState<'uri' | 'fields'>('uri');
  const [postgisForm, setPostgisForm] = useState({
    uri: '',
    host: '',
    port: '5432',
    database: '',
    username: '',
    password: '',
    schema: 'public'
  });

  const handleDatabaseClick = (connection: PostgresConnectionDetails, projectId: string) => {
    setSelectedDatabase({ connection, projectId });
    setShowDatabaseDetails(true);
  };

  const handlePostgisConnect = async () => {
    if (!currentMapData?.project_id) {
      toast.error('No project ID available');
      return;
    }

    let connectionUri = '';
    if (connectionMethod === 'uri') {
      connectionUri = postgisForm.uri;
    } else {
      // Build URI from form fields
      connectionUri = `postgresql://${postgisForm.username}:${postgisForm.password}@${postgisForm.host}:${postgisForm.port}/${postgisForm.database}`;
    }

    if (!connectionUri.trim()) {
      toast.error('Please provide connection details');
      return;
    }

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
          schema: 'public'
        });

        // Refresh immediately to show "Loading into AI..." in the database list
        updateProjectData(currentMapData.project_id);
        updateMapData(currentMapData.map_id);

        // Poll for updated connection details and refresh when AI naming is complete
        const pollForUpdatedConnection = async () => {
          let attempts = 0;
          const maxAttempts = 48; // 2 minutes max (48 * 2.5 seconds = 120 seconds)

          const pollInterval = setInterval(async () => {
            attempts++;

            try {
              // Fetch current project data to check connection names
              const response = await fetch(`/api/projects/${currentMapData.project_id}`);
              if (response.ok) {
                const projectData = await response.json();

                // Check if any connections no longer have "Loading..." as the name
                const hasUpdatedNames = projectData.postgres_connections?.some(
                  (conn: PostgresConnectionDetails) => conn.friendly_name && conn.friendly_name !== "Loading..."
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
          }, 2500); // Check every 2.5 seconds
        };

        pollForUpdatedConnection();
      } else {
        const errorData = await response.json().catch(() => ({ detail: response.statusText }));
        toast.error(`Failed to save connection: ${errorData.detail || response.statusText}`);
      }
    } catch (error) {
      toast.error(`Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  };

  const processedLayers = useMemo<LayerWithStatus[]>(() => {
    const currentLayersArray = currentMapData.layers || [];

    // Use diff from currentMapData to determine layer statuses
    if (currentMapData.diff && currentMapData.diff.layer_diffs) {
      const layerDiffMap = new globalThis.Map<string, string>(
        currentMapData.diff.layer_diffs.map(diff => [diff.layer_id, diff.status])
      );

      // Start with current layers
      const layersWithStatus = currentLayersArray.map(layer => ({
        ...layer,
        status: (layerDiffMap.get(layer.id) || 'existing') as 'added' | 'removed' | 'edited' | 'existing'
      }));

      // Add removed layers from diff
      const removedLayers = currentMapData.diff.layer_diffs
        .filter(diff => diff.status === 'removed')
        .filter(diff => !currentLayersArray.some(layer => layer.id === diff.layer_id))
        .map(diff => ({
          id: diff.layer_id,
          name: diff.name,
          path: '',
          // geometry_type: null,
          type: 'removed',
          // feature_count: null,
          status: 'removed' as const
        }));

      return [...layersWithStatus, ...removedLayers];
    }

    // If no diff, all layers are existing
    return currentLayersArray.map(l => ({ ...l, status: 'existing' as const }));
  }, [currentMapData]);

  return (
    <Card className="absolute top-4 left-4 max-h-[60vh] overflow-auto py-2 rounded-sm border-0 gap-2 max-w-72 w-full">
      <CardHeader className="px-2">
        <CardTitle className="text-base flex justify-between items-center gap-2">
          <div className="flex items-center gap-2">
            <SidebarTrigger />

            Map Layers
          </div>
          {readyState === 1 && driftDbConnected ?
            <span className="text-green-500 inline-block"><CheckCircleFill /></span> :
            <span className="text-red-500 inline-block"><XCircleFill /></span>}
        </CardTitle>
      </CardHeader>
      <CardContent className="px-0">
        {processedLayers.length > 0 ? (
          <ul className="space-y-1 text-sm">
            {processedLayers.map(layerWithStatus => {
              const { status, ...layerDetails } = layerWithStatus;

              // Check if this layer has an active action
              const hasActiveAction = activeActions.some(action => action.layer_id === layerDetails.id);

              let liClassName = '';
              if (currentMapData.display_as_diff) {
                if (status === 'added') {
                  liClassName += ' bg-green-100 dark:bg-green-900 hover:bg-green-200 dark:hover:bg-green-800';
                } else if (status === 'removed') {
                  liClassName += ' bg-red-100 dark:bg-red-900 hover:bg-red-200 dark:hover:bg-red-800';
                } else if (status === 'edited') {
                  liClassName += ' bg-yellow-100 dark:bg-yellow-800 hover:bg-yellow-200 dark:hover:bg-yellow-700';
                } else { // existing
                  liClassName += ' hover:bg-slate-100 dark:hover:bg-gray-600 dark:focus:bg-gray-600';
                }
              } else {
                liClassName += ' hover:bg-slate-100 dark:hover:bg-gray-600 dark:focus:bg-gray-600';
              }

              // Add pulse animation if there's an active action for this layer
              if (hasActiveAction) {
                liClassName += ' animate-pulse';
              }

              return (
                <ContextMenu key={layerDetails.id}>
                  <ContextMenuTrigger>
                    <li className={`${liClassName} flex items-center justify-between px-2 py-1 gap-2`}>
                      <div className="flex items-center gap-2">
                        <span className="font-medium truncate" title={layerDetails.name}>
                          {layerDetails.name}
                        </span>
                        <span className="text-xs text-slate-500 dark:text-gray-400">
                          {layerDetails.feature_count ?? 'N/A'}
                        </span>
                      </div>
                      <div className="w-4 h-4 flex-shrink-0">
                        <LayerLegendSymbol layerDetails={layerDetails} />
                      </div>
                    </li>
                  </ContextMenuTrigger>
                  <ContextMenuContent>
                    <ContextMenuItem
                      disabled={status === 'removed'}
                      onClick={() => {
                        if (status === 'removed') return;
                        if (layerDetails.bounds && layerDetails.bounds.length === 4 && mapRef.current) {
                          mapRef.current.fitBounds([
                            [layerDetails.bounds[0], layerDetails.bounds[1]],
                            [layerDetails.bounds[2], layerDetails.bounds[3]]
                          ], { padding: 50, animate: true });
                          toast.success('Zoomed to layer');
                        } else {
                          toast.info('Layer bounds not available for zoom.');
                        }
                      }}
                    >
                      Zoom to layer
                    </ContextMenuItem>
                    <ContextMenuItem
                      onClick={() => {
                        if (status === 'removed') return;

                        // Set the selected layer and show the attribute table
                        setSelectedLayer(layerDetails);
                        setShowAttributeTable(true);
                      }}
                    >
                      View attributes
                    </ContextMenuItem>
                    <ContextMenuSub>
                      <ContextMenuSubTrigger disabled={status === 'removed'}>Export layer as</ContextMenuSubTrigger>
                      <ContextMenuSubContent>
                        <ContextMenuItem>Shapefile</ContextMenuItem>
                        <ContextMenuItem>GeoPackage</ContextMenuItem>
                      </ContextMenuSubContent>
                    </ContextMenuSub>
                    <ContextMenuItem
                      onClick={() => {
                        if (status === 'removed') {
                          toast.info('Layer is already removed.'); // Or implement restore functionality
                          return;
                        }
                        fetch(`/api/maps/${currentMapData.map_id}/layer/${layerDetails.id}`, {
                          method: 'DELETE',
                          headers: { 'Content-Type': 'application/json' },
                        })
                          .then(response => {
                            if (response.ok) {
                              toast.success(`Layer "${layerDetails.name}" deletion process started.`);
                              // Consider a state update mechanism instead of reload for better UX
                              window.location.reload();
                            } else {
                              response.json().then(err => toast.error(`Failed to delete layer: ${err.detail || response.statusText}`));
                            }
                          })
                          .catch(err => {
                            console.error('Error deleting layer:', err);
                            toast.error(`Error deleting layer: ${err.message}`);
                          });
                      }}
                    >
                      {status === 'removed' ? 'Layer marked as removed' : 'Delete layer'}
                    </ContextMenuItem>
                  </ContextMenuContent>
                </ContextMenu>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-slate-500 px-2">No layers to display.</p>
        )}
        {/* Sources section */}
        {project?.postgres_connections && project.postgres_connections.length > 0 && (
          <>
            <div className="flex items-center px-2 py-2">
              <div className="flex-1 h-px bg-gray-300 dark:bg-gray-600"></div>
              <span className="px-3 text-xs font-medium text-gray-600 dark:text-gray-400">DATABASES</span>
              <div className="flex-1 h-px bg-gray-300 dark:bg-gray-600"></div>
            </div>
            <ul className="space-y-1 text-sm">
              {project.postgres_connections.map((connection, index) => (
                <li
                  key={index}
                  className={`flex items-center justify-between px-2 py-1 gap-2 hover:bg-slate-100 dark:hover:bg-gray-600 cursor-pointer ${connection.friendly_name === 'Loading...' ? 'animate-pulse' : ''}`}
                  onClick={() => handleDatabaseClick(connection, project.id)}
                >
                  <span className="font-medium truncate flex items-center gap-2" title={connection.friendly_name}>
                    <Database className="h-4 w-4" />
                    {connection.friendly_name}
                  </span>
                  <span className="text-xs text-slate-500 dark:text-gray-400">
                    {connection.table_count} tables
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
      <CardFooter className="p-2 flex justify-between space-x-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="default" className="hover:cursor-pointer">
              <Upload /> Add Data <ChevronDown className="ml-1 h-3 w-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuItem onClick={openDropzone} className="cursor-pointer">
              <Upload className="mr-2 h-4 w-4" />
              Upload file
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setShowPostgisDialog(true)} className="cursor-pointer">
              <Database className="mr-2 h-4 w-4" />
              Load PostGIS
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        {/* PostGIS Connection Dialog */}
        <Dialog open={showPostgisDialog} onOpenChange={setShowPostgisDialog}>
          <DialogContent className="sm:max-w-[500px]">
            <DialogHeader>
              <DialogTitle>Add a PostGIS Database</DialogTitle>
              <DialogDescription>
                Your database connection details will be stored on the server. Read-only access is best.{" "}
                <a
                  href="https://docs.mundi.ai/en/getting-started/adding-postgis-database/"
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

              {connectionMethod === 'uri' ? (
                <div className="space-y-2">
                  <label htmlFor="uri" className="text-sm font-medium">
                    Database URI
                  </label>
                  <Input
                    id="uri"
                    placeholder="postgresql://username:password@host:port/database"
                    value={postgisForm.uri}
                    onChange={(e) => setPostgisForm(prev => ({ ...prev, uri: e.target.value }))}
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
                        onChange={(e) => setPostgisForm(prev => ({ ...prev, host: e.target.value }))}
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
                        onChange={(e) => setPostgisForm(prev => ({ ...prev, port: e.target.value }))}
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
                        onChange={(e) => setPostgisForm(prev => ({ ...prev, database: e.target.value }))}
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
                        onChange={(e) => setPostgisForm(prev => ({ ...prev, schema: e.target.value }))}
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
                        onChange={(e) => setPostgisForm(prev => ({ ...prev, username: e.target.value }))}
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
                        onChange={(e) => setPostgisForm(prev => ({ ...prev, password: e.target.value }))}
                      />
                    </div>
                  </div>
                </>
              )}
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setShowPostgisDialog(false)} className="hover:cursor-pointer">
                Cancel
              </Button>
              <Button type="button" onClick={handlePostgisConnect} className="hover:cursor-pointer">
                Add Connection
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Database Details Dialog */}
        <DatabaseDetailsDialog
          isOpen={showDatabaseDetails && selectedDatabase !== null}
          onClose={() => setShowDatabaseDetails(false)}
          databaseName={selectedDatabase?.connection.friendly_name || ''}
          connectionId={selectedDatabase?.connection.connection_id || ''}
          projectId={selectedDatabase?.projectId || ''}
        />

        {currentMapData.display_as_diff ?
          <Button size="sm" variant="secondary" onClick={saveAndForkMap} className="hover:cursor-pointer" disabled={isSaving}>
            {isSaving ? (
              <>
                <Save className="animate-pulse" /> Saving
              </>
            ) : (
              <>
                <Save /> Save
              </>
            )}
          </Button>
          : null}
        {/* <Button size="sm" variant="secondary" className="hover:cursor-pointer"><FileEarmarkZipFill /> Export</Button> */}
      </CardFooter>
    </Card>
  );
};


export default function MapLibreMap({ mapId, width = '100%', height = '500px', className = '', project, mapData, openDropzone, updateMapData, updateProjectData }: MapLibreMapProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const [errors, setErrors] = useState<ErrorEntry[]>([]);
  const [hasZoomed, setHasZoomed] = useState(false);
  const [layerSymbols, setLayerSymbols] = useState<{ [layerId: string]: JSX.Element }>({});



  // Helper function to add a new error
  const addError = (message: string, shouldOverrideMessages: boolean = false) => {
    const newError: ErrorEntry = {
      id: Date.now().toString() + Math.random().toString(36).substr(2, 9),
      message,
      timestamp: new Date(),
      shouldOverrideMessages,
    };
    setErrors(prev => [...prev, newError]);

    // Auto-dismiss after 5 seconds
    setTimeout(() => {
      setErrors(prev => prev.filter(error => error.id !== newError.id));
    }, 5000);
  };

  // Helper function to dismiss a specific error
  const dismissError = (errorId: string) => {
    setErrors(prev => prev.filter(error => error.id !== errorId));
  };
  const [loading, setLoading] = useState(true);
  const [pointerPosition, setPointerPosition] = useState<PointerPosition | null>(null);
  const otherClientPositions = usePresence<PointerPosition | null>("cursors", pointerPosition);
  const navigate = useNavigate();
  const [showAttributeTable, setShowAttributeTable] = useState(false);
  const [selectedLayer, setSelectedLayer] = useState<MapLayer | null>(null);
  const [activeActions, setActiveActions] = useState<EphemeralAction[]>([]);

  const [isSaving, setIsSaving] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);

  // Function to get the appropriate icon for an action
  const getActionIcon = (action: string) => {
    if (action.includes("thinking")) {
      return <Brain className="animate-pulse w-4 h-4 mr-2" />;
    } else if (action.includes("Downloading data from OpenStreetMap")) {
      return <Download className="animate-pulse w-4 h-4 mr-2" />;
    } else if (action.includes("SQL")) {
      return <Database className="animate-pulse w-4 h-4 mr-2" />;
    } else if (action.includes("Sending message")) {
      return <Send className="animate-pulse w-4 h-4 mr-2" />;
    } else {
      return <Activity className="w-4 h-4 mr-2 animate-pulse" />;
    }
  };

  // State for changelog entries
  // State for changelog entries from map data
  const [changelog, setChangelog] = useState<Array<{
    summary: string;
    timestamp: string;
    mapState: string;
  }>>([]);
  const [messages, setMessages] = useState<ChatCompletionMessageRow[]>([]);
  const [showMessages, setShowMessages] = useState(true);
  // Track the number of tool responses received from messages
  const [toolResponseCount, setToolResponseCount] = useState(0);

  useEffect(() => {
    if (updateMapData) {
      updateMapData(mapId);
    }
  }, [toolResponseCount, mapId, updateMapData]);

  // Process changelog data when mapData changes
  useEffect(() => {
    if (mapData?.changelog) {
      const formattedChangelog = mapData.changelog.map(entry => ({
        summary: entry.message,
        timestamp: new Date(entry.last_edited).toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit'
        }),
        mapState: entry.map_state
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
  const generateRandomPointsInBounds = (bounds: number[], count: number = 3) => {
    const [minLng, minLat, maxLng, maxLat] = bounds;
    const points = [];

    for (let i = 0; i < count; i++) {
      points.push({
        lng: minLng + Math.random() * (maxLng - minLng),
        lat: minLat + Math.random() * (maxLat - minLat)
      });
    }

    return points;
  };

  // Quadratic Bezier curve interpolation from p0 to p2 through p1
  const bezierInterpolate = (
    p0: { lng: number; lat: number },
    p1: { lng: number; lat: number },
    p2: { lng: number; lat: number },
    t: number
  ) => {
    const invT = 1 - t;
    return {
      lng: invT * invT * p0.lng + 2 * invT * t * p1.lng + t * t * p2.lng,
      lat: invT * invT * p0.lat + 2 * invT * t * p1.lat + t * t * p2.lat
    };
  };

  // Update Kue's target points when active actions change
  useEffect(() => {
    const activeLayerActions = activeActions.filter(action =>
      action.status === 'active' && action.layer_id
    );

    // Get current action IDs
    const currentActionIds = new Set(activeLayerActions.map(action => action.action_id));

    // Remove state for actions that are no longer active
    setKuePositions(prev => {
      const filtered = Object.fromEntries(
        Object.entries(prev).filter(([actionId]) => currentActionIds.has(actionId))
      );
      return filtered;
    });
    setKueTargetPoints(prev => {
      const filtered = Object.fromEntries(
        Object.entries(prev).filter(([actionId]) => currentActionIds.has(actionId))
      );
      return filtered;
    });

    // Add state for new actions
    if (mapData?.layers) {
      activeLayerActions.forEach(action => {
        const layer = mapData.layers.find(l => l.id === action.layer_id);
        if (layer?.bounds && layer.bounds.length >= 4) {
          const actionId = action.action_id;

          // Only initialize if not already present
          setKueTargetPoints(prev => {
            if (prev[actionId]) return prev;
            const newTargetPoints = generateRandomPointsInBounds(layer.bounds!);
            return { ...prev, [actionId]: newTargetPoints };
          });

          setKuePositions(prev => {
            if (prev[actionId]) return prev;
            const newTargetPoints = generateRandomPointsInBounds(layer.bounds!);
            return { ...prev, [actionId]: newTargetPoints[0] };
          });
        }
      });
    }
  }, [activeActions, mapData]);

  // Animate Kue's positions based on timestamp
  useEffect(() => {
    const activeActionIds = Object.keys(kueTargetPoints);
    if (activeActionIds.length === 0) return;

    const interval = setInterval(() => {
      const now = Date.now();

      activeActionIds.forEach(actionId => {
        const targetPoints = kueTargetPoints[actionId];

        if (targetPoints && targetPoints.length >= 2) {
          // Calculate progress based on timestamp modulo curve duration
          const progress = (now % KUE_CURVE_DURATION_MS) / KUE_CURVE_DURATION_MS;

          // Check if we've started a new curve cycle
          const currentCycle = Math.floor(now / KUE_CURVE_DURATION_MS);
          const lastCycle = Math.floor((now - UPDATE_KUE_POINTER_MSEC) / KUE_CURVE_DURATION_MS);

          if (currentCycle !== lastCycle) {
            // Generate new random points for the new curve
            const layer = mapData?.layers?.find(l =>
              activeActions.find(a => a.action_id === actionId)?.layer_id === l.id
            );
            if (layer?.bounds) {
              const newTargetPoints = generateRandomPointsInBounds(layer.bounds);
              setKueTargetPoints(prev => ({
                ...prev,
                [actionId]: newTargetPoints
              }));
              return; // Skip position update this frame to use new points next frame
            }
          }

          const startPoint = targetPoints[0];
          const middlePoint = targetPoints[1];
          const endPoint = targetPoints[2];

          const interpolatedPosition = bezierInterpolate(startPoint, middlePoint, endPoint, progress);

          setKuePositions(prev => ({
            ...prev,
            [actionId]: interpolatedPosition
          }));
        }
      });
    }, UPDATE_KUE_POINTER_MSEC);

    return () => clearInterval(interval);
  }, [kueTargetPoints, activeActions, mapData]);

  // Generate GeoJSON from pointer positions
  const pointsGeoJSON = useMemo(() => {
    const features: GeoJSON.Feature[] = [];

    // Add real user pointer positions
    Object.entries(otherClientPositions)
      .filter(([, data]) => data !== null && data.value !== null && "lng" in data.value && "lat" in data.value)
      .forEach(([id, data]) => {
        const presenceData = data as unknown as PresenceData;
        features.push({
          type: 'Feature' as const,
          geometry: {
            type: 'Point' as const,
            coordinates: [presenceData.value.lng, presenceData.value.lat]
          },
          properties: { user: id, abbrev: id.substring(0, 6), color: '#' + id.substring(0, 6) }
        });
      });

    // Add Kue's animated positions
    Object.entries(kuePositions).forEach(([actionId, position]) => {
      features.push({
        type: 'Feature' as const,
        geometry: {
          type: 'Point' as const,
          coordinates: [position.lng, position.lat]
        },
        properties: { user: 'Kue', abbrev: 'Kue', color: '#ff69b4', actionId }
      });
    });

    return {
      type: 'FeatureCollection' as const,
      features
    };
  }, [otherClientPositions, kuePositions]);

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
          layers: []
        }, // Start with empty style so map loads
        attributionControl: {
          compact: false
        }
      };

      const newMap = new Map(mapOptions);
      mapRef.current = newMap;

      newMap.on('load', () => {
        // Add navigation controls
        newMap.addControl(new NavigationControl());
        newMap.addControl(new ScaleControl());

        // Load cursor image early (doesn't need to wait for style)
        const cursorImage = new Image();
        cursorImage.onload = () => {
          if (newMap.hasImage('remote-cursor')) {
            newMap.removeImage('remote-cursor');
          }
          newMap.addImage('remote-cursor', cursorImage);
        };
        cursorImage.src = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIAAAAyCAYAAAAeP4ixAAAACXBIWXMAAAsTAAALEwEAmpwYAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAIRSURBVHgB7dnNsdowFAXgQ5INO9OBt9m5BKUDOsAl0AHuIO4AUgF0YKgAOrCpwLDL7kbnPUHAETEY8yy98TejsWf8fnQsc3UBoNfr9WrkZoTwnMxmM8EnCCP0GcLIyXw+P4WJ4CG5tFwuZTQalfAwjFRtt1sJgoCrM4FHxCbPcwnDkGGm8ITcchFmBg/I//gURur4EkbuUZalRFHEMD/hKLkXw4zHY4aZw0HyqMlkwjBbPQI4RJowLQ3DhHCENOVafybPcCmMPMuVMNIGFzpnaUvXnbO0qcvOWdrWVecsr9BFfyav0iTMAM3xf+JZh8PhPIqieDvu93vsdjusVqu75/gNH2iz2SBN0/OEzTjoS6dRmOPeHHf4APIodsH8PT0U3jfB1prHL3gR3nXzaJzp8oo4jnmq8Pfud672xcpRlWUZV4SbnzOtvDXExcYW65Fx4lVKqdN1J1hDmFZjbH4m5qRvrEoGR1xNbrFY2PolPj4lA95YFQUHXIXA7Q42mU6nTq/K24SSJKl7TxFwpVh6q8zurdCCr2guGQwG0EEKff4D7+XU5rf2fTgcRvpxurpwPB6xXq9DffoLHXrkGyvFSlbFVTIV7p6/4QxrKTaPZgqPKFsp5qqYaufUZ111StuqsKrpawk8Yi3FbGngWNtS559SzBUym2MOz6R8gfNjIBOAm2IMD3H3591nAIVez21/ACUSSP4DF2G8AAAAAElFTkSuQmCC";

        setLoading(false);
      });

      newMap.on('mousemove', (e) => {
        const wrapped = e.lngLat.wrap();
        setPointerPosition({
          lng: wrapped.lng,
          lat: wrapped.lat
        });
      });

      newMap.on('error', (e) => {
        console.error('MapLibre GL error:', e);
        addError('Error loading map: ' + (e.error?.message || 'Unknown error'), true);
        setLoading(false);
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
  }, []); // Only run once on mount

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
        // Fetch the new style
        const response = await fetch(`/api/maps/${mapId}/style.json`);
        if (!response.ok) {
          throw new Error(`Failed to fetch style: ${response.statusText}`);
        }
        const newStyle = await response.json();

        // Update the style using setStyle
        map.setStyle(newStyle);

        // Bust the layer symbol cache by clearing it
        setLayerSymbols({});

        // If we haven't zoomed yet, zoom to the style's center and zoom level
        // setStyle on purpose does not reset the zoom/center, but it's nice to load a map
        // and be correctly positioned on the data
        if (!hasZoomed) {
          if (newStyle.center && newStyle.zoom !== undefined) {
            map.jumpTo({
              center: newStyle.center,
              zoom: newStyle.zoom,
              pitch: newStyle.pitch || 0,
              bearing: newStyle.bearing || 0
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
  }, [mapId, toolResponseCount, mapData]); // Update when these dependencies change

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

  // Generate layer symbols when map data changes
  useEffect(() => {
    const map = mapRef.current;
    if (map && map.isStyleLoaded() && mapData?.layers) {
      const style = map.getStyle();

      mapData.layers.forEach((layer) => {
        const layerId = layer.id;

        // Skip if we already have a symbol for this layer
        if (layerSymbols[layerId]) return;

        const mapLayer = style.layers.find(
          (styleLayer) => "source" in styleLayer && (styleLayer as any).source === layerId
        );

        if (mapLayer) {
          // Call legendSymbol as a function and render the result to JSX

          const tree: RenderElement | null = legendSymbol({
            sprite: style.sprite,
            zoom: map.getZoom(),
            layer: mapLayer as any
          });

          function renderTree(tree: RenderElement | null): JSX.Element | null {
            if (!tree) return null;
            return React.createElement(
              tree.element,
              tree.attributes,
              tree.children?.map(renderTree)
            );
          }

          const symbolElement = renderTree(tree);
          if (symbolElement) {
            setLayerSymbols(prev => ({
              ...prev,
              [layerId]: symbolElement as JSX.Element
            }));
          }
        }
      });
    }
  }, [mapData, layerSymbols]);

  const status = useConnectionStatus();
  const [inputValue, setInputValue] = useState('');

  // Function to fetch messages
  const fetchMessages = async () => {
    try {
      const response = await fetch(`/api/maps/${mapId}/messages`);
      if (response.ok) {
        const data = await response.json();
        // Ensure messages from fetch are sorted by message_index
        const fetchedMessages: ChatCompletionMessageRow[] = data.messages.sort(
          (a: ChatCompletionMessageRow, b: ChatCompletionMessageRow) => (a.id) - (b.id)
        );

        setMessages(fetchedMessages);
      } else {
        console.error('Error fetching messages:', response.statusText);
      }
    } catch (error) {
      console.error('Error fetching messages:', error);
    }
  };

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
      action: "Sending message to Kue...",
      timestamp: new Date().toISOString(),
      completed_at: null,
      layer_id: null,
      status: "active",
      updates: {
        style_json: false,
      },
    };
    setActiveActions(prev => [...prev, sendingAction]);

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
      setActiveActions(prev =>
        prev.filter(a => a.action_id !== actionId)
      );
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
  }, [sessionContext]);

  const wsUrl = useMemo(() => {
    if (!mapId || !jwt)
      return null;

    return `${wsProtocol}//${window.location.host}/api/maps/ws/${mapId}/messages/updates?token=${jwt}`;
  }, [mapId, wsProtocol, jwt]);

  const { lastMessage, readyState } = useWebSocket(wsUrl, {
    onOpen: () => {
      // WebSocket connected
    },
    onError: (event) => {
      console.error('WebSocket error for map:', mapId, event);
      addError('Chat connection error.', false);
    },
    shouldReconnect: () => true, // will attempt to reconnect on all close events
    reconnectAttempts: 10,
    reconnectInterval: 3000,
  }, !sessionContext.loading); // connect if not loading

  // Process incoming messages
  useEffect(() => {
    if (lastMessage) {
      try {
        const update = JSON.parse(lastMessage.data as string);

        // Check if this is an ephemeral action
        if (update.ephemeral === true) {
          const action = update as EphemeralAction;

          if (action.status === 'active') {
            // Add to active actions
            setActiveActions(prev => [...prev, action]);
          } else if (action.status === 'completed') {
            // Remove from active actions
            setActiveActions(prev =>
              prev.filter(a => a.action_id !== action.action_id)
            );

            if (action.updates.style_json) {
              setToolResponseCount(prev => prev + 1);
            }
          }
        } else {
          // Regular message
          setMessages(prevMessages => {
            const newMessages = [...prevMessages, update as ChatCompletionMessageRow];
            return newMessages;
          });
        }
      } catch (e) {
        console.error("Error processing WebSocket message:", e);
        addError("Failed to process update from server.", false);
      }
    }
  }, [lastMessage]);

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
  }, [mapId]);

  useEffect(() => {
    if (errors.length > 0) {
      const latestError = errors[errors.length - 1];
      toast.error(latestError.message);
      console.error(latestError.message);
    }
  }, [errors]);

  // Function to fork the current map
  const saveAndForkMap = async () => {
    setIsSaving(true);
    try {
      const response = await fetch(`/api/maps/${mapId}/save_fork`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
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
    lastMsg &&
      lastMsg.message_json.role === "assistant" &&
      typeof lastMsg.message_json.content === "string"
      ? (lastMsg.message_json.content as string)
      : null;

  // Determine the last user message for the input placeholder.
  const lastUserMsg: string | null =
    lastMsg &&
      lastMsg.message_json.role === "user" &&
      typeof lastMsg.message_json.content === "string"
      ? (lastMsg.message_json.content as string)
      : null;

  // especially chat disconnected errors happen all the time and shouldn't
  // override the text box
  const criticalErrors = errors.filter(e => e.shouldOverrideMessages);

  return (
    <>
      <div className={`relative map-container ${className} grow max-h-screen`} style={{ width, height }}>
        <div ref={mapContainerRef} style={{ width: '100%', height: '100%', minHeight: '100vh' }} className="bg-slate-950" />

        {/* Render the attribute table if showAttributeTable is true */}
        {selectedLayer && (
          <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 z-50 w-4/5 max-w-4xl">
            <AttributeTable
              layer={selectedLayer}
              isOpen={showAttributeTable}
              onClose={() => setShowAttributeTable(false)}
            />
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
          <div className={`z-30 absolute bottom-12 mb-[34px] opacity-90 left-3/5 transform -translate-x-1/2 w-4/5 max-w-lg overflow-auto bg-white dark:bg-gray-800 rounded-t-md shadow-md p-2 text-sm transition-all duration-300 max-h-40 h-auto ${errors.length > 0 ? 'border-red-800' : ''}`}>
            {criticalErrors.length > 0 ? (
              <div className="space-y-1">
                {criticalErrors.map((error) => (
                  <div key={error.id} className="flex items-center justify-between">
                    <div className="flex flex-col flex-1 mr-2">
                      <span className="text-red-400">{error.message}</span>
                      <span className="text-xs text-slate-500 dark:text-gray-400">
                        {error.timestamp.toLocaleTimeString()}
                      </span>
                    </div>
                    <button
                      onClick={() => dismissError(error.id)}
                      className="text-white cursor-pointer hover:underline shrink-0"
                      title="Dismiss error"
                    >
                      Close
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
                  <button className="text-white cursor-pointer ml-2 shrink-0 hover:underline" onClick={() => setIsCancelling(true)}>Cancel</button>
                )}
              </div>
            ) : lastAssistantMsg ? (
              <span>{lastAssistantMsg}</span>
            ) : null}
          </div>
        )}
        <div className={`z-30 absolute bottom-12 left-3/5 transform -translate-x-1/2 w-4/5 max-w-xl bg-white dark:bg-gray-800 shadow-md focus-within:ring-2 focus-within:ring-white/30 flex items-center border border-input bg-input rounded-md ${!showMessages ? 'rounded-l-md' : 'rounded-md'}`}>
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
                className={`p-2 hover:cursor-pointer ${showMessages
                  ? 'text-gray-600 hover:text-gray-500'
                  : 'text-gray-400 hover:text-gray-200'
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
      {showMessages && <div className="z-30 max-h-screen h-full w-80 bg-white dark:bg-gray-800 shadow-md flex flex-col text-sm">
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
                  .filter(part => part.type === 'text')
                  .map(part => part.text)
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
                parts.push(...messageJson.tool_calls.map((tc: ChatCompletionMessageToolCall) =>
                  `Using tool: ${tc.function.name}(${tc.function.arguments})`
                ));
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
            const hasImages = Array.isArray(messageJson.content) &&
              messageJson.content.some(part => part.type === 'image_url');

            if (!contentDisplay && !hasImages) {
              return null;
            }

            return (
              <div key={`msg-${msg.id || index}-${index}`} className={`mb-3 ${messageClass ? `p-2 rounded ${messageClass}` : ''} text-sm`}>
                {contentDisplay}

                {/* Render images if present */}
                {Array.isArray(messageJson.content) && messageJson.content
                  .filter(part => part.type === 'image_url')
                  .map((part, imgIndex) => (
                    <div key={`msg-${msg.id || index}-img-${imgIndex}`} className="mt-2">
                      <img
                        src={part.image_url.url}
                        alt="Message attachment"
                        className="max-w-full rounded-md"
                        style={{ maxHeight: '200px' }}
                      />
                    </div>
                  ))
                }
              </div>
            );
          })}
        </div>
      </div>}
    </>
  );
}