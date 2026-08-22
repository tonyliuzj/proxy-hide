"use client";

import { KeyRound, MoreHorizontal, PauseCircle, PlayCircle, Settings2, UsersRound } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { CreateWorkspaceDialog, ManageWorkspaceDialog, ReplacePasswordDialog } from "@/components/dialogs/admin-workspace-dialogs";
import { DataToolbar } from "@/components/data-toolbar";
import { PageHeader } from "@/components/page-header";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api/client";
import { useAdminWorkspaces } from "@/lib/api/resources";
import type { AdminWorkspace } from "@/lib/api/types";
import { formatNumber, formatRelativeTime } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

export default function AdminWorkspacesPage() {
  const [search, setSearch] = useState("");
  const [managing, setManaging] = useState<AdminWorkspace>();
  const [replacingPassword, setReplacingPassword] = useState<AdminWorkspace>();
  const query = useAdminWorkspaces({ page_size: 100 });
  const queryClient = useQueryClient();
  const rows = (query.data?.items ?? []).filter((workspace) => `${workspace.name} ${workspace.slug} ${workspace.ownerEmail}`.toLowerCase().includes(search.toLowerCase()));

  async function setStatus(workspace: AdminWorkspace) {
    const next = workspace.status === "active" ? "suspended" : "active";
    const verb = next === "suspended" ? "Suspend" : "Reactivate";
    if (!window.confirm(`${verb} ${workspace.name}? ${next === "suspended" ? "Existing owner sessions will be revoked and gateway authentication will fail." : "Owner access will be restored."}`)) return;
    try {
      await api.patch(`/admin/workspaces/${workspace.id}`, { status: next });
      await queryClient.invalidateQueries({ queryKey: ["admin", "workspaces"] });
      toast.success(`Workspace ${next}`);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not change workspace status.");
    }
  }

  return <>
    <PageHeader title="Workspaces" description="Provision owners, enforce limits, and suspend tenant access." actions={<CreateWorkspaceDialog />} />
    <div className="p-4 sm:p-6"><Card className="overflow-hidden">
      <DataToolbar value={search} onChange={setSearch} placeholder="Search workspace or owner" />
      {query.isLoading ? <TableLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} /> : rows.length === 0 ? <QueryEmpty title="No matching workspaces" description="Provision a workspace to create its sole owner account." /> : <Table><TableHeader><TableRow><TableHead className="pl-5">Workspace</TableHead><TableHead>Owner</TableHead><TableHead>Status</TableHead><TableHead>Private proxies</TableHead><TableHead>Gateway limit</TableHead><TableHead>Created</TableHead><TableHead className="w-12" /></TableRow></TableHeader><TableBody>{rows.map((workspace) => <TableRow key={workspace.id}>
        <TableCell className="pl-5"><Link href={`/admin/workspaces/${workspace.id}`} className="flex items-center gap-3 hover:underline"><div className="flex size-8 items-center justify-center rounded-md bg-muted"><UsersRound className="size-4 text-muted-foreground" /></div><div><p className="font-medium">{workspace.name}</p><p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{workspace.slug}</p></div></Link></TableCell>
        <TableCell className="text-sm">{workspace.ownerEmail}</TableCell>
        <TableCell><StatusBadge status={workspace.status} /></TableCell>
        <TableCell className="tabular-nums">{formatNumber(workspace.proxies)} / {formatNumber(workspace.limits.max_private_proxies)}</TableCell>
        <TableCell className="tabular-nums">{formatNumber(workspace.limits.max_gateway_connections)} connections</TableCell>
        <TableCell className="text-xs text-muted-foreground">{formatRelativeTime(workspace.createdAt)}</TableCell>
        <TableCell><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`${workspace.name} actions`}><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem asChild><Link href={`/admin/workspaces/${workspace.id}`}><UsersRound />Manage proxies</Link></DropdownMenuItem><DropdownMenuItem onSelect={() => setManaging(workspace)}><Settings2 />Manage limits</DropdownMenuItem><DropdownMenuItem onSelect={() => setReplacingPassword(workspace)}><KeyRound />Replace owner password</DropdownMenuItem><DropdownMenuSeparator /><DropdownMenuItem variant={workspace.status === "active" ? "destructive" : "default"} onSelect={() => void setStatus(workspace)}>{workspace.status === "active" ? <PauseCircle /> : <PlayCircle />}{workspace.status === "active" ? "Suspend workspace" : "Reactivate workspace"}</DropdownMenuItem></DropdownMenuContent></DropdownMenu></TableCell>
      </TableRow>)}</TableBody></Table>}
    </Card></div>
    <ManageWorkspaceDialog workspace={managing} onClose={() => setManaging(undefined)} />
    <ReplacePasswordDialog workspace={replacingPassword} onClose={() => setReplacingPassword(undefined)} />
  </>;
}
