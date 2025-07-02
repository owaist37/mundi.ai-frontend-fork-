// Copyright Bunting Labs, Inc. 2025

import { useParams, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Database, Loader2, ArrowLeft, RefreshCw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import MermaidComponent from "@/components/MermaidComponent";
import { useEffect, useState } from "react";

const PostGISDocumentation = () => {
  const { connectionId } = useParams<{ connectionId: string }>();
  const navigate = useNavigate();

  const [documentation, setDocumentation] = useState<string | null>(null);
  const [connectionName, setConnectionName] = useState<string>("");
  const [projectId, setProjectId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isRegenerating, setIsRegenerating] = useState(false);

  useEffect(() => {
    if (connectionId) {
      fetchDocumentation();
    }
  }, [connectionId]);

  const fetchDocumentation = async () => {
    setLoading(true);
    setError(null);

    try {
      // First, we need to find which project this connection belongs to
      const projectsResponse = await fetch('/api/projects/');
      if (!projectsResponse.ok) {
        throw new Error('Failed to fetch projects');
      }
      const projectsData = await projectsResponse.json();

      // Search through all projects to find the one containing this connection
      let foundProjectId = '';
      let foundConnectionName = '';

      for (const project of projectsData.projects) {
        // Get the full project details which includes postgres_connections
        const projectResponse = await fetch(`/api/projects/${project.id}`);
        if (projectResponse.ok) {
          const projectDetails = await projectResponse.json();
          const connection = projectDetails.postgres_connections?.find((c: any) => c.connection_id === connectionId);
          if (connection) {
            foundProjectId = project.id;
            foundConnectionName = connection.friendly_name || connection.connection_name || 'Database';
            break;
          }
        }
      }

      if (!foundProjectId) {
        throw new Error('Connection not found in any project');
      }

      setProjectId(foundProjectId);
      setConnectionName(foundConnectionName);

      // Now fetch the documentation
      const docResponse = await fetch(`/api/projects/${foundProjectId}/postgis-connections/${connectionId}/documentation`);
      if (!docResponse.ok) {
        throw new Error(`Failed to fetch documentation: ${docResponse.statusText}`);
      }
      const docData = await docResponse.json();
      setDocumentation(docData.documentation);
      if (docData.friendly_name) {
        setConnectionName(docData.friendly_name);
      }
    } catch (err) {
      console.error('Error fetching database documentation:', err);
      setError(err instanceof Error ? err.message : 'Failed to load documentation');
      setDocumentation(null);
    } finally {
      setLoading(false);
    }
  };

  const handleRegenerate = async () => {
    if (!connectionId || !projectId) return;

    setIsRegenerating(true);
    setError(null);

    try {
      const response = await fetch(`/api/projects/${projectId}/postgis-connections/${connectionId}/regenerate-documentation`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error(`Failed to regenerate documentation: ${response.statusText}`);
      }

      // Wait a moment and then refetch the documentation
      setTimeout(() => {
        fetchDocumentation();
        setIsRegenerating(false);
      }, 2000);
    } catch (err) {
      console.error('Error regenerating database documentation:', err);
      setError(err instanceof Error ? err.message : 'Failed to regenerate documentation');
      setIsRegenerating(false);
    }
  };

  const fallbackContent = `
Documentation is being generated for this database. Please check back in a few moments.

If documentation generation fails, this indicates the database connection details or the database structure couldn't be analyzed automatically.
`;

  return (
    <div className="flex flex-col h-screen bg-background w-full">
      {/* Header */}
      <div className="border-b">
        <div className="flex items-center justify-between p-4">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate(-1)}
              className="flex items-center gap-2 hover:cursor-pointer"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to Map
            </Button>
            <div className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              <h1 className="text-xl font-semibold">{connectionName || 'Database Documentation'}</h1>
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRegenerate}
            disabled={isRegenerating || loading}
            className="flex items-center gap-2 hover:cursor-pointer"
          >
            {isRegenerating ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            {isRegenerating ? 'Regenerating...' : 'Regenerate'}
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-8">
        <div className="max-w-4xl mx-auto">
          {loading && (
            <div className="flex items-center justify-center p-8">
              <Loader2 className="h-6 w-6 animate-spin mr-2" />
              <span>Loading database documentation...</span>
            </div>
          )}

          {error && (
            <div className="p-4 border border-red-500 rounded-lg mb-4">
              <p className="text-red-500">Error loading documentation: {error}</p>
            </div>
          )}

          {!loading && !error && (
            <div className="prose prose-sm prose-invert max-w-none">
              <ReactMarkdown
                components={{
                  code(props) {
                    const { className, children, ...rest } = props;
                    const match = /language-(\w+)/.exec(className || '');
                    const language = match ? match[1] : '';

                    if (language === 'mermaid') {
                      return (
                        <div className="bg-muted/20 mx-auto my-4">
                          <MermaidComponent chart={String(children)} />
                        </div>
                      );
                    }

                    return (
                      <code className={className} {...rest}>
                        {children}
                      </code>
                    );
                  }
                }}
              >
                {documentation || fallbackContent}
              </ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default PostGISDocumentation;