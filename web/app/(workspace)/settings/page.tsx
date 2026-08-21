"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { KeyRound, LoaderCircle, Save, Shield, SlidersHorizontal } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { PageHeader } from "@/components/page-header";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, ApiError } from "@/lib/api/client";
import type { AuditEventDto, PageDto } from "@/lib/api/dto";
import { useApiQuery } from "@/lib/api/hooks";
import { useWorkspaceSettings } from "@/lib/api/resources";
import { formatNumber, formatRelativeTime } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

const passwordSchema = z.object({ currentPassword: z.string().min(1), newPassword: z.string().min(12, "Use at least 12 characters"), confirmPassword: z.string().min(1) }).refine((value) => value.newPassword === value.confirmPassword, { path: ["confirmPassword"], message: "Passwords do not match" });
type PasswordValues = z.infer<typeof passwordSchema>;

export default function SettingsPage() {
  const settings = useWorkspaceSettings();
  const audit = useApiQuery<PageDto<AuditEventDto>>(["audit"], "/audit?page_size=50");
  const queryClient = useQueryClient();
  const router = useRouter();
  const [workspaceNameDraft, setWorkspaceNameDraft] = useState<string>();
  const [savingName, setSavingName] = useState(false);
  const password = useForm<PasswordValues>({ resolver: zodResolver(passwordSchema), defaultValues: { currentPassword: "", newPassword: "", confirmPassword: "" } });

  async function saveWorkspace() {
    const workspaceName = workspaceNameDraft ?? settings.data?.workspace.name ?? "";
    if (!workspaceName.trim()) return;
    setSavingName(true);
    try {
      await api.patch("/settings", { name: workspaceName.trim() });
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
      setWorkspaceNameDraft(undefined);
      toast.success("Workspace settings saved");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not save workspace settings.");
    } finally {
      setSavingName(false);
    }
  }

  async function changePassword(values: PasswordValues) {
    try {
      await api.post("/settings/change-password", { current_password: values.currentPassword, new_password: values.newPassword });
      toast.success("Password changed. Sign in again.");
      password.reset();
      router.replace("/login");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not change the password.");
    }
  }

  if (settings.isLoading) return <><PageHeader title="Settings" /><div className="p-4 sm:p-6"><TableLoading /></div></>;
  if (settings.isError || !settings.data) return <><PageHeader title="Settings" /><div className="p-4 sm:p-6"><Card><QueryError onRetry={() => settings.refetch()} /></Card></div></>;

  const usage = settings.data.usage;
  const limits = settings.data.limits;
  const workspaceName = workspaceNameDraft ?? settings.data.workspace.name;
  const quotas = [
    ["Private proxies", usage.private_proxies, limits.max_private_proxies],
    ["Sources", usage.sources, limits.max_sources],
    ["Custom targets", usage.custom_targets, limits.max_custom_targets],
    ["Filters", usage.filters, limits.max_filters],
    ["Pools", usage.pools, limits.max_pools],
    ["Endpoints", usage.endpoints, limits.max_endpoints],
  ] as const;

  return <>
    <PageHeader title="Settings" description="Workspace identity, enforced quotas, security, and audit activity." />
    <div className="p-4 sm:p-6">
      <Tabs defaultValue="workspace">
        <TabsList><TabsTrigger value="workspace">Workspace</TabsTrigger><TabsTrigger value="security">Security</TabsTrigger><TabsTrigger value="audit">Audit</TabsTrigger></TabsList>

        <TabsContent value="workspace" className="space-y-5">
          <Card>
            <CardHeader><div className="flex items-center gap-2"><SlidersHorizontal className="size-4 text-muted-foreground" /><CardTitle>Workspace</CardTitle></div><CardDescription>The slug and access status are managed by the platform operator.</CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor="workspace-name">Display name</Label><Input id="workspace-name" value={workspaceName} onChange={(event) => setWorkspaceNameDraft(event.target.value)} maxLength={120} /></div><div className="space-y-2"><Label>Slug</Label><Input value={settings.data.workspace.slug} readOnly /></div></div>
              <div className="flex items-center justify-between"><StatusBadge status={settings.data.workspace.status} /><Button onClick={saveWorkspace} disabled={savingName || !workspaceName.trim()}>{savingName ? <LoaderCircle className="animate-spin" /> : <Save />}Save changes</Button></div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Quota usage</CardTitle><CardDescription>Limits are set by the platform administrator.</CardDescription></CardHeader>
            <CardContent><div className="grid gap-x-8 gap-y-5 md:grid-cols-2">{quotas.map(([label, value, limit]) => <div key={label}><div className="mb-2 flex items-center justify-between text-sm"><span>{label}</span><span className="tabular-nums text-muted-foreground">{formatNumber(value)} / {formatNumber(limit)}</span></div><Progress value={limit ? Math.min((value / limit) * 100, 100) : 100} /></div>)}</div><div className="mt-6 grid gap-3 border-t pt-5 text-sm sm:grid-cols-2 lg:grid-cols-4"><div><p className="text-muted-foreground">Concurrent checks</p><p className="mt-1 font-semibold">{formatNumber(limits.max_concurrent_checks)}</p></div><div><p className="text-muted-foreground">Gateway connections</p><p className="mt-1 font-semibold">{formatNumber(limits.max_gateway_connections)}</p></div><div><p className="text-muted-foreground">Requests/minute</p><p className="mt-1 font-semibold">{formatNumber(limits.requests_per_minute)}</p></div><div><p className="text-muted-foreground">Destination ports</p><p className="mt-1 font-mono font-semibold">{limits.destination_ports.join(", ")}</p></div></div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="security">
          <Card className="max-w-2xl"><CardHeader><div className="flex items-center gap-2"><KeyRound className="size-4 text-muted-foreground" /><CardTitle>Owner password</CardTitle></div><CardDescription>Changing the password revokes every active session for this owner.</CardDescription></CardHeader><CardContent><form className="space-y-4" onSubmit={password.handleSubmit(changePassword)}><div className="space-y-2"><Label htmlFor="current-password">Current password</Label><Input id="current-password" type="password" autoComplete="current-password" {...password.register("currentPassword")} /></div><div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor="new-password">New password</Label><Input id="new-password" type="password" autoComplete="new-password" {...password.register("newPassword")} />{password.formState.errors.newPassword ? <p className="text-xs text-destructive">{password.formState.errors.newPassword.message}</p> : null}</div><div className="space-y-2"><Label htmlFor="confirm-password">Confirm password</Label><Input id="confirm-password" type="password" autoComplete="new-password" {...password.register("confirmPassword")} />{password.formState.errors.confirmPassword ? <p className="text-xs text-destructive">{password.formState.errors.confirmPassword.message}</p> : null}</div></div><Button type="submit" disabled={password.formState.isSubmitting}>{password.formState.isSubmitting ? <LoaderCircle className="animate-spin" /> : <Shield />}Change password</Button></form></CardContent></Card>
        </TabsContent>

        <TabsContent value="audit">
          <Card className="overflow-hidden">{audit.isLoading ? <TableLoading /> : audit.isError ? <QueryError onRetry={() => audit.refetch()} /> : !audit.data?.items.length ? <QueryEmpty title="No audit events" description="Configuration and security changes appear here." /> : <Table><TableHeader><TableRow><TableHead className="pl-5">Action</TableHead><TableHead>Resource</TableHead><TableHead>Actor</TableHead><TableHead>IP address</TableHead><TableHead>Time</TableHead></TableRow></TableHeader><TableBody>{audit.data.items.map((event) => <TableRow key={event.id}><TableCell className="pl-5 font-mono text-xs">{event.action}</TableCell><TableCell>{event.resource_type}</TableCell><TableCell className="font-mono text-xs">{event.actor_user_id?.slice(0, 12) ?? "System"}</TableCell><TableCell className="font-mono text-xs">{event.ip_address ?? "-"}</TableCell><TableCell className="text-xs text-muted-foreground">{formatRelativeTime(event.created_at)}</TableCell></TableRow>)}</TableBody></Table>}</Card>
        </TabsContent>
      </Tabs>
    </div>
  </>;
}
