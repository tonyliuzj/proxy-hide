"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, BookOpen, Eye, Globe2, LoaderCircle, Play, RefreshCw, Server, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ProxyImportDialog } from "@/components/dialogs/proxy-import-dialog";
import { GlobalCatalogDialog } from "@/components/dialogs/global-catalog-dialog";
import { MetricCard } from "@/components/metric-card";
import { PageHeader } from "@/components/page-header";
import { PaginationBar } from "@/components/pagination-bar";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api/client";
import { adaptProxy } from "@/lib/api/adapters";
import type { PageDto, ProxyDto } from "@/lib/api/dto";
import { useAdminWorkspace, useAdminWorkspaceGlobalPools, useAdminWorkspaceProxies } from "@/lib/api/resources";
import type { ProxyRecord } from "@/lib/api/types";
import { formatNumber, formatPercent } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

export default function AdminWorkspaceDetailPage() {
  const workspaceId = String(useParams<{ workspaceId: string }>().workspaceId);
  const [page, setPage] = useState(1);
  const [testingId, setTestingId] = useState<string>();
  const [globalMembers, setGlobalMembers] = useState<{ poolName: string; items: ProxyRecord[]; total: number }>();
  const workspace = useAdminWorkspace(workspaceId);
  const proxies = useAdminWorkspaceProxies(workspaceId, { page, page_size: 100 });
  const globalPools = useAdminWorkspaceGlobalPools(workspaceId, { page_size: 100 });
  const queryClient = useQueryClient();

  async function testProxy(proxy: ProxyRecord) {
    setTestingId(proxy.id);
    try {
      await api.post(`/admin/workspaces/${workspaceId}/proxies/${proxy.id}/check`);
      toast.success("Priority health check queued");
      window.setTimeout(() => void proxies.refetch(), 13_000);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not test the proxy.");
    } finally { setTestingId(undefined); }
  }

  async function remove(proxy: ProxyRecord) {
    if (!window.confirm(`Remove ${proxy.host}:${proxy.port} from this workspace?`)) return;
    try {
      await api.delete(`/admin/workspaces/${workspaceId}/proxies/${proxy.id}`);
      await Promise.all([proxies.refetch(), queryClient.invalidateQueries({ queryKey: ["admin", "workspaces"] })]);
      toast.success("Workspace proxy removed");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not remove the proxy.");
    }
  }

  async function removeGlobalPool(poolId: string, name: string) {
    if (!window.confirm(`Remove ${name} from this workspace?`)) return;
    try {
      await api.delete(`/admin/workspaces/${workspaceId}/global-pools/${poolId}`);
      await globalPools.refetch();
      toast.success("Filtered Global Catalog removed");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not remove the Global Catalog pool.");
    }
  }

  async function viewGlobalPool(poolId: string, poolName: string) {
    try {
      const result = await api.get<PageDto<ProxyDto>>(`/admin/workspaces/${workspaceId}/global-pools/${poolId}/proxies?page_size=100`);
      setGlobalMembers({ poolName, items: result.items.map(adaptProxy), total: result.total });
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not load the matching addresses.");
    }
  }

  if (workspace.isError) return <><PageHeader title="Workspace" /><div className="p-6"><Card><QueryError onRetry={() => workspace.refetch()} /></Card></div></>;
  const value = workspace.data;
  return <>
    <PageHeader title={value?.name ?? "Workspace"} description="Manage this workspace's private proxy inventory and global catalog access." actions={<><Button asChild variant="outline" size="sm"><Link href="/admin/workspaces"><ArrowLeft />Workspaces</Link></Button><Button asChild variant="outline" size="sm"><Link href={`/admin/workspaces/${workspaceId}/connection-guide`}><BookOpen />Connection guide</Link></Button>{value?.limits.global_catalog_enabled ? <GlobalCatalogDialog workspaceId={workspaceId} /> : null}<ProxyImportDialog workspaceId={workspaceId} /></>} />
    <div className="space-y-5 p-4 sm:p-6">
      <section className="grid gap-3 sm:grid-cols-3">
        <MetricCard label="Private proxies" value={formatNumber(proxies.data?.total ?? 0)} hint={`limit ${formatNumber(value?.limits.max_private_proxies ?? 0)}`} icon={Server} />
        <MetricCard label="Global catalog" value={value?.limits.global_catalog_enabled ? "Enabled" : "Disabled"} hint="shared catalog visibility" icon={Globe2} />
        <MetricCard label="Workspace status" value={value?.status ?? "Loading"} hint={value?.ownerEmail ?? "workspace owner"} icon={Server} />
      </section>
      <Card className="overflow-hidden">
        <CardHeader><CardTitle>Filtered Global Catalog</CardTitle><p className="text-sm text-muted-foreground">Each pool contains only addresses matching its filters. Membership is rechecked after every address health check.</p></CardHeader>
        <CardContent className="p-0">{globalPools.isLoading ? <TableLoading /> : globalPools.isError ? <QueryError onRetry={() => globalPools.refetch()} /> : !globalPools.data?.items.length ? <QueryEmpty title="No Global Catalog pools" description="Add the Global Catalog with country, protocol, score, and latency filters." /> : <Table><TableHeader><TableRow><TableHead className="pl-5">Pool</TableHead><TableHead>Strategy</TableHead><TableHead>Revision</TableHead><TableHead>Last checked</TableHead><TableHead className="w-24">Actions</TableHead></TableRow></TableHeader><TableBody>{globalPools.data.items.map((pool) => <TableRow key={pool.id}><TableCell className="pl-5 font-medium">{pool.name}</TableCell><TableCell>{pool.strategy.replaceAll("_", " ")}</TableCell><TableCell>{pool.currentRevision || "Pending"}</TableCell><TableCell>{pool.materializedAt ? new Date(pool.materializedAt).toLocaleString() : "Pending"}</TableCell><TableCell><div className="flex gap-1"><Button variant="ghost" size="icon-sm" onClick={() => void viewGlobalPool(pool.id, pool.name)} aria-label={`View ${pool.name} addresses`}><Eye /></Button><Button variant="ghost" size="icon-sm" onClick={() => void removeGlobalPool(pool.id, pool.name)} aria-label={`Remove ${pool.name}`}><Trash2 /></Button></div></TableCell></TableRow>)}</TableBody></Table>}</CardContent>
      </Card>
      {globalMembers ? <Card className="overflow-hidden"><CardHeader><CardTitle>{globalMembers.poolName} addresses ({formatNumber(globalMembers.total)})</CardTitle></CardHeader><CardContent className="p-0">{!globalMembers.items.length ? <QueryEmpty title="No matching addresses" description="Addresses appear after health checks confirm they satisfy every filter." /> : <Table><TableHeader><TableRow><TableHead className="pl-5">Address</TableHead><TableHead>Protocol</TableHead><TableHead>Country</TableHead><TableHead>Health</TableHead><TableHead>Score</TableHead><TableHead>Latency</TableHead></TableRow></TableHeader><TableBody>{globalMembers.items.map((proxy) => <TableRow key={proxy.id}><TableCell className="pl-5 font-mono text-xs">{proxy.host}:{proxy.port}</TableCell><TableCell className="uppercase">{proxy.protocol}</TableCell><TableCell>{proxy.countryCode}</TableCell><TableCell><StatusBadge status={proxy.status} /></TableCell><TableCell>{Math.round(proxy.score)}/100</TableCell><TableCell>{proxy.latencyMs ? `${Math.round(proxy.latencyMs)} ms` : "-"}</TableCell></TableRow>)}</TableBody></Table>}</CardContent></Card> : null}
      <Card className="overflow-hidden">
        <CardHeader className="flex flex-row items-center justify-between"><CardTitle>Private proxy inventory</CardTitle><Button variant="outline" size="sm" onClick={() => proxies.refetch()} disabled={proxies.isFetching}><RefreshCw className={proxies.isFetching ? "animate-spin" : ""} />Refresh</Button></CardHeader>
        <CardContent className="p-0">{proxies.isLoading ? <TableLoading /> : proxies.isError ? <QueryError onRetry={() => proxies.refetch()} /> : !proxies.data?.items.length ? <QueryEmpty title="No private proxies" description="Import proxies to make them available only to this workspace." /> : <><Table><TableHeader><TableRow><TableHead className="pl-5">Address</TableHead><TableHead>Protocol</TableHead><TableHead>Country</TableHead><TableHead>Health</TableHead><TableHead>Score</TableHead><TableHead>Latency</TableHead><TableHead>Success</TableHead><TableHead className="w-28">Actions</TableHead></TableRow></TableHeader><TableBody>{proxies.data.items.map((proxy) => <TableRow key={proxy.id}><TableCell className="pl-5 font-mono text-xs">{proxy.host}:{proxy.port}</TableCell><TableCell className="uppercase">{proxy.protocol}</TableCell><TableCell>{proxy.countryCode}</TableCell><TableCell><StatusBadge status={proxy.status} /></TableCell><TableCell>{Math.round(proxy.score)}/100</TableCell><TableCell>{proxy.latencyMs ? `${Math.round(proxy.latencyMs)} ms` : "-"}</TableCell><TableCell>{formatPercent(proxy.successRate)}</TableCell><TableCell><div className="flex gap-1"><Button variant="ghost" size="icon-sm" onClick={() => void testProxy(proxy)} disabled={testingId === proxy.id} aria-label={`Test ${proxy.host}`}>{testingId === proxy.id ? <LoaderCircle className="animate-spin" /> : <Play />}</Button><Button variant="ghost" size="icon-sm" onClick={() => void remove(proxy)} aria-label={`Remove ${proxy.host}`}><Trash2 /></Button></div></TableCell></TableRow>)}</TableBody></Table><PaginationBar page={proxies.data.page} pageSize={proxies.data.page_size} total={proxies.data.total} onPageChange={setPage} /></>}</CardContent>
      </Card>
    </div>
  </>;
}
