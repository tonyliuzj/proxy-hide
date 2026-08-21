"use client";

import { MoreHorizontal, Play, Target as TargetIcon, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { TargetDialog } from "@/components/dialogs/target-dialog";
import { DataToolbar } from "@/components/data-toolbar";
import { PageHeader } from "@/components/page-header";
import { PaginationBar } from "@/components/pagination-bar";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useResourceParams } from "@/hooks/use-resource-params";
import { api, ApiError } from "@/lib/api/client";
import { useTargets } from "@/lib/api/resources";
import type { Target } from "@/lib/api/types";
import { formatPercent, formatRelativeTime } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

export default function TargetsPage() {
  const { params, update } = useResourceParams();
  const query = useTargets({ page: Number(params.page), page_size: Number(params.page_size) });
  const queryClient = useQueryClient();
  const rows = (query.data?.items ?? []).filter((target) => `${target.name} ${target.url}`.toLowerCase().includes(params.q.toLowerCase()));

  async function run(target: Target) {
    try { await api.post(`/targets/${target.id}/check`); toast.success("Target check queued"); }
    catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not queue target check."); }
  }

  async function toggle(target: Target) {
    try {
      await api.patch(`/targets/${target.id}`, { enabled: !target.enabled });
      await queryClient.invalidateQueries({ queryKey: ["targets"] });
      toast.success(target.enabled ? "Target disabled" : "Target enabled");
    } catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not update the target."); }
  }

  async function remove(target: Target) {
    if (!window.confirm(`Delete ${target.name}? Filters referencing it must be updated first.`)) return;
    try {
      await api.delete(`/targets/${target.id}`);
      await queryClient.invalidateQueries({ queryKey: ["targets"] });
      toast.success("Target deleted");
    } catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not delete the target."); }
  }

  return <>
    <PageHeader title="Targets" description="Independent availability classifications used by filters and pools." actions={<TargetDialog />} />
    <div className="p-4 sm:p-6"><Card className="overflow-hidden">
      <DataToolbar value={params.q} onChange={(q) => update({ q })} placeholder="Search targets" />
      {query.isLoading ? <TableLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} /> : rows.length === 0 ? <QueryEmpty title="No targets" description="Add Google, Bing, or a custom URL to classify proxy availability." /> : <>
        <Table><TableHeader><TableRow><TableHead className="pl-5">Target</TableHead><TableHead>Type</TableHead><TableHead>Request</TableHead><TableHead>Expected status</TableHead><TableHead>Availability</TableHead><TableHead>Enabled</TableHead><TableHead>Last check</TableHead><TableHead className="w-12" /></TableRow></TableHeader><TableBody>{rows.map((target) => <TableRow key={target.id}>
          <TableCell className="pl-5"><div className="flex items-center gap-3"><div className="flex size-8 items-center justify-center rounded-md bg-muted"><TargetIcon className="size-4 text-muted-foreground" /></div><div className="min-w-0"><p className="font-medium">{target.name}</p><p className="max-w-xs truncate text-xs text-muted-foreground">{target.url}</p></div></div></TableCell>
          <TableCell><StatusBadge status={target.kind} /></TableCell><TableCell className="font-mono text-xs">{target.method}</TableCell><TableCell>{target.statusRanges.map(([low, high]) => `${low}-${high}`).join(", ")}</TableCell>
          <TableCell>{target.availabilityRate === null ? <span className="text-muted-foreground">Not reported</span> : <span className="font-medium tabular-nums">{formatPercent(target.availabilityRate)}</span>}</TableCell>
          <TableCell><Switch checked={target.enabled} onCheckedChange={() => void toggle(target)} aria-label={`${target.enabled ? "Disable" : "Enable"} ${target.name}`} /></TableCell>
          <TableCell className="text-xs text-muted-foreground">{target.lastCheckedAt ? formatRelativeTime(target.lastCheckedAt) : "Not reported"}</TableCell>
          <TableCell><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`${target.name} actions`}><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => void run(target)}><Play />Run now</DropdownMenuItem>{target.kind === "custom" ? <><DropdownMenuSeparator /><DropdownMenuItem variant="destructive" onSelect={() => void remove(target)}><Trash2 />Delete target</DropdownMenuItem></> : null}</DropdownMenuContent></DropdownMenu></TableCell>
        </TableRow>)}</TableBody></Table>
        <PaginationBar page={query.data?.page ?? 1} pageSize={query.data?.page_size ?? 25} total={query.data?.total ?? 0} onPageChange={(page) => update({ page: String(page) }, false)} />
      </>}
    </Card></div>
  </>;
}
