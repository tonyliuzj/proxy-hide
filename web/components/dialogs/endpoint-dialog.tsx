"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { LoaderCircle, Plus } from "lucide-react";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
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
import type { EndpointCredentials } from "@/lib/api/types";
import { useQueryClient } from "@tanstack/react-query";

const schema = z.object({
  name: z.string().trim().min(2).max(120),
  username: z.string().trim().regex(/^[a-zA-Z0-9][a-zA-Z0-9_-]{2,63}$/, "Use 3-64 letters, numbers, dashes, or underscores"),
  poolId: z.string().min(1, "Select a pool"),
  allowlist: z.string().max(4000),
  enabled: z.boolean(),
});
type Values = z.infer<typeof schema>;

export function EndpointDialog({ onCredentials }: { onCredentials: (credentials: EndpointCredentials) => void }) {
  const [open, setOpen] = useState(false);
  const pools = usePools();
  const queryClient = useQueryClient();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", username: "", poolId: "", allowlist: "", enabled: true },
  });

  async function submit(values: Values) {
    const ipAllowlist = values.allowlist.split(/[\n,]/).map((value) => value.trim()).filter(Boolean);
    try {
      const dto = await api.post<EndpointCreatedDto>("/endpoints", {
        name: values.name,
        username: values.username,
        pool_id: values.poolId,
        enabled: values.enabled,
        ip_allowlist: ipAllowlist,
      });
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
      <DialogHeader><DialogTitle>Publish rotating endpoint</DialogTitle><DialogDescription>Choose a ready pool and globally unique gateway username.</DialogDescription></DialogHeader>
      <form className="space-y-4" onSubmit={form.handleSubmit(submit)}>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2"><Label htmlFor="endpoint-name">Name</Label><Input id="endpoint-name" placeholder="Google UK" {...form.register("name")} />{form.formState.errors.name ? <p className="text-xs text-destructive">Enter a name.</p> : null}</div>
          <div className="space-y-2"><Label htmlFor="endpoint-username">Gateway username</Label><Input id="endpoint-username" autoCapitalize="none" placeholder="google-uk" {...form.register("username")} />{form.formState.errors.username ? <p className="text-xs text-destructive">{form.formState.errors.username.message}</p> : null}</div>
        </div>
        <div className="space-y-2"><Label>Pool</Label><Controller control={form.control} name="poolId" render={({ field }) => <Select value={field.value} onValueChange={field.onChange}><SelectTrigger className="w-full"><SelectValue placeholder="Select a pool" /></SelectTrigger><SelectContent>{pools.data?.items.map((pool) => <SelectItem key={pool.id} value={pool.id}>{pool.name}{pool.currentRevision ? "" : " (pending)"}</SelectItem>)}</SelectContent></Select>} />{form.formState.errors.poolId ? <p className="text-xs text-destructive">Select a pool.</p> : null}</div>
        <div className="space-y-2"><Label htmlFor="endpoint-allowlist">Client IP allowlist</Label><Input id="endpoint-allowlist" placeholder="203.0.113.8/32, 198.51.100.0/24" {...form.register("allowlist")} /><p className="text-xs text-muted-foreground">Leave empty to allow any client IP. Separate CIDRs with commas.</p></div>
        <div className="flex items-center justify-between rounded-md border p-3"><div><Label htmlFor="endpoint-enabled">Accept connections</Label><p className="mt-1 text-xs text-muted-foreground">Disabled endpoints always fail closed.</p></div><Controller control={form.control} name="enabled" render={({ field }) => <Switch id="endpoint-enabled" checked={field.value} onCheckedChange={field.onChange} />} /></div>
        <DialogFooter><DialogClose asChild><Button type="button" variant="outline">Cancel</Button></DialogClose><Button type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? <LoaderCircle className="animate-spin" /> : null}Publish endpoint</Button></DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
