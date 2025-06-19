// Copyright Bunting Labs, Inc. 2025

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Database, Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import MermaidComponent from "./MermaidComponent";
import { useEffect, useState } from "react";

interface DatabaseDetailsDialogProps {
  isOpen: boolean;
  onClose: () => void;
  databaseName: string;
  connectionId: string;
  projectId: string;
}

const DatabaseDetailsDialog = ({ isOpen, onClose, databaseName, connectionId, projectId }: DatabaseDetailsDialogProps) => {
  const [documentation, setDocumentation] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && connectionId && projectId) {
      setLoading(true);
      setError(null);

      fetch(`/api/projects/${projectId}/postgis-connections/${connectionId}/documentation`)
        .then(response => {
          if (!response.ok) {
            throw new Error(`Failed to fetch documentation: ${response.statusText}`);
          }
          return response.json();
        })
        .then(data => {
          setDocumentation(data.documentation);
        })
        .catch(err => {
          console.error('Error fetching database documentation:', err);
          setError(err.message);
          setDocumentation(null);
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [isOpen, connectionId, projectId]);

  // Fallback content for when documentation is not available
  const fallbackContent = `
Documentation is being generated for this database. Please check back in a few moments.

If documentation generation fails, this indicates the database connection details or the database structure couldn't be analyzed automatically.
`;

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col xl:!max-w-4xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            {databaseName}
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-6 flex-1 min-h-0">
          <div className="overflow-y-auto pr-4">
            <div className="space-y-6">
              {loading && (
                <div className="flex items-center justify-center p-8">
                  <Loader2 className="h-6 w-6 animate-spin mr-2" />
                  <span>Loading database documentation...</span>
                </div>
              )}

              {error && (
                <div className="p-4 border border-red-500 rounded-lg">
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
                            <div className="border rounded-lg p-4 bg-muted/20 my-6 max-w-2xl mx-auto">
                              <MermaidComponent chart={String(children).replace(/\n$/, '')} />
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
      </DialogContent>
    </Dialog>
  );
};

export default DatabaseDetailsDialog;