"use client";

import { LoaderCircle, MoreHorizontal, Play, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ProxyImportDialog } from "@/components/dialogs/proxy-import-dialog";
import { GlobalCatalogDialog } from "@/components/dialogs/global-catalog-dialog";
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
import { useProxies, useTargets } from "@/lib/api/resources";
import type { ProxyRecord } from "@/lib/api/types";
import { formatPercent } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

export default function ProxiesPage() {
  const { params, update } = useResourceParams({ protocol: "all", health: "all" });
  const query = useProxies({ page: Number(params.page), page_size: Number(params.page_size), protocol: params.protocol === "all" ? undefined : params.protocol, health: params.health === "all" ? undefined : params.health });
  const queryClient = useQueryClient();
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testingAll, setTestingAll] = useState(false);
  const [testTarget, setTestTarget] = useState("connectivity");
  const targets = useTargets({ page_size: 100 });
  const rows = (query.data?.items ?? []).filter((proxy) => `${proxy.host} ${proxy.country} ${proxy.countryCode}`.toLowerCase().includes(params.q.toLowerCase()));

  async function check(proxy: ProxyRecord) {
    setTestingId(proxy.id);
    try {
      await api.post(`/proxies/${proxy.id}/check${testTarget === "connectivity" ? "" : `?target_id=${testTarget}`}`);
      toast.success(`${testTarget === "connectivity" ? "Connectivity" : targets.data?.items.find((target) => target.id === testTarget)?.name ?? "Target"} check queued`);
      window.setTimeout(() => void query.refetch(), 13_000);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not queue the health check.");
    } finally {
      setTestingId(null);
    }
  }

  async function checkAll() {
    setTestingAll(true);
    try {
      if (testTarget !== "connectivity") {
        await api.post(`/targets/${testTarget}/check`);
        toast.success("Selected searchable target check queued");
      } else {
        const result = await api.post<{ queued: number }>("/proxies/check-all");
        toast.success(result.queued ? `${result.queued} connectivity checks queued` : "No proxies to test");
      }
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not queue all health checks.");
    } finally {
      setTestingAll(false);
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
    <PageHeader title="Proxies" description="Private inventory and eligible global catalog routes." actions={<><Select value={testTarget} onValueChange={setTestTarget}><SelectTrigger size="sm" className="w-48"><SelectValue placeholder="Choose test" /></SelectTrigger><SelectContent><SelectItem value="connectivity">Connectivity</SelectItem>{targets.data?.items.filter((target) => target.enabled).map((target) => <SelectItem key={target.id} value={target.id}>{target.name}</SelectItem>)}</SelectContent></Select><Button variant="outline" size="sm" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw className={query.isFetching ? "animate-spin" : ""} />Refresh</Button><Button variant="outline" size="sm" onClick={() => void checkAll()} disabled={testingAll || !query.data?.total}>{testingAll ? <LoaderCircle className="animate-spin" /> : <Play />}Test all</Button><GlobalCatalogDialog /><ProxyImportDialog /></>} />
    <div className="p-4 sm:p-6"><Card className="overflow-hidden">
      <DataToolbar value={params.q} onChange={(q) => update({ q })} placeholder="Search host or country" filters={<><Select value={params.protocol} onValueChange={(protocol) => update({ protocol })}><SelectTrigger size="sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All protocols</SelectItem><SelectItem value="http">HTTP</SelectItem><SelectItem value="https">HTTPS</SelectItem><SelectItem value="socks4a">SOCKS4a</SelectItem><SelectItem value="socks5">SOCKS5</SelectItem></SelectContent></Select><Select value={params.health} onValueChange={(health) => update({ health })}><SelectTrigger size="sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All health</SelectItem><SelectItem value="healthy">Healthy</SelectItem><SelectItem value="degraded">Degraded</SelectItem><SelectItem value="unhealthy">Unhealthy</SelectItem><SelectItem value="unknown">Unknown</SelectItem></SelectContent></Select></>} />
      {query.isLoading ? <TableLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} /> : rows.length === 0 ? <QueryEmpty title="No matching proxies" description={query.data?.total ? "Adjust the search or filters to see more routes." : "Import a private list or configure a source to populate inventory."} /> : <>
        <Table><TableHeader><TableRow><TableHead className="pl-5">Address</TableHead><TableHead>Scope</TableHead><TableHead>Location</TableHead><TableHead>Health</TableHead><TableHead>Score</TableHead><TableHead>Latency</TableHead><TableHead>Success</TableHead><TableHead className="w-12" /></TableRow></TableHeader><TableBody>{rows.map((proxy) => <TableRow key={proxy.id}>
          <TableCell className="pl-5"><div className="flex items-center gap-2"><div><p className="font-mono text-xs font-medium">{proxy.port ? `${proxy.host}:${proxy.port}` : proxy.host}</p><p className="mt-0.5 text-[11px] uppercase text-muted-foreground">{proxy.protocol}</p></div><Button variant="outline" size="sm" className="h-7 px-2" onClick={() => void check(proxy)} disabled={testingId === proxy.id || testingAll}>{testingId === proxy.id ? <LoaderCircle className="animate-spin" /> : <Play />}Test</Button></div></TableCell>
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
