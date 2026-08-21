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
import { api, ApiError } from "@/lib/api/client";
import type { SourceDto } from "@/lib/api/dto";
import { useQueryClient } from "@tanstack/react-query";

const sourceSchema = z.object({ name: z.string().trim().min(2).max(120), url: z.url("Enter a valid feed URL"), defaultProtocol: z.enum(["http", "https", "socks4a", "socks5"]), refreshIntervalMinutes: z.coerce.number().int().min(5).max(1440), username: z.string().max(1024), password: z.string().max(1024), enabled: z.boolean() });
type InputValues = z.input<typeof sourceSchema>;
type Values = z.output<typeof sourceSchema>;

export function SourceDialog({ admin = false }: { admin?: boolean }) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const form = useForm<InputValues, unknown, Values>({ resolver: zodResolver(sourceSchema), defaultValues: { name: "", url: "", defaultProtocol: "http", refreshIntervalMinutes: 60, username: "", password: "", enabled: true } });

  async function submit(values: Values) {
    try {
      await api.post<SourceDto>(admin ? "/admin/sources" : "/sources", { name: values.name, url: values.url, default_protocol: values.defaultProtocol, refresh_interval_minutes: values.refreshIntervalMinutes, username: values.username || null, password: values.password || null, enabled: values.enabled });
      toast.success("Source created and queued for its first refresh");
      await queryClient.invalidateQueries({ queryKey: admin ? ["admin", "sources"] : ["sources"] });
      form.reset();
      setOpen(false);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not create source.");
    }
  }

  return <Dialog open={open} onOpenChange={setOpen}>
    <DialogTrigger asChild><Button size="sm"><Plus />Add source</Button></DialogTrigger>
    <DialogContent>
      <DialogHeader><DialogTitle>Add {admin ? "global" : "private"} source</DialogTitle><DialogDescription>Proxy lists are fetched server-side and validated before inventory changes.</DialogDescription></DialogHeader>
      <form className="space-y-4" onSubmit={form.handleSubmit(submit)}>
        <div className="space-y-2"><Label htmlFor="source-name">Name</Label><Input id="source-name" placeholder="EU premium feed" {...form.register("name")} />{form.formState.errors.name ? <p className="text-xs text-destructive">Enter a name between 2 and 120 characters.</p> : null}</div>
        <div className="space-y-2"><Label htmlFor="source-url">Feed URL</Label><Input id="source-url" type="url" placeholder="https://provider.example/proxies.txt" {...form.register("url")} />{form.formState.errors.url ? <p className="text-xs text-destructive">{form.formState.errors.url.message}</p> : null}</div>
        <div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label>Default protocol</Label><Controller control={form.control} name="defaultProtocol" render={({ field }) => <Select value={field.value} onValueChange={field.onChange}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="http">HTTP</SelectItem><SelectItem value="https">HTTPS</SelectItem><SelectItem value="socks4a">SOCKS4a</SelectItem><SelectItem value="socks5">SOCKS5</SelectItem></SelectContent></Select>} /></div><div className="space-y-2"><Label htmlFor="refresh-interval">Refresh interval (minutes)</Label><Input id="refresh-interval" type="number" min={5} max={1440} {...form.register("refreshIntervalMinutes")} /></div></div>
        <div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor="source-user">Username</Label><Input id="source-user" autoComplete="off" {...form.register("username")} /></div><div className="space-y-2"><Label htmlFor="source-password">Password</Label><Input id="source-password" type="password" autoComplete="new-password" {...form.register("password")} /></div></div>
        <div className="flex items-center justify-between rounded-md border p-3"><div><Label htmlFor="source-enabled">Refresh automatically</Label><p className="mt-1 text-xs text-muted-foreground">Run this source on its configured interval.</p></div><Controller control={form.control} name="enabled" render={({ field }) => <Switch id="source-enabled" checked={field.value} onCheckedChange={field.onChange} />} /></div>
        <DialogFooter><DialogClose asChild><Button type="button" variant="outline">Cancel</Button></DialogClose><Button type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? <LoaderCircle className="animate-spin" /> : null}Create source</Button></DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
