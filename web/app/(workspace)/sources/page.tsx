"use client";

import { MoreHorizontal, Play, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { SourceDialog } from "@/components/dialogs/source-dialog";
import { DataToolbar } from "@/components/data-toolbar";
import { PageHeader } from "@/components/page-header";
import { PaginationBar } from "@/components/pagination-bar";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useResourceParams } from "@/hooks/use-resource-params";
import { api, ApiError } from "@/lib/api/client";
import { useSources } from "@/lib/api/resources";
import type { Source } from "@/lib/api/types";
import { formatRelativeTime } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

function host(url: string) {
  try { return new URL(url).host; } catch { return url; }
}

export default function SourcesPage() {
  const { params, update } = useResourceParams();
  const query = useSources({ page: Number(params.page), page_size: Number(params.page_size) });
  const queryClient = useQueryClient();
  const rows = (query.data?.items ?? []).filter((source) => `${source.name} ${source.url}`.toLowerCase().includes(params.q.toLowerCase()));

  async function run(source: Source) {
    try { await api.post(`/sources/${source.id}/run`); toast.success("Source refresh queued"); }
    catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not queue source refresh."); }
  }

  async function toggle(source: Source) {
    try {
      await api.patch(`/sources/${source.id}`, { enabled: !source.enabled });
      await queryClient.invalidateQueries({ queryKey: ["sources"] });
      toast.success(source.enabled ? "Source disabled" : "Source enabled");
    } catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not update the source."); }
  }

  async function remove(source: Source) {
    if (!window.confirm(`Delete ${source.name}? Existing routes are removed by inventory reconciliation.`)) return;
    try {
      await api.delete(`/sources/${source.id}`);
      await queryClient.invalidateQueries({ queryKey: ["sources"] });
      toast.success("Source deleted");
    } catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not delete the source."); }
  }

  return <>
    <PageHeader title="Sources" description="Scheduled private feeds that maintain proxy inventory." actions={<SourceDialog />} />
    <div className="p-4 sm:p-6"><Card className="overflow-hidden">
      <DataToolbar value={params.q} onChange={(q) => update({ q })} placeholder="Search sources" actions={<Button variant="outline" size="sm" onClick={() => query.refetch()}><RefreshCw className={query.isFetching ? "animate-spin" : ""} />Refresh</Button>} />
      {query.isLoading ? <TableLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} /> : rows.length === 0 ? <QueryEmpty title="No sources" description="Add a remote feed to refresh private proxy inventory automatically." /> : <>
        <Table><TableHeader><TableRow><TableHead className="pl-5">Source</TableHead><TableHead>Protocol</TableHead><TableHead>Status</TableHead><TableHead>Inventory</TableHead><TableHead>Schedule</TableHead><TableHead>Last run</TableHead><TableHead className="w-12" /></TableRow></TableHeader><TableBody>{rows.map((source) => <TableRow key={source.id}>
          <TableCell className="pl-5"><p className="font-medium">{source.name}</p><p className="mt-0.5 text-xs text-muted-foreground">{host(source.url)}</p></TableCell>
          <TableCell className="text-xs font-medium uppercase">{source.defaultProtocol}</TableCell>
          <TableCell><StatusBadge status={!source.enabled ? "disabled" : source.lastRunStatus ?? "unknown"} /></TableCell>
          <TableCell>{source.proxyCount === null ? <span className="text-muted-foreground">Not reported</span> : <><span className="font-medium tabular-nums">{source.healthyCount}</span><span className="text-muted-foreground"> / {source.proxyCount} healthy</span></>}</TableCell>
          <TableCell>Every {source.refreshIntervalMinutes} min</TableCell>
          <TableCell className="text-xs text-muted-foreground">{source.lastRunAt ? formatRelativeTime(source.lastRunAt) : "Never"}</TableCell>
          <TableCell><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`${source.name} actions`}><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => void run(source)}><Play />Run now</DropdownMenuItem><DropdownMenuItem onSelect={() => void toggle(source)}>{source.enabled ? "Disable source" : "Enable source"}</DropdownMenuItem><DropdownMenuSeparator /><DropdownMenuItem variant="destructive" onSelect={() => void remove(source)}><Trash2 />Delete source</DropdownMenuItem></DropdownMenuContent></DropdownMenu></TableCell>
        </TableRow>)}</TableBody></Table>
        <PaginationBar page={query.data?.page ?? 1} pageSize={query.data?.page_size ?? 25} total={query.data?.total ?? 0} onPageChange={(page) => update({ page: String(page) }, false)} />
      </>}
    </Card></div>
  </>;
}
