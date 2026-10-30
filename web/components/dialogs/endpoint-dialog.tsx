"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { LoaderCircle, Plus } from "lucide-react";
import { useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { adaptEndpointCredentials } from "@/lib/api/adapters";
import { api, ApiError } from "@/lib/api/client";
import type { EndpointCreatedDto } from "@/lib/api/dto";
import { usePools } from "@/lib/api/resources";
import { ROTATION_STRATEGIES, STRATEGY_VALUES, strategyLabel } from "@/lib/api/strategies";
import type { EndpointCredentials } from "@/lib/api/types";
import { useQueryClient } from "@tanstack/react-query";

// Typical home-lab and Docker ranges. Narrow these to the machines that need the proxy.
const PRIVATE_NETWORKS = "127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16";

const schema = z
  .object({
    name: z.string().trim().min(2).max(120),
    access: z.enum(["port", "credentials"]),
    username: z.string().trim(),
    poolId: z.string().min(1, "Select a pool"),
    allowlist: z.string().max(4000),
    port: z.string().trim().regex(/^(\d{4,5})?$/, "Enter a port number or leave empty"),
    strategy: z.enum(["inherit", ...STRATEGY_VALUES]),
    enabled: z.boolean(),
  })
  .superRefine((values, context) => {
    if (values.access === "credentials" && !/^[a-zA-Z0-9][a-zA-Z0-9_-]{2,63}$/.test(values.username)) {
      context.addIssue({ code: "custom", path: ["username"], message: "Use 3-64 letters, numbers, dashes, or underscores" });
    }
    if (values.access === "port" && !splitList(values.allowlist).length) {
      context.addIssue({ code: "custom", path: ["allowlist"], message: "A port without a password needs at least one allowed network" });
    }
  });
type Values = z.infer<typeof schema>;

function splitList(value: string) {
  return value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
}

export function EndpointDialog({ onCredentials }: { onCredentials: (credentials: EndpointCredentials) => void }) {
  const [open, setOpen] = useState(false);
  const pools = usePools();
  const queryClient = useQueryClient();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", access: "port", username: "", poolId: "", allowlist: PRIVATE_NETWORKS, port: "", strategy: "inherit", enabled: true },
  });
  const access = useWatch({ control: form.control, name: "access" });
  const strategy = useWatch({ control: form.control, name: "strategy" });
  const poolId = useWatch({ control: form.control, name: "poolId" });
  const poolStrategy = pools.data?.items.find((pool) => pool.id === poolId)?.strategy;
  const strategyHint = strategy === "inherit"
    ? poolStrategy ? `Follows the pool: ${strategyLabel(poolStrategy)}.` : "Follows whichever rotation the pool uses."
    : ROTATION_STRATEGIES.find((option) => option.value === strategy)?.description;

  async function submit(values: Values) {
    const body = {
      name: values.name,
      pool_id: values.poolId,
      enabled: values.enabled,
      ip_allowlist: splitList(values.allowlist),
      strategy: values.strategy === "inherit" ? undefined : values.strategy,
      ...(values.access === "port"
        ? { dedicated_port: true, require_auth: false, listen_port: values.port ? Number(values.port) : undefined }
        : { username: values.username }),
    };
    try {
      const dto = await api.post<EndpointCreatedDto>("/endpoints", body);
      const credentials = adaptEndpointCredentials(dto);
      await queryClient.invalidateQueries({ queryKey: ["endpoints"] });
      form.reset();
      setOpen(false);
      onCredentials(credentials);
      toast.success("Endpoint published");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not create the endpoint.");
    }
  }

  return <Dialog open={open} onOpenChange={setOpen}>
    <DialogTrigger asChild><Button size="sm" disabled={!pools.data?.items.length}><Plus />Publish endpoint</Button></DialogTrigger>
    <DialogContent>
      <DialogHeader><DialogTitle>Publish endpoint</DialogTitle><DialogDescription>Give apps an address that routes to a pool, with the rotation you choose.</DialogDescription></DialogHeader>
      <form className="space-y-4" onSubmit={form.handleSubmit(submit)}>
        <div className="space-y-2"><Label htmlFor="endpoint-name">Name</Label><Input id="endpoint-name" placeholder="Google UK" {...form.register("name")} />{form.formState.errors.name ? <p className="text-xs text-destructive">Enter a name.</p> : null}</div>
        <div className="space-y-2"><Label>Pool</Label><Controller control={form.control} name="poolId" render={({ field }) => <Select value={field.value} onValueChange={field.onChange}><SelectTrigger className="w-full"><SelectValue placeholder="Select a pool" /></SelectTrigger><SelectContent>{pools.data?.items.map((pool) => <SelectItem key={pool.id} value={pool.id}>{pool.name}{pool.currentRevision ? "" : " (pending)"}</SelectItem>)}</SelectContent></Select>} />{form.formState.errors.poolId ? <p className="text-xs text-destructive">Select a pool.</p> : null}</div>
        <div className="space-y-2"><Label>How apps connect</Label><Controller control={form.control} name="access" render={({ field }) => <Select value={field.value} onValueChange={field.onChange}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="port">Its own ip:port, no password</SelectItem><SelectItem value="credentials">Shared gateway with username and secret</SelectItem></SelectContent></Select>} /></div>
        {access === "credentials"
          ? <div className="space-y-2"><Label htmlFor="endpoint-username">Gateway username</Label><Input id="endpoint-username" autoCapitalize="none" placeholder="google-uk" {...form.register("username")} />{form.formState.errors.username ? <p className="text-xs text-destructive">{form.formState.errors.username.message}</p> : null}</div>
          : <div className="space-y-2"><Label htmlFor="endpoint-port">Port <span className="font-normal text-muted-foreground">(optional)</span></Label><Input id="endpoint-port" inputMode="numeric" placeholder="Next free port" {...form.register("port")} />{form.formState.errors.port ? <p className="text-xs text-destructive">{form.formState.errors.port.message}</p> : null}</div>}
        <div className="space-y-2"><Label htmlFor="endpoint-allowlist">{access === "port" ? "Allowed client networks" : "Client IP allowlist"}</Label><Input id="endpoint-allowlist" placeholder="192.168.0.0/16, 203.0.113.8/32" {...form.register("allowlist")} />{form.formState.errors.allowlist ? <p className="text-xs text-destructive">{form.formState.errors.allowlist.message}</p> : <p className="text-xs text-muted-foreground">{access === "port" ? "Only these addresses can use the port, because it has no password. Separate CIDRs with commas." : "Leave empty to allow any client IP. Separate CIDRs with commas."}</p>}</div>
        <div className="space-y-2"><Label>Rotation</Label><Controller control={form.control} name="strategy" render={({ field }) => <Select value={field.value} onValueChange={field.onChange}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="inherit">Use the pool&apos;s setting</SelectItem>{ROTATION_STRATEGIES.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent></Select>} /><p className="text-xs text-muted-foreground">{strategyHint}</p></div>
        <div className="flex items-center justify-between rounded-md border p-3"><div><Label htmlFor="endpoint-enabled">Accept connections</Label><p className="mt-1 text-xs text-muted-foreground">Disabled endpoints always fail closed.</p></div><Controller control={form.control} name="enabled" render={({ field }) => <Switch id="endpoint-enabled" checked={field.value} onCheckedChange={field.onChange} />} /></div>
        <DialogFooter><DialogClose asChild><Button type="button" variant="outline">Cancel</Button></DialogClose><Button type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? <LoaderCircle className="animate-spin" /> : null}Publish endpoint</Button></DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
