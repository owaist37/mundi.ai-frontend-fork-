// Copyright Bunting Labs, Inc. 2025
import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Clock, Plus } from "lucide-react";
import { Button } from './ui/button';
import { Card } from "./ui/card";
import { Tooltip, TooltipProvider, TooltipTrigger } from "./ui/tooltip";
import { Pagination, PaginationContent, PaginationItem, PaginationLink, PaginationNext, PaginationPrevious } from "./ui/pagination";
import Session from 'supertokens-auth-react/recipe/session';

import { MapProject } from '../lib/types';

interface MapsListProps {
  hideNewButton?: boolean;
}

export default function MapsList({ hideNewButton = false }: MapsListProps) {
  const [projects, setProjects] = useState<MapProject[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [loading, setLoading] = useState(false);
  const sessionContext = Session.useSessionContext();

  // Fetch maps when component mounts or page changes
  useEffect(() => {
    if (!sessionContext.loading && sessionContext.doesSessionExist) {
      fetchProjects(currentPage);
    }
  }, [sessionContext, currentPage]);

  const fetchProjects = async (page: number = 1) => {
    setLoading(true);
    try {
      const response = await fetch(`/api/projects/?page=${page}&limit=12`);
      if (!response.ok) {
        throw new Error(`Failed to fetch projects: ${response.status} ${response.statusText}`);
      }
      const data = await response.json();
      setProjects(data.projects || []);
      setTotalPages(data.total_pages || 1);
      setTotalItems(data.total_items || 0);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch projects');
      setProjects([]);
      setTotalPages(1);
      setTotalItems(0);
    } finally {
      setLoading(false);
    }
  };

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
  };

  const renderPagination = () => {
    if (totalPages <= 1) return null;

    const getVisiblePages = () => {
      const pages = [];
      const maxVisible = 5;

      if (totalPages <= maxVisible) {
        for (let i = 1; i <= totalPages; i++) {
          pages.push(i);
        }
      } else {
        const start = Math.max(1, currentPage - 2);
        const end = Math.min(totalPages, currentPage + 2);

        for (let i = start; i <= end; i++) {
          pages.push(i);
        }
      }

      return pages;
    };

    const visiblePages = getVisiblePages();

    return (
      <Pagination>
        <PaginationContent>
          <PaginationItem>
            <PaginationPrevious
              onClick={() => currentPage > 1 && handlePageChange(currentPage - 1)}
              className={currentPage <= 1 ? "pointer-events-none opacity-50" : "cursor-pointer"}
            />
          </PaginationItem>

          {visiblePages.map((page) => (
            <PaginationItem key={page}>
              <PaginationLink
                onClick={() => handlePageChange(page)}
                isActive={currentPage === page}
                className="cursor-pointer"
              >
                {page}
              </PaginationLink>
            </PaginationItem>
          ))}

          <PaginationItem>
            <PaginationNext
              onClick={() => currentPage < totalPages && handlePageChange(currentPage + 1)}
              className={currentPage >= totalPages ? "pointer-events-none opacity-50" : "cursor-pointer"}
            />
          </PaginationItem>
        </PaginationContent>
      </Pagination>
    );
  };

  const handleCreateMap = async () => {
    setCreating(true);
    try {
      const response = await fetch('/api/maps/create', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          title: 'New Map',
          description: '',
          project: {
            layers: []
          }
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to create map');
      }

      const newMap = await response.json();
      console.log('newMap', newMap);
      // Refresh map list
      fetchProjects(currentPage);

    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create map');
    } finally {
      setCreating(false);
    }
  };

  if (sessionContext.loading) {
    return <div className="p-6 text-white">Loading session...</div>;
  }

  if (!sessionContext.doesSessionExist) {
    return (
      <div className="p-6 text-white">
        <h1 className="text-2xl font-bold mb-4">Maps</h1>
        <p>Please log in to view and create maps.</p>
        <Link to="/auth" className="text-[#e2420d] hover:underline">
          Login
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-center justify-end relative">
        <div className="absolute left-1/2 transform -translate-x-1/2">
          <h1 className="text-2xl font-bold">Your Maps <span className="text-gray-400">({totalItems} projects)</span></h1>
        </div>
        {!hideNewButton && (
          <TooltipProvider delayDuration={100}>
            <Tooltip>
              <TooltipTrigger asChild>
                <div>
                  <Button
                    onClick={handleCreateMap}
                    disabled={creating}
                    className="bg-[#C1FA3D] hover:bg-[#B8E92B] text-black hover:cursor-pointer"
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    {creating ? "Creating..." : "New Map"}
                  </Button>
                </div>
              </TooltipTrigger>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>

      {/* Top pagination */}
      {renderPagination()}

      {error ? (
        <Card className="border-red-500 border-2 text-white flex flex-col items-center justify-center p-6">
          <div className="h-8 w-8 mb-2 text-red-500 flex items-center justify-center">
            <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-lg font-medium text-red-400">Error Loading Maps</h3>
          <p className="text-sm text-gray-400 text-center mt-1">
            {error}
          </p>
          <Button
            onClick={() => fetchProjects(currentPage)}
            className="mt-4 bg-[#C1FA3D] hover:bg-[#B8E92B] text-black hover:cursor-pointer"
          >
            Try Again
          </Button>
        </Card>
      ) : projects.length === 0 ? (
        <Card className="border-dashed border-2 border-slate-500 text-white flex flex-col items-center justify-center p-6">
          <Plus className="h-8 w-8 mb-2 text-[#e2420d]" />
          <h3 className="text-lg font-medium">No Maps Found</h3>
          <p className="text-sm text-gray-400 text-center mt-1">
            Create your first map to get started
          </p>
          {!hideNewButton && (
            <Button
              onClick={handleCreateMap}
              disabled={creating}
              className="mt-4 bg-[#C1FA3D] hover:bg-[#B8E92B] text-black hover:cursor-pointer"
            >
              {creating ? "Creating..." : "Create Your First Map"}
            </Button>
          )}
        </Card>
      ) : (
        <>
          {loading && (
            <div className="flex justify-center items-center py-8">
              <div className="text-white">Loading maps...</div>
            </div>
          )}

          {!loading && (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
              {projects.map((project) => (
                <Link to={`/project/${project.id}`} key={project.id}>
                  <div
                    key={project.id}
                    className="relative h-[280px] border border-zinc-300 rounded-md overflow-hidden group cursor-pointer"
                    style={{
                      backgroundImage: `url(/api/projects/${project.id}/social.webp)`,
                      backgroundSize: 'cover',
                      backgroundPosition: 'center',
                      backgroundRepeat: 'no-repeat'
                    }}
                  >
                    {/* Dark overlay for better text readability */}
                    <div className="absolute inset-0 bg-black/40 group-hover:bg-black/50 transition-colors" />

                    {/* Content overlay */}
                    <div className="relative h-full flex flex-col justify-between p-4 text-white">
                      {/* Header */}
                      <div>
                        <h3 className="text-lg font-semibold line-clamp-2 mb-1">
                          {project.most_recent_version?.title}
                        </h3>
                        <p className="text-sm text-gray-200 line-clamp-2">
                          {project.most_recent_version?.description || "No description"}
                        </p>
                      </div>

                      {/* Footer */}
                      <div className="flex items-center justify-between space-x-2">
                        <div className="flex items-center text-xs text-gray-300">
                          <Clock className="mr-1 h-3 w-3" />
                          {(() => {
                            const lastEdited = new Date(project.most_recent_version?.last_edited || project.created_on);
                            const now = new Date();
                            const diffMs = now.getTime() - lastEdited.getTime();
                            const diffSec = Math.floor(diffMs / 1000);
                            const diffMin = Math.floor(diffSec / 60);
                            const diffHour = Math.floor(diffMin / 60);
                            const diffDay = Math.floor(diffHour / 24);

                            let value, unit;
                            if (diffSec < 60) {
                              value = -diffSec;
                              unit = "second";
                            } else if (diffMin < 60) {
                              value = -diffMin;
                              unit = "minute";
                            } else if (diffHour < 24) {
                              value = -diffHour;
                              unit = "hour";
                            } else {
                              value = -diffDay;
                              unit = "day";
                            }

                            const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
                            return `Last edited ${rtf.format(value, unit as Intl.RelativeTimeFormatUnit)}`;
                          })()}
                        </div>

                        <Button size="sm" asChild className="bg-[#C1FA3D] hover:bg-[#B8E92B] text-black">
                          Open
                        </Button>
                      </div>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </>
      )}

      {/* Bottom pagination */}
      {renderPagination()}

      {/* Add CSS to ensure consistent image alignment */}
      <style>{`
        [data-map-item] {
          display: flex;
          flex-direction: column;
        }

        [data-map-item] > div {
          height: 100%;
        }
      `}</style>
    </div>
  );
}