"use client";

import { Activity, Clock3, ListChecks, PlayCircle, RefreshCw } from "lucide-react";
import { MetricCard } from "@/components/metric-card";
import { PageHeader } from "@/components/page-header";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAdminQueue } from "@/lib/api/resources";
import { formatNumber, formatRelativeTime } from "@/lib/utils";

export default function AdminStatisticsPage() {
  const queue = useAdminQueue();
  return <>
    <PageHeader title="Statistics" description="Current platform-wide background job queue." actions={<Button variant="outline" size="sm" onClick={() => queue.refetch()} disabled={queue.isFetching}><RefreshCw className={queue.isFetching ? "animate-spin" : ""} />Refresh</Button>} />
    <div className="space-y-5 p-4 sm:p-6">
      <section className="grid gap-3 sm:grid-cols-3">
        <MetricCard label="Current queue" value={formatNumber(queue.data?.total ?? 0)} hint="queued and running jobs" icon={Activity} />
        <MetricCard label="Waiting" value={formatNumber(queue.data?.queued ?? 0)} hint="not started" icon={Clock3} />
        <MetricCard label="Running" value={formatNumber(queue.data?.running ?? 0)} hint="being processed" icon={PlayCircle} />
      </section>
      <Card className="overflow-hidden">
        {queue.isLoading ? <TableLoading /> : queue.isError ? <QueryError onRetry={() => queue.refetch()} /> : !queue.data?.items.length ? <QueryEmpty title="Queue is empty" description="There are no queued or running background jobs." /> : <Table>
          <TableHeader><TableRow><TableHead className="pl-5">Job</TableHead><TableHead>Status</TableHead><TableHead>Workspace</TableHead><TableHead>Progress</TableHead><TableHead>Attempt</TableHead><TableHead>Queued</TableHead><TableHead>Started</TableHead></TableRow></TableHeader>
          <TableBody>{queue.data.items.map((job) => <TableRow key={job.id}>
            <TableCell className="pl-5"><div className="flex items-center gap-3"><div className="flex size-8 items-center justify-center rounded-md bg-muted"><ListChecks className="size-4 text-muted-foreground" /></div><div><p className="font-medium capitalize">{job.type.replaceAll("_", " ")}</p><p className="font-mono text-[11px] text-muted-foreground">{job.id.slice(0, 12)}</p></div></div></TableCell>
            <TableCell><StatusBadge status={job.status} /></TableCell>
            <TableCell className="font-mono text-xs text-muted-foreground">{job.workspaceId?.slice(0, 12) ?? "Global"}</TableCell>
            <TableCell className="tabular-nums">{job.progressTotal ? `${job.progressCurrent} / ${job.progressTotal}` : "-"}</TableCell>
            <TableCell className="tabular-nums">{job.attempt + 1} / {job.maxAttempts}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{formatRelativeTime(job.createdAt)}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{job.startedAt ? formatRelativeTime(job.startedAt) : "Not started"}</TableCell>
          </TableRow>)}</TableBody>
        </Table>}
      </Card>
    </div>
  </>;
}
