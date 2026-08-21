"use client";

import Link from "next/link";
import { Activity, Boxes, Globe2, Network, RefreshCw } from "lucide-react";
import { MetricCard } from "@/components/metric-card";
import { PageHeader } from "@/components/page-header";
import { QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { TrafficChart } from "@/components/traffic-chart";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDashboardSummary, usePools, useTraffic } from "@/lib/api/resources";
import { formatNumber, formatRelativeTime } from "@/lib/utils";

export default function DashboardPage() {
  const summary = useDashboardSummary();
  const traffic = useTraffic();
  const pools = usePools({ page_size: 5 });
  const refreshing = summary.isFetching || traffic.isFetching || pools.isFetching;

  function refresh() {
    void Promise.all([summary.refetch(), traffic.refetch(), pools.refetch()]);
  }

  if (summary.isLoading) {
    return <><PageHeader title="Dashboard" description="Current proxy health and gateway activity for this workspace." /><div className="p-4 sm:p-6"><TableLoading rows={8} /></div></>;
  }

  if (summary.isError || !summary.data) {
    return <><PageHeader title="Dashboard" /><div className="p-4 sm:p-6"><Card><QueryError onRetry={refresh} /></Card></div></>;
  }

  const successRate = summary.data.requests24h
    ? Math.round((summary.data.successfulRequests24h / summary.data.requests24h) * 1000) / 10
    : 0;
  const metrics = [
    { label: "Healthy proxies", value: formatNumber(summary.data.proxiesHealthy), hint: `of ${formatNumber(summary.data.proxiesTotal)} eligible`, icon: Network },
    { label: "Requests (24h)", value: formatNumber(summary.data.requests24h), hint: `${successRate}% successful`, icon: Activity },
    { label: "Published endpoints", value: formatNumber(summary.data.endpointsTotal), hint: `${summary.data.activeJobs} active jobs`, icon: Globe2 },
    { label: "Ready pools", value: `${summary.data.poolsReady}/${summary.data.poolsTotal}`, hint: "latest materialised revisions", icon: Boxes },
  ];

  return <>
    <PageHeader title="Dashboard" description="Current proxy health and gateway activity for this workspace." actions={<Button variant="outline" size="sm" onClick={refresh} disabled={refreshing}><RefreshCw className={refreshing ? "animate-spin" : ""} />Refresh</Button>} />
    <div className="space-y-5 p-4 sm:p-6">
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((metric) => <MetricCard key={metric.label} {...metric} />)}
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,1fr)]">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <div><CardTitle>Request volume</CardTitle><p className="mt-1 text-xs text-muted-foreground">Requests and failures, last 24 hours</p></div>
            <Button asChild variant="ghost" size="sm"><Link href="/traffic">View traffic</Link></Button>
          </CardHeader>
          <CardContent className="pl-2">{traffic.data ? <TrafficChart data={traffic.data.points} /> : <TableLoading rows={4} />}</CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <div><CardTitle>Pool readiness</CardTitle><p className="mt-1 text-xs text-muted-foreground">Latest materialised revisions</p></div>
            <Boxes className="size-4 text-muted-foreground" />
          </CardHeader>
          <CardContent className="px-0 pb-0">
            <Table><TableHeader><TableRow><TableHead className="pl-5">Pool</TableHead><TableHead>Revision</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
              <TableBody>{pools.data?.items.map((pool) => <TableRow key={pool.id}><TableCell className="pl-5"><Link href="/pools" className="font-medium hover:underline">{pool.name}</Link><p className="mt-0.5 text-xs capitalize text-muted-foreground">{pool.strategy.replaceAll("_", " ")}</p></TableCell><TableCell className="font-mono text-xs">{pool.currentRevision || "Pending"}</TableCell><TableCell><StatusBadge status={!pool.enabled ? "disabled" : pool.currentRevision ? "healthy" : "queued"} /></TableCell></TableRow>)}</TableBody>
            </Table>
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <div><CardTitle>Recent operations</CardTitle><p className="mt-1 text-xs text-muted-foreground">Checker, source, and materialisation jobs</p></div>
          <Button asChild variant="outline" size="sm"><Link href="/checks">Open checks</Link></Button>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Table><TableHeader><TableRow><TableHead className="pl-5">Type</TableHead><TableHead>Status</TableHead><TableHead>Progress</TableHead><TableHead>Attempt</TableHead><TableHead>Error</TableHead><TableHead className="pr-5 text-right">Created</TableHead></TableRow></TableHeader>
            <TableBody>{summary.data.recentChecks.map((job) => <TableRow key={job.id}><TableCell className="pl-5 capitalize">{job.type.replaceAll("_", " ")}</TableCell><TableCell><StatusBadge status={job.status} /></TableCell><TableCell className="tabular-nums">{job.progressTotal ? `${job.progressCurrent}/${job.progressTotal}` : "-"}</TableCell><TableCell>{job.attempt}/{job.maxAttempts}</TableCell><TableCell className="font-mono text-xs text-muted-foreground">{job.errorCode ?? "-"}</TableCell><TableCell className="pr-5 text-right text-xs text-muted-foreground">{formatRelativeTime(job.createdAt)}</TableCell></TableRow>)}</TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  </>;
}
