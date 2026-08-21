"use client";

import Link from "next/link";
import { Database, Globe2, ShieldCheck, UsersRound } from "lucide-react";
import { MetricCard } from "@/components/metric-card";
import { PageHeader } from "@/components/page-header";
import { QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAdminProxies, useAdminSources, useAdminWorkspaces } from "@/lib/api/resources";
import { formatNumber, formatRelativeTime } from "@/lib/utils";

export default function AdminOverviewPage() {
  const workspaces = useAdminWorkspaces({ page_size: 5 });
  const proxies = useAdminProxies({ page_size: 1 });
  const sources = useAdminSources({ page_size: 1 });
  const active = workspaces.data?.items.filter((workspace) => workspace.status === "active").length ?? 0;
  return <>
    <PageHeader title="Platform overview" description="Operator-owned workspaces and the shared proxy catalog." />
    <div className="space-y-5 p-4 sm:p-6">
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Workspaces" value={formatNumber(workspaces.data?.total ?? 0)} hint={`${active} active in this page`} icon={UsersRound} />
        <MetricCard label="Global proxies" value={formatNumber(proxies.data?.total ?? 0)} hint="shared masked catalog" icon={Globe2} />
        <MetricCard label="Global sources" value={formatNumber(sources.data?.total ?? 0)} hint="operator-managed feeds" icon={Database} />
        <MetricCard label="Tenant isolation" value="Enforced" hint="session-derived workspace scope" icon={ShieldCheck} />
      </section>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between"><CardTitle>Recent workspaces</CardTitle><Button asChild variant="outline" size="sm"><Link href="/admin/workspaces">Manage workspaces</Link></Button></CardHeader>
        <CardContent className="px-0 pb-0">{workspaces.isLoading ? <TableLoading /> : workspaces.isError ? <QueryError onRetry={() => workspaces.refetch()} /> : <Table><TableHeader><TableRow><TableHead className="pl-5">Workspace</TableHead><TableHead>Owner</TableHead><TableHead>Status</TableHead><TableHead>Created</TableHead></TableRow></TableHeader><TableBody>{workspaces.data?.items.map((workspace) => <TableRow key={workspace.id}><TableCell className="pl-5 font-medium">{workspace.name}<p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{workspace.slug}</p></TableCell><TableCell>{workspace.ownerEmail}</TableCell><TableCell><StatusBadge status={workspace.status} /></TableCell><TableCell className="text-xs text-muted-foreground">{formatRelativeTime(workspace.createdAt)}</TableCell></TableRow>)}</TableBody></Table>}</CardContent>
      </Card>
    </div>
  </>;
}
