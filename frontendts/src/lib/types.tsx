// Copyright Bunting Labs, Inc. 2025

export interface MapProject {
  id: string;
  owner_uuid: string;
  link_accessible: boolean;
  maps: string[];
  created_on: string;
  most_recent_version?: {
    title?: string;
    description?: string;
    last_edited?: string;
  };
  postgres_connections?: PostgresConnectionDetails[];
}

export type ProjectState = { type: 'not_logged_in' } | { type: 'loading' } | { type: 'loaded'; projects: MapProject[] };

export interface MapLayer {
  id: string;
  name: string;
  path: string;
  type: string;
  raster_cog_url?: string;
  metadata?: Record<string, unknown>;
  bounds?: number[];
  geometry_type?: string;
  feature_count?: number;
  original_srid?: number;
}

export interface PostgresConnectionDetails {
  connection_id: string;
  table_count: number;
  friendly_name: string;
  last_error_text?: string;
  last_error_timestamp?: string;
}

export interface MapData {
  map_id: string;
  project_id: string;
  layers: MapLayer[];
  changelog: Array<{
    message: string;
    map_state: string;
    last_edited: string;
  }>;
  display_as_diff: boolean;
  diff?: MapDiff;
}

export interface LayerDiff {
  layer_id: string;
  name: string;
  status: string; // 'added', 'removed', 'edited', 'existing'
  changes?: {
    [key: string]: {
      old: string | object | null;
      new: string | object | null;
    };
  };
}

export interface MapDiff {
  prev_map_id?: string;
  new_map_id: string;
  layer_diffs: LayerDiff[];
}

export interface PointerPosition {
  lng: number;
  lat: number;
}

export interface PresenceData {
  value: PointerPosition;
  lastSeen: number;
}

export interface EphemeralUpdates {
  style_json: boolean;
}

export interface EphemeralAction {
  map_id: string;
  ephemeral: boolean;
  action_id: string;
  layer_id: string | null;
  action: string;
  timestamp: string;
  completed_at: string | null;
  status: 'active' | 'completed' | 'zoom_action' | 'error';
  updates: EphemeralUpdates;
  bounds?: [number, number, number, number];
  description?: string;
  error_message?: string;
}
