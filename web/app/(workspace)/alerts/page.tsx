"use client";

import { toast } from "sonner";
import { PageHeader } from "@/components/page-header";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { PageDto } from "@/lib/api/dto";
import { useApiQuery } from "@/lib/api/hooks";
import { formatRelativeTime } from "@/lib/utils";

interface Alert { id: string; severity: string; status: string; title: string; message: string; created_at: string }

export default function AlertsPage() {
  const query = useApiQuery<PageDto<Alert>>(["alerts"], "/alerts?page_size=100");
  async function setStatus(id: string, status: "acknowledged" | "resolved") {
    await api.patch(`/alerts/${id}`, { status }); await query.refetch(); toast.success(`Alert ${status}`);
  }
  return <><PageHeader title="Alerts" description="Actionable failures and operational health warnings." /><div className="p-4 sm:p-6"><Card className="overflow-hidden">{query.isLoading ? <TableLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} /> : !query.data?.items.length ? <QueryEmpty title="No alerts" description="Operational failures will appear here." /> : <Table><TableHeader><TableRow><TableHead className="pl-5">Severity</TableHead><TableHead>Alert</TableHead><TableHead>Status</TableHead><TableHead>Time</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader><TableBody>{query.data.items.map((item) => <TableRow key={item.id}><TableCell className="pl-5"><StatusBadge status={item.severity} /></TableCell><TableCell><p className="font-medium">{item.title}</p><p className="max-w-xl text-xs text-muted-foreground">{item.message}</p></TableCell><TableCell><StatusBadge status={item.status} /></TableCell><TableCell className="text-xs text-muted-foreground">{formatRelativeTime(item.created_at)}</TableCell><TableCell className="space-x-2 text-right">{item.status === "open" ? <Button size="sm" variant="outline" onClick={() => void setStatus(item.id, "acknowledged")}>Acknowledge</Button> : null}{item.status !== "resolved" ? <Button size="sm" onClick={() => void setStatus(item.id, "resolved")}>Resolve</Button> : null}</TableCell></TableRow>)}</TableBody></Table>}</Card></div></>;
}
