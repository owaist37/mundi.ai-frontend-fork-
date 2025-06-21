import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenuSub,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"
import { LogOut, Map, LogIn, UserPlus, KeyRound, BookOpen, Cloud, PanelRightClose, PanelRightOpen } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

import Session from "supertokens-auth-react/recipe/session";
import { signOut } from "supertokens-auth-react/recipe/session";
import { Link } from "react-router-dom"
import MLightSvg from "@/assets/M-light.svg"
import MDarkSvg from "@/assets/M-dark.svg"
import MundiLightSvg from "@/assets/Mundi-light.svg"
import MundiDarkSvg from "@/assets/Mundi-dark.svg"
import { ProjectState } from "@/lib/types";

export function AppSidebar({ projects }: { projects: ProjectState }) {
  const sessionContext = Session.useSessionContext();
  const { state, toggleSidebar } = useSidebar();

  async function onLogout() {
    await signOut();
    window.location.href = "/auth"; // or redirect to wherever the login page is
  }

  return (
    <Sidebar collapsible="icon" data-theme="light">
      <SidebarHeader className="flex flex-col items-center p-4">
        {state === "collapsed" ? (
          <>
            <a href="https://mundi.ai/" target="_blank" className="w-8 h-8">
              <img src={MLightSvg} alt="M" className="w-full h-full dark:hidden" />
              <img src={MDarkSvg} alt="M" className="w-full h-full hidden dark:block" />
            </a>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={toggleSidebar}
                  className="w-8 h-8 mt-2 cursor-pointer"
                >
                  <PanelRightOpen className="w-4 h-4 scale-x-[-1]" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">
                <p>Expand Sidebar</p>
              </TooltipContent>
            </Tooltip>
          </>
        ) : (
          <div className="flex items-center justify-between w-full">
            <a href="https://docs.mundi.ai/" target="_blank" className="h-8">
              <img src={MundiLightSvg} alt="Mundi" className="h-full dark:hidden" />
              <img src={MundiDarkSvg} alt="Mundi" className="h-full hidden dark:block" />
            </a>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={toggleSidebar}
                  className="w-8 h-8 cursor-pointer"
                >
                  <PanelRightClose className="w-4 h-4 scale-x-[-1]" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">
                <p>Collapse Sidebar</p>
              </TooltipContent>
            </Tooltip>
          </div>
        )}
      </SidebarHeader>
      <SidebarContent>
        {!sessionContext.loading && sessionContext.doesSessionExist && (
          <>
            <SidebarGroup>
              <SidebarGroupLabel asChild>Projects</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  <SidebarMenuItem>
                    <SidebarMenuButton asChild tooltip="My Projects">
                      <Link to="/">
                        <Map className="w-4 h-4 mr-2" />
                        <span className="text-sm">My Projects</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                  {projects.type === 'loaded' && (
                    <SidebarMenuSub>
                      {projects.projects.slice(-3).map((project) => (
                        <SidebarMenuItem key={project.id}>
                          <SidebarMenuButton asChild>
                            <Link to={`/project/${project.id}`} className="flex items-center justify-between w-full">
                              <span className="text-sm">
                                {project.most_recent_version?.title || `Project ${project.id.slice(0, 8)}`}
                              </span>
                              <span className="text-xs text-muted-foreground ml-2">
                                {project.most_recent_version?.last_edited
                                  ? (() => {
                                    const now = new Date();
                                    const edited = new Date(project.most_recent_version.last_edited);
                                    const diffMs = now.getTime() - edited.getTime();
                                    const diffSecs = Math.floor(diffMs / 1000);
                                    const diffMins = Math.floor(diffSecs / 60);
                                    const diffHours = Math.floor(diffMins / 60);
                                    const diffDays = Math.floor(diffHours / 24);

                                    if (diffSecs < 60) return `${diffSecs} seconds ago`;
                                    if (diffMins < 60) return `${diffMins} minutes ago`;
                                    if (diffHours < 24) return `${diffHours} hours ago`;
                                    return `${diffDays} days ago`;
                                  })()
                                  : 'No date'
                                }
                              </span>
                            </Link>
                          </SidebarMenuButton>
                        </SidebarMenuItem>
                      ))}
                    </SidebarMenuSub>
                  )}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </>
        )}

        <SidebarGroup>
          <SidebarGroupLabel>Account</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {!sessionContext.loading && (
                sessionContext.doesSessionExist ? (
                  <>
                    <SidebarMenuItem>
                      <SidebarMenuButton onClick={onLogout} className="cursor-pointer" tooltip="Logout">
                        <LogOut className="w-4 h-4 mr-2" />
                        <span className="text-sm">Logout</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  </>
                ) : (
                  <>
                    <SidebarMenuItem>
                      <SidebarMenuButton asChild tooltip="Sign In">
                        <Link to="/auth">
                          <LogIn className="w-4 h-4 mr-2" />
                          <span className="text-sm">Sign In</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                    <SidebarMenuItem>
                      <SidebarMenuButton asChild tooltip="Sign Up">
                        <Link to="/auth?show=signup">
                          <UserPlus className="w-4 h-4 mr-2" />
                          <span className="text-sm">Sign Up</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                    <SidebarMenuItem>
                      <SidebarMenuButton asChild tooltip="Forgot Password">
                        <Link to="/auth/reset-password">
                          <KeyRound className="w-4 h-4 mr-2" />
                          <span className="text-sm">Forgot Password</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  </>
                )
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>About</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="Documentation">
                  <a href="https://docs.mundi.ai" target="_blank">
                    <BookOpen className="w-4 h-4 mr-2" />
                    <span className="text-sm">Documentation</span>
                  </a>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="Mundi Cloud">
                  <a href="https://app.mundi.ai" target="_blank">
                    <Cloud className="w-4 h-4 mr-2" />
                    <span className="text-sm">Mundi Cloud</span>
                  </a>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="p-1 border-t border-border border-gray-700">
        <div className="text-center">
          <a href="https://buntinglabs.com" target="_blank" className="text-muted-foreground text-xs hover:underline">
            {state === "collapsed" ? (
              <img src="/public/bunting_bird.svg" alt="Bunting Labs" className="w-6 h-6 mx-auto my-2" />
            ) : (
              "© Bunting Labs, Inc. 2025"
            )}
          </a>
        </div>
      </SidebarFooter>
    </Sidebar>
  )
}