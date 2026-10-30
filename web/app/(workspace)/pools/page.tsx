"use client";

import { Link2, MoreHorizontal, PauseCircle, Play, PlayCircle, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PoolDialog } from "@/components/dialogs/pool-dialog";
import { PoolListLinksDialog } from "@/components/dialogs/pool-list-links-dialog";
import { DataToolbar } from "@/components/data-toolbar";
import { PageHeader } from "@/components/page-header";
import { PaginationBar } from "@/components/pagination-bar";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useState } from "react";
import { useResourceParams } from "@/hooks/use-resource-params";
import { api, ApiError } from "@/lib/api/client";
import { strategyLabel } from "@/lib/api/strategies";
import { useFilters, usePools } from "@/lib/api/resources";
import type { Pool } from "@/lib/api/types";
import { formatRelativeTime } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

export default function PoolsPage() {
  const { params, update } = useResourceParams();
  const query = usePools({ page: Number(params.page), page_size: Number(params.page_size) });
  const filters = useFilters({ page_size: 100 });
  const queryClient = useQueryClient();
  const [sharePool, setSharePool] = useState<Pool>();
  const filterNames = new Map(filters.data?.items.map((filter) => [filter.id, filter.name]));
  const rows = (query.data?.items ?? []).filter((pool) => `${pool.name} ${filterNames.get(pool.filterName) ?? ""}`.toLowerCase().includes(params.q.toLowerCase()));

  async function materialize(pool: Pool) {
    try { await api.post(`/pools/${pool.id}/materialize`); toast.success("Pool materialisation queued"); }
    catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not queue materialisation."); }
  }

  async function toggle(pool: Pool) {
    try {
      await api.patch(`/pools/${pool.id}`, { enabled: !pool.enabled });
      await queryClient.invalidateQueries({ queryKey: ["pools"] });
      toast.success(pool.enabled ? "Pool disabled" : "Pool enabled");
    } catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not update the pool."); }
  }

  async function remove(pool: Pool) {
    if (!window.confirm(`Delete ${pool.name}? Endpoints must be deleted first.`)) return;
    try {
      await api.delete(`/pools/${pool.id}`);
      await queryClient.invalidateQueries({ queryKey: ["pools"] });
      toast.success("Pool deleted");
    } catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not delete the pool."); }
  }

  return <>
    <PageHeader title="Pools" description="Materialised proxy sets with deterministic rotation behavior." actions={<PoolDialog />} />
    <div className="p-4 sm:p-6"><Card className="overflow-hidden">
      <DataToolbar value={params.q} onChange={(q) => update({ q })} placeholder="Search pools" actions={<Button variant="outline" size="sm" onClick={() => query.refetch()}><RefreshCw className={query.isFetching ? "animate-spin" : ""} />Refresh revisions</Button>} />
      {query.isLoading ? <TableLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} /> : rows.length === 0 ? <QueryEmpty title="No pools" description="Create a filter first, then materialise it into a routable pool." /> : <>
        <Table><TableHeader><TableRow><TableHead className="pl-5">Pool</TableHead><TableHead>Filter</TableHead><TableHead>Catalog</TableHead><TableHead>Rotation</TableHead><TableHead>Revision</TableHead><TableHead>Members</TableHead><TableHead>Status</TableHead><TableHead>Materialised</TableHead><TableHead className="w-12" /></TableRow></TableHeader><TableBody>{rows.map((pool) => <TableRow key={pool.id}>
          <TableCell className="pl-5 font-medium">{pool.name}</TableCell>
          <TableCell>{filterNames.get(pool.filterName) ?? <span className="font-mono text-xs">{pool.filterName.slice(0, 8)}</span>}</TableCell>
          <TableCell><Badge variant="outline" className="capitalize">{pool.catalogSelection}</Badge></TableCell><TableCell>{strategyLabel(pool.strategy)}</TableCell><TableCell className="font-mono text-xs">{pool.currentRevision || "Pending"}</TableCell>
          <TableCell>{pool.eligibleCount === null ? <span className="text-muted-foreground">Not reported</span> : <span className="font-semibold tabular-nums">{pool.eligibleCount}</span>}</TableCell><TableCell><StatusBadge status={!pool.enabled ? "disabled" : pool.currentRevision ? "healthy" : "queued"} /></TableCell><TableCell className="text-xs text-muted-foreground">{formatRelativeTime(pool.updatedAt)}</TableCell>
          <TableCell><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`${pool.name} actions`}><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => void materialize(pool)}><Play />Materialise now</DropdownMenuItem><DropdownMenuItem onSelect={() => void toggle(pool)}>{pool.enabled ? <PauseCircle /> : <PlayCircle />}{pool.enabled ? "Disable pool" : "Enable pool"}</DropdownMenuItem><DropdownMenuItem onSelect={() => setSharePool(pool)}><Link2 />Share list link</DropdownMenuItem><DropdownMenuSeparator /><DropdownMenuItem variant="destructive" onSelect={() => void remove(pool)}><Trash2 />Delete pool</DropdownMenuItem></DropdownMenuContent></DropdownMenu></TableCell>
        </TableRow>)}</TableBody></Table>
        <PaginationBar page={query.data?.page ?? 1} pageSize={query.data?.page_size ?? 25} total={query.data?.total ?? 0} onPageChange={(page) => update({ page: String(page) }, false)} />
      </>}
    </Card></div>
    {sharePool ? <PoolListLinksDialog pool={sharePool} onClose={() => setSharePool(undefined)} /> : null}
  </>;
}
