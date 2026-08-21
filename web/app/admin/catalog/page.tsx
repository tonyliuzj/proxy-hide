"use client";

import { MoreHorizontal, Play, RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ProxyImportDialog } from "@/components/dialogs/proxy-import-dialog";
import { SourceDialog } from "@/components/dialogs/source-dialog";
import { DataToolbar } from "@/components/data-toolbar";
import { PageHeader } from "@/components/page-header";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, ApiError } from "@/lib/api/client";
import { useAdminProxies, useAdminSources } from "@/lib/api/resources";
import type { Source } from "@/lib/api/types";
import { formatPercent, formatRelativeTime } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

export default function GlobalCatalogPage() {
  const [proxySearch, setProxySearch] = useState("");
  const [sourceSearch, setSourceSearch] = useState("");
  const proxies = useAdminProxies({ page_size: 100 });
  const sources = useAdminSources({ page_size: 100 });
  const queryClient = useQueryClient();
  const proxyRows = (proxies.data?.items ?? []).filter((proxy) => `${proxy.host} ${proxy.countryCode} ${proxy.protocol}`.toLowerCase().includes(proxySearch.toLowerCase()));
  const sourceRows = (sources.data?.items ?? []).filter((source) => `${source.name} ${source.url}`.toLowerCase().includes(sourceSearch.toLowerCase()));

  async function run(source: Source) {
    try {
      await api.post(`/admin/sources/${source.id}/run`);
      toast.success("Global source refresh queued");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not queue source refresh.");
    }
  }

  async function toggle(source: Source) {
    try {
      await api.patch(`/admin/sources/${source.id}`, { enabled: !source.enabled });
      await queryClient.invalidateQueries({ queryKey: ["admin", "sources"] });
      toast.success(source.enabled ? "Global source disabled" : "Global source enabled");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not update the source.");
    }
  }

  async function remove(source: Source) {
    if (!window.confirm(`Delete ${source.name}? Existing catalog routes remain until inventory reconciliation.`)) return;
    try {
      await api.delete(`/admin/sources/${source.id}`);
      await queryClient.invalidateQueries({ queryKey: ["admin", "sources"] });
      toast.success("Global source deleted");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not delete the source.");
    }
  }

  return <>
    <PageHeader title="Global catalog" description="Operator-managed routes shared with enabled workspaces and masked in customer views." actions={<><SourceDialog admin /><ProxyImportDialog admin /></>} />
    <div className="p-4 sm:p-6"><Tabs defaultValue="proxies"><TabsList><TabsTrigger value="proxies">Proxies</TabsTrigger><TabsTrigger value="sources">Sources</TabsTrigger></TabsList>
      <TabsContent value="proxies"><Card className="overflow-hidden"><DataToolbar value={proxySearch} onChange={setProxySearch} placeholder="Search address, country, or protocol" actions={<Button variant="outline" size="sm" onClick={() => proxies.refetch()}><RefreshCw className={proxies.isFetching ? "animate-spin" : ""} />Refresh</Button>} />{proxies.isLoading ? <TableLoading /> : proxies.isError ? <QueryError onRetry={() => proxies.refetch()} /> : proxyRows.length === 0 ? <QueryEmpty title="No global proxies" description="Import a list or add a global source to populate the shared catalog." /> : <Table><TableHeader><TableRow><TableHead className="pl-5">Address</TableHead><TableHead>Protocol</TableHead><TableHead>Country</TableHead><TableHead>Health</TableHead><TableHead>Score</TableHead><TableHead>Latency</TableHead><TableHead>Success</TableHead></TableRow></TableHeader><TableBody>{proxyRows.map((proxy) => <TableRow key={proxy.id}><TableCell className="pl-5 font-mono text-xs">{proxy.host}:{proxy.port}</TableCell><TableCell className="uppercase">{proxy.protocol}</TableCell><TableCell>{proxy.countryCode}</TableCell><TableCell><StatusBadge status={proxy.status} /></TableCell><TableCell>{Math.round(proxy.score)}/100</TableCell><TableCell>{proxy.latencyMs ? `${Math.round(proxy.latencyMs)} ms` : "-"}</TableCell><TableCell>{formatPercent(proxy.successRate)}</TableCell></TableRow>)}</TableBody></Table>}</Card></TabsContent>
      <TabsContent value="sources"><Card className="overflow-hidden"><DataToolbar value={sourceSearch} onChange={setSourceSearch} placeholder="Search global sources" />{sources.isLoading ? <TableLoading /> : sources.isError ? <QueryError onRetry={() => sources.refetch()} /> : sourceRows.length === 0 ? <QueryEmpty title="No global sources" description="Add an authenticated HTTP feed for shared catalog inventory." /> : <Table><TableHeader><TableRow><TableHead className="pl-5">Source</TableHead><TableHead>Protocol</TableHead><TableHead>Status</TableHead><TableHead>Schedule</TableHead><TableHead>Last run</TableHead><TableHead className="w-12" /></TableRow></TableHeader><TableBody>{sourceRows.map((source) => <TableRow key={source.id}><TableCell className="pl-5"><p className="font-medium">{source.name}</p><p className="mt-0.5 max-w-md truncate text-xs text-muted-foreground">{source.url}</p></TableCell><TableCell className="uppercase">{source.defaultProtocol}</TableCell><TableCell><StatusBadge status={!source.enabled ? "disabled" : source.lastRunStatus ?? "unknown"} /></TableCell><TableCell>Every {source.refreshIntervalMinutes} min</TableCell><TableCell className="text-xs text-muted-foreground">{source.lastRunAt ? formatRelativeTime(source.lastRunAt) : "Never"}</TableCell><TableCell><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`${source.name} actions`}><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => void run(source)}><Play />Run now</DropdownMenuItem><DropdownMenuItem onSelect={() => void toggle(source)}>{source.enabled ? "Disable source" : "Enable source"}</DropdownMenuItem><DropdownMenuSeparator /><DropdownMenuItem variant="destructive" onSelect={() => void remove(source)}>Delete source</DropdownMenuItem></DropdownMenuContent></DropdownMenu></TableCell></TableRow>)}</TableBody></Table>}</Card></TabsContent>
    </Tabs></div>
  </>;
}
