// Copyright Bunting Labs, Inc. 2025
import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import Session from 'supertokens-auth-react/recipe/session';
import { useDropzone } from 'react-dropzone';
import { DriftDBProvider } from 'driftdb-react';
import MapLibreMap from './MapLibreMap';
import 'maplibre-gl/dist/maplibre-gl.css';
import { toast } from 'sonner';
import { MapData } from '../lib/types';
import { MapProject } from '../lib/types';

// Add interface for tracking upload progress
interface UploadingFile {
  id: string;
  file: File;
  progress: number;
  status: 'uploading' | 'completed' | 'error';
  error?: string;
}

export default function ProjectView() {
  // Get map ID from URL parameter or query string
  const { projectId, versionIdParam } = useParams();
  if (!projectId)
    throw new Error('Project ID is required');

  const [project, setProject] = useState<MapProject | null>(null);

  const versionId = versionIdParam || project?.maps[project?.maps.length - 1] || null;

  const [mapData, setMapData] = useState<MapData | null>(null);

  // Add state for tracking uploading files
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([]);

  // pull changelog and other details
  async function updateProjectData(id: string) {
    const projectRes = await fetch(`/api/projects/${id}`);
    setProject(await projectRes.json());
  }
  useEffect(() => {
    updateProjectData(projectId);
  }, [projectId]);

  // loading current map with auto diff
  const updateMapData = useCallback(async (id: string) => {
    const mapRes = await fetch(`/api/maps/${id}?diff_map_id=auto`);
    setMapData(await mapRes.json());
  }, []);

  useEffect(() => {
    if (!project) return;
    if (!versionId) return;

    updateMapData(versionId);
  }, [versionId, project, updateMapData]);
  const sessionContext = Session.useSessionContext();

  // Get room ID for DriftDB
  const [roomId, setRoomId] = useState<string | null>(null);

  const fetchRoomId = useCallback(async (mapId: string) => {
    try {
      const response = await fetch(`/api/maps/${mapId}/room`);
      if (!response.ok) {
        throw new Error(`Failed to get room: ${response.statusText}`);
      }
      const data = await response.json();
      setRoomId(data.room_id);
    } catch (err) {
      console.error('Error fetching room ID:', err);
    }
  }, []);

  // Helper function to upload a single file with progress tracking
  const uploadFile = useCallback(async (file: File, fileId: string) => {
    if (!versionId) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
      const xhr = new XMLHttpRequest();

      // Track upload progress
      xhr.upload.addEventListener('progress', (event) => {
        if (event.lengthComputable) {
          const progress = Math.round((event.loaded / event.total) * 100);
          setUploadingFiles(prev =>
            prev.map(f => f.id === fileId ? { ...f, progress } : f)
          );
        }
      });

      // Handle completion
      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          const response = JSON.parse(xhr.responseText);
          toast.success(`Layer "${response.name}" uploaded successfully! Refreshing...`);

          // Mark as completed
          setUploadingFiles(prev =>
            prev.map(f => f.id === fileId ? { ...f, status: 'completed', progress: 100 } : f)
          );

          // Remove from uploading list after delay
          setTimeout(() => {
            setUploadingFiles(prev => prev.filter(f => f.id !== fileId));
          }, 2000);

          // Refresh the map data
          setTimeout(() => {
            updateMapData(versionId);
          }, 2000);
        } else {
          throw new Error(`Upload failed: ${xhr.statusText}`);
        }
      });

      // Handle errors
      xhr.addEventListener('error', () => {
        const errorMessage = 'Upload failed due to network error';
        setUploadingFiles(prev =>
          prev.map(f => f.id === fileId ? { ...f, status: 'error', error: errorMessage } : f)
        );
        toast.error(`Error uploading ${file.name}: ${errorMessage}`);
      });

      xhr.open('POST', `/api/maps/${versionId}/layers`);
      xhr.send(formData);

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      setUploadingFiles(prev =>
        prev.map(f => f.id === fileId ? { ...f, status: 'error', error: errorMessage } : f)
      );
      toast.error(`Error uploading ${file.name}: ${errorMessage}`);
    }
  }, [versionId, updateMapData]);

  // Modified dropzone implementation to handle multiple files
  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (!versionId || acceptedFiles.length === 0) return;

    const maxFileSize = 100 * 1024 * 1024; // 100MB in bytes

    // Filter out files that are too large
    const validFiles = acceptedFiles.filter(file => {
      if (file.size > maxFileSize) {
        toast.error(`File "${file.name}" is too large. Files over 100MB aren't supported yet.`);
        return false;
      }
      return true;
    });

    if (validFiles.length === 0) return;

    // Create uploading file entries
    const newUploadingFiles: UploadingFile[] = validFiles.map(file => ({
      id: `${file.name}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      file,
      progress: 0,
      status: 'uploading'
    }));

    // Add to uploading files state
    setUploadingFiles(prev => [...prev, ...newUploadingFiles]);

    // Start uploading each file
    newUploadingFiles.forEach(uploadingFile => {
      uploadFile(uploadingFile.file, uploadingFile.id);
    });
  }, [versionId, uploadFile]);

  const {
    getRootProps,
    getInputProps,
    isDragActive,
    open
  } = useDropzone({
    onDrop,
    noClick: true, // Prevent opening the file dialog when clicking
    accept: {
      'application/geo+json': ['.geojson', '.json'],
      'application/vnd.google-earth.kml+xml': ['.kml'],
      'application/vnd.google-earth.kmz': ['.kmz'],
      'image/tiff': ['.tif', '.tiff'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
      'application/geopackage+sqlite3': ['.gpkg'],
      'application/octet-stream': ['.fgb', '.dem'],
      'application/zip': ['.zip']
    }
  });

  useEffect(() => {
    if (!versionId) {
      return;
    }

    // Only fetch if we have a session and an ID
    if (!sessionContext.loading && versionId) {
      updateMapData(versionId);
      fetchRoomId(versionId);
    }
  }, [versionId, sessionContext.loading, updateMapData, fetchRoomId]);

  if (sessionContext.loading) {
    return <div className="p-6">Loading session...</div>;
  }

  if (!sessionContext.doesSessionExist) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-4">Map View</h1>
        <p>Please log in to view this map.</p>
        <a href="/auth" className="text-blue-500 hover:underline">Login</a>
      </div>
    );
  }

  if (!versionId) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-4">Loading project {projectId} version {versionId}...</h1>
      </div>
    );
  }

  if (!mapData) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-4">Map Not Found</h1>
        <p>The requested map could not be found.</p>
        <a href="/maps" className="text-blue-500 hover:underline">Back to Maps</a>
      </div>
    );
  }

  return (
    <div
      {...getRootProps()}
      className={`flex grow ${isDragActive ? 'file-drag-active' : ''}`}
    >
      {/* Dropzone */}
      <input {...getInputProps()} />

      {/* Interactive Map Section */}
      {roomId && project ? (
        <DriftDBProvider api="/drift/" room={roomId}>
          <MapLibreMap
            mapId={versionId}
            height="100%"
            project={project}
            mapData={mapData}
            openDropzone={open}
            updateMapData={updateMapData}
            updateProjectData={updateProjectData}
            uploadingFiles={uploadingFiles}
          />
        </DriftDBProvider>
      ) : (
        <div className="flex items-center justify-center h-full">
          <p>Loading room information...</p>
        </div>
      )}
    </div>
  );
}