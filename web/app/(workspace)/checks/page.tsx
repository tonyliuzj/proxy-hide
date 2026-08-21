"use client";

import { ListChecks, RefreshCw, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/page-header";
import { PaginationBar } from "@/components/pagination-bar";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useResourceParams } from "@/hooks/use-resource-params";
import { api, ApiError } from "@/lib/api/client";
import { useJobs } from "@/lib/api/resources";
import type { JobRun } from "@/lib/api/types";
import { formatRelativeTime } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

export default function ChecksPage() {
  const { params, update } = useResourceParams({ status: "all", type: "all" });
  const query = useJobs({ page: Number(params.page), page_size: Number(params.page_size) });
  const queryClient = useQueryClient();
  const rows = (query.data?.items ?? []).filter((job) =>
    (params.status === "all" || job.status === params.status) &&
    (params.type === "all" || job.type === params.type),
  );

  async function retry(job: JobRun) {
    try {
      await api.post(`/checks/${job.id}/retry`);
      await queryClient.invalidateQueries({ queryKey: ["checks"] });
      toast.success("Check queued for retry");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not retry the check.");
    }
  }

  return <>
    <PageHeader title="Checks" description="Durable health, target, source, and pool jobs." actions={<Button variant="outline" size="sm" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw className={query.isFetching ? "animate-spin" : ""} />Refresh</Button>} />
    <div className="p-4 sm:p-6">
      <Card className="overflow-hidden">
        <div className="flex flex-wrap gap-2 border-b p-3">
          <Select value={params.status} onValueChange={(value) => update({ status: value })}><SelectTrigger size="sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All statuses</SelectItem><SelectItem value="queued">Queued</SelectItem><SelectItem value="running">Running</SelectItem><SelectItem value="succeeded">Succeeded</SelectItem><SelectItem value="failed">Failed</SelectItem><SelectItem value="dead">Dead letter</SelectItem></SelectContent></Select>
          <Select value={params.type} onValueChange={(value) => update({ type: value })}><SelectTrigger size="sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All job types</SelectItem><SelectItem value="check_proxy">General checks</SelectItem><SelectItem value="check_target">Target checks</SelectItem><SelectItem value="refresh_source">Source refreshes</SelectItem><SelectItem value="materialize_pool">Pool materialisation</SelectItem><SelectItem value="publish_snapshot">Snapshot publish</SelectItem></SelectContent></Select>
        </div>
        {query.isLoading ? <TableLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} /> : rows.length === 0 ? <QueryEmpty title="No matching jobs" description="Scheduled and manually requested operations appear here." /> : <>
          <Table><TableHeader><TableRow><TableHead className="pl-5">Job</TableHead><TableHead>Status</TableHead><TableHead>Progress</TableHead><TableHead>Attempts</TableHead><TableHead>Error</TableHead><TableHead>Started</TableHead><TableHead>Finished</TableHead><TableHead className="w-12" /></TableRow></TableHeader>
            <TableBody>{rows.map((job) => <TableRow key={job.id}>
              <TableCell className="pl-5"><div className="flex items-center gap-3"><div className="flex size-8 items-center justify-center rounded-md bg-muted"><ListChecks className="size-4 text-muted-foreground" /></div><div><p className="font-medium capitalize">{job.type.replaceAll("_", " ")}</p><p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{job.id.slice(0, 12)}</p></div></div></TableCell>
              <TableCell><StatusBadge status={job.status} /></TableCell>
              <TableCell className="tabular-nums">{job.progressTotal ? `${job.progressCurrent} / ${job.progressTotal}` : "-"}</TableCell>
              <TableCell>{job.attempt} / {job.maxAttempts}</TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">{job.errorCode ?? "-"}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{job.startedAt ? formatRelativeTime(job.startedAt) : "Not started"}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{job.finishedAt ? formatRelativeTime(job.finishedAt) : "-"}</TableCell>
              <TableCell>{job.status === "failed" || job.status === "dead" ? <Button variant="ghost" size="icon-sm" onClick={() => void retry(job)} aria-label={`Retry ${job.type}`}><RotateCcw /></Button> : null}</TableCell>
            </TableRow>)}</TableBody>
          </Table>
          <PaginationBar page={query.data?.page ?? 1} pageSize={query.data?.page_size ?? 25} total={query.data?.total ?? 0} onPageChange={(page) => update({ page: String(page) }, false)} />
        </>}
      </Card>
    </div>
  </>;
}
