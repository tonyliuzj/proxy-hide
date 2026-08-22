"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  BellRing,
  Boxes,
  BookOpen,
  ChevronDown,
  CircleGauge,
  Database,
  Filter,
  Gauge,
  Globe2,
  ListChecks,
  LogOut,
  Menu,
  Network,
  Settings,
  SlidersHorizontal,
  Target,
  UsersRound,
} from "lucide-react";
import { Brand } from "@/components/brand";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { api, ApiError } from "@/lib/api/client";
import type { SessionDto } from "@/lib/api/dto";
import { useApiQuery } from "@/lib/api/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

type ShellMode = "workspace" | "admin";
type NavItem = { label: string; href: string; icon: typeof Gauge };

const workspaceNavigation: { label: string; items: NavItem[] }[] = [
  { label: "Overview", items: [{ label: "Dashboard", href: "/dashboard", icon: Gauge }] },
  { label: "Inventory", items: [{ label: "Proxies", href: "/proxies", icon: Network }, { label: "Sources", href: "/sources", icon: Database }, { label: "Targets", href: "/targets", icon: Target }] },
  { label: "Routing", items: [{ label: "Filters", href: "/filters", icon: Filter }, { label: "Pools", href: "/pools", icon: Boxes }, { label: "Endpoints", href: "/endpoints", icon: Globe2 }, { label: "Connection guide", href: "/connection-guide", icon: BookOpen }] },
  { label: "Operations", items: [{ label: "Checks", href: "/checks", icon: ListChecks }, { label: "Traffic", href: "/traffic", icon: Activity }, { label: "Alerts", href: "/alerts", icon: BellRing }, { label: "Access", href: "/access", icon: UsersRound }, { label: "Settings", href: "/settings", icon: Settings }] },
];

const adminNavigation: { label: string; items: NavItem[] }[] = [
  { label: "Platform", items: [{ label: "Overview", href: "/admin", icon: CircleGauge }, { label: "Statistics", href: "/admin/statistics", icon: Activity }, { label: "Workspaces", href: "/admin/workspaces", icon: UsersRound }, { label: "Global catalog", href: "/admin/catalog", icon: Globe2 }] },
];

function Navigation({ mode, onNavigate }: { mode: ShellMode; onNavigate?: () => void }) {
  const pathname = usePathname();
  const groups = mode === "admin" ? adminNavigation : workspaceNavigation;
  return <nav className="flex-1 overflow-y-auto px-3 py-4">{groups.map((group) => <div key={group.label} className="mb-5"><p className="mb-1.5 px-2 text-[10px] font-semibold uppercase text-white/35">{group.label}</p><div className="space-y-0.5">{group.items.map((item) => { const active = item.href === "/admin" ? pathname === item.href : pathname === item.href || pathname.startsWith(`${item.href}/`); const Icon = item.icon; return <Link key={item.href} href={item.href} onClick={onNavigate} className={cn("flex h-9 items-center gap-3 rounded-md px-2.5 text-sm text-white/65 transition-colors hover:bg-white/8 hover:text-white", active && "bg-white/10 text-white")}><Icon className={cn("size-4", active ? "text-[#38c8b2]" : "text-white/45")} /><span>{item.label}</span></Link>; })}</div></div>)}</nav>;
}

function initials(email?: string) {
  if (!email) return "--";
  return email.slice(0, 2).toUpperCase();
}

function Sidebar({ mode, session, onNavigate }: { mode: ShellMode; session?: SessionDto; onNavigate?: () => void }) {
  const workspace = session?.workspace;
  const email = session?.user.email;
  return <div className="flex h-full flex-col bg-[#172227] text-white"><div className="flex h-16 items-center border-b border-white/8 px-5"><Brand admin={mode === "admin"} /></div>{mode === "workspace" ? <div className="mx-3 mt-3 rounded-md border border-white/8 bg-white/5 px-3 py-2.5"><p className="truncate text-xs font-medium">{workspace?.name ?? "Workspace unavailable"}</p><div className="mt-1 flex items-center gap-1.5 text-[11px] text-white/45"><span className={cn("size-1.5 rounded-full", workspace?.status === "active" ? "bg-emerald-400" : "bg-white/30")} />{workspace?.status === "active" ? "Workspace active" : "Status unknown"}</div></div> : <div className="mx-3 mt-3 rounded-md border border-white/8 bg-white/5 px-3 py-2.5"><p className="text-xs font-medium">Platform administration</p><p className="mt-1 text-[11px] text-white/40">Isolated operator access</p></div>}<Navigation mode={mode} onNavigate={onNavigate} /><div className="border-t border-white/8 p-3"><div className="flex items-center gap-2.5 rounded-md px-2 py-1.5"><Avatar className="size-7"><AvatarFallback className="bg-white/10 text-[10px] text-white">{initials(email)}</AvatarFallback></Avatar><div className="min-w-0 flex-1"><p className="truncate text-xs font-medium">{mode === "admin" ? "Platform administrator" : "Workspace owner"}</p><p className="truncate text-[10px] text-white/40">{email ?? "Session unavailable"}</p></div></div></div></div>;
}

export function AppShell({ children, mode = "workspace" }: { children: React.ReactNode; mode?: ShellMode }) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [mobileOpen, setMobileOpen] = useState(false);
  const sessionQuery = useApiQuery<SessionDto>(["session", mode], "/auth/me");
  const healthQuery = useQuery({ queryKey: ["health"], queryFn: () => api.health<{ status: string }>(), staleTime: 15_000, refetchInterval: 30_000 });
  const logout = useMutation({ mutationFn: () => api.post<void>("/auth/logout"), onSuccess: () => { queryClient.clear(); router.replace("/login"); }, onError: () => toast.error("Could not sign out. Please retry.") });
  const session = sessionQuery.data;
  useEffect(() => {
    if (sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401) {
      router.replace("/login");
      return;
    }
    if (!session) return;
    if (mode === "workspace" && session.must_change_password && pathname !== "/settings") router.replace("/settings");
    if (mode === "admin" && session.user.role !== "platform_admin") router.replace("/dashboard");
    if (mode === "workspace" && session.user.role === "platform_admin") router.replace("/admin");
  }, [mode, router, session, sessionQuery.error]);
  const health = healthQuery.data?.status === "healthy" || healthQuery.data?.status === "ok";
  const nav = (mode === "admin" ? adminNavigation : workspaceNavigation).flatMap((group) => group.items);
  const current = nav.find((item) => item.href === "/admin" ? pathname === item.href : pathname === item.href || pathname.startsWith(`${item.href}/`));
  return <div className="min-h-screen bg-background"><aside className="fixed inset-y-0 left-0 z-30 hidden w-60 lg:block"><Sidebar mode={mode} session={session} /></aside><div className="min-h-screen lg:pl-60"><header className="sticky top-0 z-20 flex h-14 items-center border-b bg-background/95 px-4 backdrop-blur sm:px-6"><Sheet open={mobileOpen} onOpenChange={setMobileOpen}><SheetTrigger asChild><Button variant="ghost" size="icon" className="mr-2 lg:hidden" aria-label="Open navigation"><Menu /></Button></SheetTrigger><SheetContent side="left" className="w-72 border-0 p-0"><SheetTitle className="sr-only">Navigation</SheetTitle><SheetDescription className="sr-only">Proxy Hide sections</SheetDescription><Sidebar mode={mode} session={session} onNavigate={() => setMobileOpen(false)} /></SheetContent></Sheet><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{current?.label ?? (mode === "admin" ? "Platform" : "Workspace")}</p></div><div className="flex items-center gap-1.5"><Badge variant="outline" className={cn("hidden gap-1.5 sm:flex", health ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "text-muted-foreground")}><span className={cn("size-1.5 rounded-full", health ? "bg-emerald-500" : "bg-muted-foreground/50")} />{health ? "Systems operational" : "Status unavailable"}</Badge><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" className="h-9 gap-2 px-2"><Avatar className="size-6"><AvatarFallback className="text-[10px]">{initials(session?.user.email)}</AvatarFallback></Avatar><ChevronDown className="size-3 text-muted-foreground" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="w-56"><DropdownMenuLabel>{session?.user.email ?? "Session unavailable"}</DropdownMenuLabel><DropdownMenuSeparator />{mode === "workspace" ? <DropdownMenuItem asChild><Link href="/settings"><SlidersHorizontal />Workspace settings</Link></DropdownMenuItem> : null}<DropdownMenuSeparator /><DropdownMenuItem disabled={logout.isPending} onSelect={() => logout.mutate()}><LogOut />{logout.isPending ? "Signing out" : "Sign out"}</DropdownMenuItem></DropdownMenuContent></DropdownMenu></div></header><main>{children}</main></div></div>;
}
