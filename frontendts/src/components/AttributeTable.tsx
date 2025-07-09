import { useCallback, useEffect, useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { MapLayer } from '@/lib/types';
import { Input } from './ui/input';

// Type for pandas JSON format
type PandasData = {
  columns: string[];
  data: (string | number | boolean)[][];
};

interface AttributeTableProps {
  layer: MapLayer;
  isOpen: boolean;
  onClose: () => void;
}

const DEBOUNCE_MS = 500;

export default function AttributeTable({ layer, isOpen, onClose }: AttributeTableProps) {
  const [inputText, setInputText] = useState('');
  const [sqlQuery, setSqlQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [data, setData] = useState<PandasData>({
    columns: [],
    data: [],
  });
  const [duration, setDuration] = useState(0);

  const fetchLayerData = useCallback(
    async (query: string) => {
      setIsLoading(true);
      try {
        const response = await fetch(`/api/layer/${layer.id}/query`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            natural_language_query: query,
            max_n_rows: 100,
          }),
        });

        if (!response.ok) {
          throw new Error('Failed to fetch layer data');
        }

        const result = await response.json();
        setSqlQuery(result.query);
        setDuration(result.duration_ms);

        // Use headers and result arrays directly from the response
        setData({
          columns: result.headers,
          data: result.result,
        });
      } catch (error) {
        console.error('Error fetching layer data:', error);
      } finally {
        setIsLoading(false);
      }
    },
    [layer.id],
  );

  // Handle input text changes with debounce, or fetch default data on mount
  useEffect(() => {
    const query = inputText.trim() || 'Show me all data';
    const delay = inputText.trim() ? DEBOUNCE_MS : 0;

    console.log(`Fetching attributes for layer: ${layer.name} (ID: ${layer.id})`);

    const timer = setTimeout(() => {
      fetchLayerData(query);
    }, delay);

    return () => clearTimeout(timer);
  }, [inputText, layer, fetchLayerData]);

  // Handle escape key to close dialog
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [onClose]);

  return (
    <Dialog open={isOpen} onOpenChange={() => onClose()}>
      <DialogContent className="sm:max-w-[90vw] md:max-w-[800px] max-h-[90vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="font-semibold text-base">
            Attributes: {layer.name} <span className="text-muted-foreground">({layer.feature_count} features)</span>
            {/* {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground ml-2" />} */}
          </DialogTitle>
          {/* <DialogDescription className="text-muted-foreground text-xs">
             features • {layer.type}
          </DialogDescription> */}
        </DialogHeader>

        <div className="flex flex-col gap-2 flex-1 min-h-0">
          {/* Input text box */}
          <Input
            placeholder="Type your query (e.g., 'Show me all data', 'Find records where status is active')"
            className="bg-background text-sm focus-visible:ring-0 focus-visible:ring-offset-0"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
          />

          {/* SQL Query display */}
          <Card className={`rounded-md border border-border py-2 ${isLoading ? 'animate-pulse' : ''}`}>
            <CardContent className="px-2">
              <pre className="font-medium text-orange-500 overflow-x-auto">
                <code className="text-sm">
                  {sqlQuery}{' '}
                  {duration > 0 && (
                    <span className="text-muted-foreground">
                      {sqlQuery.indexOf('\n') == -1 && <br />}&nbsp;→ {data.data.length} rows in {Math.round(duration)}ms
                    </span>
                  )}
                </code>
              </pre>
            </CardContent>
          </Card>

          {/* Table display with sticky header */}
          <div className="border border-border rounded-md flex-1 overflow-y-auto">
            <table className={`w-full text-sm relative ${isLoading ? 'animate-pulse' : ''}`}>
              <thead>
                <tr className="border-b border-border">
                  {data.columns.map((column, i) => (
                    <th
                      key={i}
                      className="p-2 text-left font-medium text-muted-foreground bg-background sticky top-0 border-b border-border"
                    >
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.data.map((row, i) => (
                  <tr key={i} className="border-b border-border hover:bg-muted/50">
                    {row.map((cell, j) => (
                      <td key={j} className="p-2 text-nowrap">
                        {String(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* TODO: add download CSV */}
      </DialogContent>
    </Dialog>
  );
}
