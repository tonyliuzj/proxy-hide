"use client";

import { Activity, Clock3, DatabaseZap, Download, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { MetricCard } from "@/components/metric-card";
import { PageHeader } from "@/components/page-header";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { TrafficChart } from "@/components/traffic-chart";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useResourceParams } from "@/hooks/use-resource-params";
import { useEndpoints, usePools, useTraffic } from "@/lib/api/resources";
import { formatBytes, formatNumber } from "@/lib/utils";

const rangeHours: Record<string, number> = { "24h": 24, "7d": 24 * 7, "30d": 24 * 30 };

export default function TrafficPage() {
  const { params, update } = useResourceParams({ range: "24h", endpoint: "all", pool: "all" });
  const endpoints = useEndpoints({ page_size: 100 });
  const pools = usePools({ page_size: 100 });
  const [anchor] = useState(() => Date.now());
  const start = useMemo(() => new Date(anchor - (rangeHours[params.range] ?? 24) * 60 * 60 * 1000).toISOString(), [anchor, params.range]);
  const query = useTraffic({ start, granularity: "hour", endpoint_id: params.endpoint === "all" ? undefined : params.endpoint, pool_id: params.pool === "all" ? undefined : params.pool });
  const successRate = query.data?.requests ? Math.round((query.data.successes / query.data.requests) * 1000) / 10 : 0;

  function exportCsv() {
    if (!query.data) return;
    const rows = ["bucket_start,requests,successes,failures,bytes_up,bytes_down,average_latency_ms", ...query.data.points.map((point) => [point.bucketStart, point.requests, point.successes, point.failures, point.bytesUp, point.bytesDown, point.averageLatencyMs].join(","))];
    const url = URL.createObjectURL(new Blob([rows.join("\n")], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `proxy-hide-traffic-${params.range}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return <>
    <PageHeader title="Traffic" description="Operational aggregates only; destinations, headers, and bodies are never retained." actions={<><Button variant="outline" size="sm" onClick={exportCsv} disabled={!query.data?.points.length}><Download />Export CSV</Button><Button variant="outline" size="sm" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw className={query.isFetching ? "animate-spin" : ""} />Refresh</Button></>} />
    <div className="space-y-5 p-4 sm:p-6">
      <div className="flex flex-wrap gap-2">
        <Select value={params.range} onValueChange={(value) => update({ range: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="24h">Last 24 hours</SelectItem><SelectItem value="7d">Last 7 days</SelectItem><SelectItem value="30d">Last 30 days</SelectItem></SelectContent></Select>
        <Select value={params.endpoint} onValueChange={(value) => update({ endpoint: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All endpoints</SelectItem>{endpoints.data?.items.map((endpoint) => <SelectItem key={endpoint.id} value={endpoint.id}>{endpoint.name}</SelectItem>)}</SelectContent></Select>
        <Select value={params.pool} onValueChange={(value) => update({ pool: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All pools</SelectItem>{pools.data?.items.map((pool) => <SelectItem key={pool.id} value={pool.id}>{pool.name}</SelectItem>)}</SelectContent></Select>
      </div>

      {query.isLoading ? <TableLoading rows={8} /> : query.isError || !query.data ? <Card><QueryError onRetry={() => query.refetch()} /></Card> : <>
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Requests" value={formatNumber(query.data.requests)} hint={`${successRate}% successful`} icon={Activity} />
          <MetricCard label="Failures" value={formatNumber(query.data.failures)} hint="upstream and policy failures" icon={DatabaseZap} />
          <MetricCard label="Transferred" value={formatBytes(query.data.bytesUp + query.data.bytesDown)} hint={`${formatBytes(query.data.bytesUp)} up`} icon={Download} />
          <MetricCard label="Average latency" value={`${Math.round(query.data.averageLatencyMs)} ms`} hint="completed setup attempts" icon={Clock3} />
        </section>
        <Card><CardHeader><CardTitle>Gateway volume</CardTitle></CardHeader><CardContent className="pl-2"><TrafficChart data={query.data.points} /></CardContent></Card>
        <Card className="overflow-hidden">
          {query.data.points.length === 0 ? <QueryEmpty title="No traffic in this range" description="Aggregates appear after clients use a published endpoint." /> : <Table><TableHeader><TableRow><TableHead className="pl-5">Bucket</TableHead><TableHead>Requests</TableHead><TableHead>Successful</TableHead><TableHead>Failed</TableHead><TableHead>Transferred</TableHead><TableHead>Average latency</TableHead></TableRow></TableHeader><TableBody>{query.data.points.slice(-12).reverse().map((point) => <TableRow key={point.bucketStart}><TableCell className="pl-5 text-xs text-muted-foreground">{new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(new Date(point.bucketStart))}</TableCell><TableCell>{formatNumber(point.requests)}</TableCell><TableCell>{formatNumber(point.successes)}</TableCell><TableCell>{formatNumber(point.failures)}</TableCell><TableCell>{formatBytes(point.bytesUp + point.bytesDown)}</TableCell><TableCell>{Math.round(point.averageLatencyMs)} ms</TableCell></TableRow>)}</TableBody></Table>}
        </Card>
      </>}
    </div>
  </>;
}
