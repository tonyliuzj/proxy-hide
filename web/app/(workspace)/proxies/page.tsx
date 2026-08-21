"use client";

import { MoreHorizontal, Play, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ProxyImportDialog } from "@/components/dialogs/proxy-import-dialog";
import { DataToolbar } from "@/components/data-toolbar";
import { PageHeader } from "@/components/page-header";
import { PaginationBar } from "@/components/pagination-bar";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useResourceParams } from "@/hooks/use-resource-params";
import { api, ApiError } from "@/lib/api/client";
import { useProxies } from "@/lib/api/resources";
import type { ProxyRecord } from "@/lib/api/types";
import { formatPercent } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

export default function ProxiesPage() {
  const { params, update } = useResourceParams({ protocol: "all", health: "all" });
  const query = useProxies({ page: Number(params.page), page_size: Number(params.page_size), protocol: params.protocol === "all" ? undefined : params.protocol, health: params.health === "all" ? undefined : params.health });
  const queryClient = useQueryClient();
  const rows = (query.data?.items ?? []).filter((proxy) => `${proxy.host} ${proxy.country} ${proxy.countryCode}`.toLowerCase().includes(params.q.toLowerCase()));

  async function check(proxy: ProxyRecord) {
    try {
      await api.post(`/proxies/${proxy.id}/check`);
      toast.success("Health check queued");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not queue the health check.");
    }
  }

  async function remove(proxy: ProxyRecord) {
    if (!window.confirm(`Remove ${proxy.host}:${proxy.port} from private inventory?`)) return;
    try {
      await api.delete(`/proxies/${proxy.id}`);
      await queryClient.invalidateQueries({ queryKey: ["proxies"] });
      toast.success("Proxy removed");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not remove the proxy.");
    }
  }

  return <>
    <PageHeader title="Proxies" description="Private inventory and eligible global catalog routes." actions={<><Button variant="outline" size="sm" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw className={query.isFetching ? "animate-spin" : ""} />Refresh</Button><ProxyImportDialog /></>} />
    <div className="p-4 sm:p-6"><Card className="overflow-hidden">
      <DataToolbar value={params.q} onChange={(q) => update({ q })} placeholder="Search host or country" filters={<><Select value={params.protocol} onValueChange={(protocol) => update({ protocol })}><SelectTrigger size="sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All protocols</SelectItem><SelectItem value="http">HTTP</SelectItem><SelectItem value="https">HTTPS</SelectItem><SelectItem value="socks4a">SOCKS4a</SelectItem><SelectItem value="socks5">SOCKS5</SelectItem></SelectContent></Select><Select value={params.health} onValueChange={(health) => update({ health })}><SelectTrigger size="sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All health</SelectItem><SelectItem value="healthy">Healthy</SelectItem><SelectItem value="degraded">Degraded</SelectItem><SelectItem value="unhealthy">Unhealthy</SelectItem><SelectItem value="unknown">Unknown</SelectItem></SelectContent></Select></>} />
      {query.isLoading ? <TableLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} /> : rows.length === 0 ? <QueryEmpty title="No matching proxies" description={query.data?.total ? "Adjust the search or filters to see more routes." : "Import a private list or configure a source to populate inventory."} /> : <>
        <Table><TableHeader><TableRow><TableHead className="pl-5">Address</TableHead><TableHead>Scope</TableHead><TableHead>Location</TableHead><TableHead>Health</TableHead><TableHead>Score</TableHead><TableHead>Latency</TableHead><TableHead>Success</TableHead><TableHead className="w-12" /></TableRow></TableHeader><TableBody>{rows.map((proxy) => <TableRow key={proxy.id}>
          <TableCell className="pl-5"><p className="font-mono text-xs font-medium">{proxy.port ? `${proxy.host}:${proxy.port}` : proxy.host}</p><p className="mt-0.5 text-[11px] uppercase text-muted-foreground">{proxy.protocol}</p></TableCell>
          <TableCell><StatusBadge status={proxy.sourceName === "Global catalog" ? "global" : "private"} /></TableCell>
          <TableCell><span className="font-medium">{proxy.countryCode}</span><span className="ml-2 text-xs text-muted-foreground">{proxy.country}</span></TableCell>
          <TableCell><StatusBadge status={proxy.status} /></TableCell>
          <TableCell><span className={proxy.score >= 85 ? "font-semibold text-emerald-700" : proxy.score < 50 ? "font-semibold text-red-700" : "font-semibold"}>{Math.round(proxy.score)}</span><span className="text-muted-foreground">/100</span></TableCell>
          <TableCell className="tabular-nums">{proxy.latencyMs ? `${Math.round(proxy.latencyMs)} ms` : "-"}</TableCell>
          <TableCell className="tabular-nums">{formatPercent(proxy.successRate)}</TableCell>
          <TableCell><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`${proxy.host} actions`}><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => void check(proxy)}><Play />Run health check</DropdownMenuItem>{proxy.sourceName !== "Global catalog" ? <><DropdownMenuSeparator /><DropdownMenuItem variant="destructive" onSelect={() => void remove(proxy)}><Trash2 />Remove proxy</DropdownMenuItem></> : null}</DropdownMenuContent></DropdownMenu></TableCell>
        </TableRow>)}</TableBody></Table>
        <PaginationBar page={query.data?.page ?? 1} pageSize={query.data?.page_size ?? 25} total={query.data?.total ?? 0} onPageChange={(page) => update({ page: String(page) }, false)} />
      </>}
    </Card></div>
  </>;
}
