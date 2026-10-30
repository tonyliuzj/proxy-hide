"use client";

import { Globe2, MoreHorizontal, RefreshCw, RotateCw, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { CopyButton } from "@/components/copy-button";
import { EndpointCredentialsDialog } from "@/components/dialogs/endpoint-credentials-dialog";
import { EndpointDialog } from "@/components/dialogs/endpoint-dialog";
import { PageHeader } from "@/components/page-header";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { adaptEndpointCredentials } from "@/lib/api/adapters";
import { api, ApiError } from "@/lib/api/client";
import type { EndpointCreatedDto } from "@/lib/api/dto";
import { useEndpoints, usePools } from "@/lib/api/resources";
import { strategyLabel } from "@/lib/api/strategies";
import type { Endpoint, EndpointCredentials } from "@/lib/api/types";
import { formatRelativeTime } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

export default function EndpointsPage() {
  const endpoints = useEndpoints();
  const pools = usePools();
  const queryClient = useQueryClient();
  const [credentials, setCredentials] = useState<EndpointCredentials>();
  const poolNames = new Map(pools.data?.items.map((pool) => [pool.id, pool.name]));
  const poolStrategies = new Map(pools.data?.items.map((pool) => [pool.id, pool.strategy]));

  async function toggle(endpoint: Endpoint) {
    try {
      await api.patch(`/endpoints/${endpoint.id}`, { enabled: !endpoint.enabled });
      await queryClient.invalidateQueries({ queryKey: ["endpoints"] });
      toast.success(endpoint.enabled ? "Endpoint disabled" : "Endpoint enabled");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not update the endpoint.");
    }
  }

  async function rotate(endpoint: Endpoint) {
    if (!window.confirm(`Regenerate the secret for ${endpoint.name}? The existing secret will stop working immediately.`)) return;
    try {
      const dto = await api.post<EndpointCreatedDto>(`/endpoints/${endpoint.id}/regenerate-secret`);
      setCredentials(adaptEndpointCredentials(dto));
      await queryClient.invalidateQueries({ queryKey: ["endpoints"] });
      toast.success("Endpoint secret regenerated");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not regenerate the secret.");
    }
  }

  async function remove(endpoint: Endpoint) {
    if (!window.confirm(`Delete ${endpoint.name}? Clients using this endpoint will be rejected.`)) return;
    try {
      await api.delete(`/endpoints/${endpoint.id}`);
      await queryClient.invalidateQueries({ queryKey: ["endpoints"] });
      toast.success("Endpoint deleted");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not delete the endpoint.");
    }
  }

  return <>
    <PageHeader title="Endpoints" description="Addresses and logins that apps use to reach a pool, each with its own rotation." actions={<EndpointDialog onCredentials={setCredentials} />} />
    <div className="p-4 sm:p-6">
      <Card className="overflow-hidden">
        {endpoints.isLoading ? <TableLoading /> : endpoints.isError ? <QueryError onRetry={() => endpoints.refetch()} /> : !endpoints.data?.items.length ? <QueryEmpty title="No endpoints" description="Publish an endpoint to give an app an ip:port that routes to a pool." /> : <>
          <Table>
            <TableHeader><TableRow><TableHead className="pl-5">Endpoint</TableHead><TableHead>Connect with</TableHead><TableHead>Pool</TableHead><TableHead>Rotation</TableHead><TableHead>Client allowlist</TableHead><TableHead>Status</TableHead><TableHead>Secret rotated</TableHead><TableHead className="w-12" /></TableRow></TableHeader>
            <TableBody>{endpoints.data.items.map((endpoint) => <TableRow key={endpoint.id}>
              <TableCell className="pl-5"><div className="flex items-center gap-3"><div className="flex size-8 items-center justify-center rounded-md bg-muted"><Globe2 className="size-4 text-muted-foreground" /></div><div><p className="font-medium">{endpoint.name}</p><p className="mt-0.5 text-xs text-muted-foreground">{endpoint.listenPort ? "HTTP, CONNECT, SOCKS5" : "Shared gateway login"}</p></div></div></TableCell>
              <TableCell>{endpoint.proxyAddress ? <div className="flex items-center"><code className="text-xs">{endpoint.proxyAddress}</code><CopyButton value={endpoint.proxyAddress} label="Copy address" /></div> : <span className="font-mono text-xs">{endpoint.username}</span>}</TableCell>
              <TableCell>{poolNames.get(endpoint.poolName) ?? <span className="font-mono text-xs">{endpoint.poolName.slice(0, 8)}</span>}</TableCell>
              <TableCell>{endpoint.strategy ? strategyLabel(endpoint.strategy) : <span className="text-muted-foreground">{poolStrategies.get(endpoint.poolName) ? `Pool: ${strategyLabel(poolStrategies.get(endpoint.poolName)!)}` : "Pool setting"}</span>}</TableCell>
              <TableCell>{endpoint.ipAllowlist.length ? <div className="flex items-center gap-1"><ShieldCheck className="size-3.5 text-emerald-700" /><Badge variant="outline">{endpoint.ipAllowlist.length} CIDR{endpoint.ipAllowlist.length === 1 ? "" : "s"}</Badge></div> : <span className="text-muted-foreground">Any IP</span>}</TableCell>
              <TableCell><StatusBadge status={endpoint.enabled ? "active" : "disabled"} /></TableCell>
              <TableCell className="text-xs text-muted-foreground">{!endpoint.requireAuth ? "No secret" : endpoint.lastUsedAt ? formatRelativeTime(endpoint.lastUsedAt) : "At creation"}</TableCell>
              <TableCell><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`${endpoint.name} actions`}><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => void toggle(endpoint)}>{endpoint.enabled ? "Disable endpoint" : "Enable endpoint"}</DropdownMenuItem>{endpoint.requireAuth ? <DropdownMenuItem onSelect={() => void rotate(endpoint)}><RotateCw />Regenerate secret</DropdownMenuItem> : null}<DropdownMenuSeparator /><DropdownMenuItem variant="destructive" onSelect={() => void remove(endpoint)}><Trash2 />Delete endpoint</DropdownMenuItem></DropdownMenuContent></DropdownMenu></TableCell>
            </TableRow>)}</TableBody>
          </Table>
          <div className="flex items-center justify-between border-t px-4 py-3 text-xs text-muted-foreground"><span>{endpoints.data.total} endpoints</span><Button variant="outline" size="sm" onClick={() => endpoints.refetch()} disabled={endpoints.isFetching}><RefreshCw className={endpoints.isFetching ? "animate-spin" : ""} />Refresh</Button></div>
        </>}
      </Card>
    </div>
    <EndpointCredentialsDialog credentials={credentials} onClose={() => setCredentials(undefined)} />
  </>;
}
