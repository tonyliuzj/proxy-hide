"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { LoaderCircle, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api, ApiError } from "@/lib/api/client";
import { DEFAULT_WORKSPACE_LIMITS } from "@/lib/api/defaults";
import type { WorkspaceAdminDto } from "@/lib/api/dto";
import type { AdminWorkspace, WorkspaceLimits } from "@/lib/api/types";
import { useQueryClient } from "@tanstack/react-query";

const limitsSchema = {
  maxPrivateProxies: z.number().int().min(0).max(10_000_000),
  maxSources: z.number().int().min(0).max(10_000),
  maxCustomTargets: z.number().int().min(0).max(10_000),
  maxFilters: z.number().int().min(0).max(10_000),
  maxPools: z.number().int().min(0).max(10_000),
  maxEndpoints: z.number().int().min(0).max(10_000),
  maxConcurrentChecks: z.number().int().min(1).max(100_000),
  maxGatewayConnections: z.number().int().min(1).max(1_000_000),
  requestsPerMinute: z.number().int().min(1).max(100_000_000),
  globalCatalogEnabled: z.boolean(),
  destinationPorts: z.string().min(1).refine((value) => value.split(",").every((port) => { const parsed = Number(port.trim()); return Number.isInteger(parsed) && parsed >= 1 && parsed <= 65535; }), "Use comma-separated ports from 1 to 65535"),
};

const createSchema = z.object({
  name: z.string().trim().min(2).max(120),
  slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, "Use lowercase letters, numbers, and dashes"),
  ownerEmail: z.email(),
  ownerPassword: z.string().min(12, "Use at least 12 characters").max(1024),
  ...limitsSchema,
});
type CreateValues = z.infer<typeof createSchema>;

const manageSchema = z.object({ name: z.string().trim().min(2).max(120), ...limitsSchema });
type ManageValues = z.infer<typeof manageSchema>;

function defaults(limits: WorkspaceLimits = DEFAULT_WORKSPACE_LIMITS) {
  return {
    maxPrivateProxies: limits.max_private_proxies,
    maxSources: limits.max_sources,
    maxCustomTargets: limits.max_custom_targets,
    maxFilters: limits.max_filters,
    maxPools: limits.max_pools,
    maxEndpoints: limits.max_endpoints,
    maxConcurrentChecks: limits.max_concurrent_checks,
    maxGatewayConnections: limits.max_gateway_connections,
    requestsPerMinute: limits.requests_per_minute,
    globalCatalogEnabled: limits.global_catalog_enabled,
    destinationPorts: limits.destination_ports.join(", "),
  };
}

function limitsPayload(values: ManageValues | CreateValues) {
  return {
    max_private_proxies: values.maxPrivateProxies,
    max_sources: values.maxSources,
    max_custom_targets: values.maxCustomTargets,
    max_filters: values.maxFilters,
    max_pools: values.maxPools,
    max_endpoints: values.maxEndpoints,
    max_concurrent_checks: values.maxConcurrentChecks,
    max_gateway_connections: values.maxGatewayConnections,
    requests_per_minute: values.requestsPerMinute,
    global_catalog_enabled: values.globalCatalogEnabled,
    destination_ports: [...new Set(values.destinationPorts.split(",").map((port) => Number(port.trim())))].sort((a, b) => a - b),
  };
}

function LimitsFields({ form }: { form: ReturnType<typeof useForm<CreateValues>> | ReturnType<typeof useForm<ManageValues>> }) {
  const register = form.register as ReturnType<typeof useForm<ManageValues>>["register"];
  const control = form.control as ReturnType<typeof useForm<ManageValues>>["control"];
  return <>
    <div className="grid gap-4 sm:grid-cols-3">
      <div className="space-y-2"><Label>Private proxies</Label><Input type="number" {...register("maxPrivateProxies", { valueAsNumber: true })} /></div>
      <div className="space-y-2"><Label>Sources</Label><Input type="number" {...register("maxSources", { valueAsNumber: true })} /></div>
      <div className="space-y-2"><Label>Custom targets</Label><Input type="number" {...register("maxCustomTargets", { valueAsNumber: true })} /></div>
      <div className="space-y-2"><Label>Filters</Label><Input type="number" {...register("maxFilters", { valueAsNumber: true })} /></div>
      <div className="space-y-2"><Label>Pools</Label><Input type="number" {...register("maxPools", { valueAsNumber: true })} /></div>
      <div className="space-y-2"><Label>Endpoints</Label><Input type="number" {...register("maxEndpoints", { valueAsNumber: true })} /></div>
      <div className="space-y-2"><Label>Concurrent checks</Label><Input type="number" {...register("maxConcurrentChecks", { valueAsNumber: true })} /></div>
      <div className="space-y-2"><Label>Gateway connections</Label><Input type="number" {...register("maxGatewayConnections", { valueAsNumber: true })} /></div>
      <div className="space-y-2"><Label>Requests/minute</Label><Input type="number" {...register("requestsPerMinute", { valueAsNumber: true })} /></div>
    </div>
    <div className="grid gap-4 sm:grid-cols-[1fr_auto] sm:items-end"><div className="space-y-2"><Label>Allowed destination ports</Label><Input {...register("destinationPorts")} />{form.formState.errors.destinationPorts ? <p className="text-xs text-destructive">{form.formState.errors.destinationPorts.message}</p> : null}</div><div className="flex h-9 items-center gap-3 rounded-md border px-3"><Label htmlFor="global-catalog">Global catalog</Label><Controller control={control} name="globalCatalogEnabled" render={({ field }) => <Switch id="global-catalog" checked={field.value} onCheckedChange={field.onChange} />} /></div></div>
  </>;
}

export function CreateWorkspaceDialog() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const form = useForm<CreateValues>({ resolver: zodResolver(createSchema), defaultValues: { name: "", slug: "", ownerEmail: "", ownerPassword: "", ...defaults() } });

  async function submit(values: CreateValues) {
    try {
      await api.post<WorkspaceAdminDto>("/admin/workspaces", { name: values.name, slug: values.slug, owner_email: values.ownerEmail, owner_password: values.ownerPassword, limits: limitsPayload(values) });
      await queryClient.invalidateQueries({ queryKey: ["admin", "workspaces"] });
      toast.success("Workspace provisioned");
      form.reset();
      setOpen(false);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not create the workspace.");
    }
  }

  return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button size="sm"><Plus />Create workspace</Button></DialogTrigger><DialogContent className="max-w-3xl"><DialogHeader><DialogTitle>Provision workspace</DialogTitle><DialogDescription>Create the owner with a permanent password and operator-enforced limits.</DialogDescription></DialogHeader><form className="max-h-[75vh] space-y-5 overflow-y-auto pr-1" onSubmit={form.handleSubmit(submit)}><div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label>Name</Label><Input {...form.register("name")} /></div><div className="space-y-2"><Label>Slug</Label><Input {...form.register("slug")} />{form.formState.errors.slug ? <p className="text-xs text-destructive">{form.formState.errors.slug.message}</p> : null}</div><div className="space-y-2"><Label>Owner email</Label><Input type="email" {...form.register("ownerEmail")} /></div><div className="space-y-2"><Label>Permanent password</Label><Input type="password" autoComplete="new-password" {...form.register("ownerPassword")} />{form.formState.errors.ownerPassword ? <p className="text-xs text-destructive">{form.formState.errors.ownerPassword.message}</p> : null}</div></div><div className="border-t pt-5"><p className="mb-4 text-sm font-medium">Workspace limits</p><LimitsFields form={form} /></div><DialogFooter><DialogClose asChild><Button type="button" variant="outline">Cancel</Button></DialogClose><Button type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? <LoaderCircle className="animate-spin" /> : null}Create workspace</Button></DialogFooter></form></DialogContent></Dialog>;
}

export function ManageWorkspaceDialog({ workspace, onClose }: { workspace?: AdminWorkspace; onClose: () => void }) {
  const queryClient = useQueryClient();
  const form = useForm<ManageValues>({ resolver: zodResolver(manageSchema), defaultValues: { name: "", ...defaults() } });
  useEffect(() => { if (workspace) form.reset({ name: workspace.name, ...defaults(workspace.limits) }); }, [form, workspace]);

  async function submit(values: ManageValues) {
    if (!workspace) return;
    try {
      await api.patch(`/admin/workspaces/${workspace.id}`, { name: values.name, limits: limitsPayload(values) });
      await queryClient.invalidateQueries({ queryKey: ["admin", "workspaces"] });
      toast.success("Workspace limits updated");
      onClose();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not update the workspace.");
    }
  }

  return <Dialog open={Boolean(workspace)} onOpenChange={(open) => { if (!open) onClose(); }}><DialogContent className="max-w-3xl"><DialogHeader><DialogTitle>Manage workspace</DialogTitle><DialogDescription>Changes take effect for new jobs and gateway snapshot publications.</DialogDescription></DialogHeader><form className="max-h-[75vh] space-y-5 overflow-y-auto pr-1" onSubmit={form.handleSubmit(submit)}><div className="space-y-2"><Label>Name</Label><Input {...form.register("name")} /></div><div className="border-t pt-5"><p className="mb-4 text-sm font-medium">Workspace limits</p><LimitsFields form={form} /></div><DialogFooter><DialogClose asChild><Button type="button" variant="outline">Cancel</Button></DialogClose><Button type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? <LoaderCircle className="animate-spin" /> : null}Save changes</Button></DialogFooter></form></DialogContent></Dialog>;
}

export function ReplacePasswordDialog({ workspace, onClose }: { workspace?: AdminWorkspace; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const [working, setWorking] = useState(false);
  async function replace() {
    if (!workspace || password.length < 12) return;
    setWorking(true);
    try {
      await api.post(`/admin/workspaces/${workspace.id}/replace-password`, { password });
      toast.success("Owner password replaced and sessions revoked");
      setPassword("");
      onClose();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not replace the password.");
    } finally {
      setWorking(false);
    }
  }
  return <Dialog open={Boolean(workspace)} onOpenChange={(open) => { if (!open) onClose(); }}><DialogContent><DialogHeader><DialogTitle>Replace owner password</DialogTitle><DialogDescription>This immediately revokes every active session for {workspace?.ownerEmail}.</DialogDescription></DialogHeader><div className="space-y-2"><Label htmlFor="replacement-password">New permanent password</Label><Input id="replacement-password" type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /><p className="text-xs text-muted-foreground">Minimum 12 characters.</p></div><DialogFooter><DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose><Button onClick={replace} disabled={working || password.length < 12}>{working ? <LoaderCircle className="animate-spin" /> : null}Replace password</Button></DialogFooter></DialogContent></Dialog>;
}
