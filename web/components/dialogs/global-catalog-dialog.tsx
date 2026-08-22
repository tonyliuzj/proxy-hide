"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Globe2, LoaderCircle } from "lucide-react";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, ApiError } from "@/lib/api/client";
import type { FilterDto, PoolDto } from "@/lib/api/dto";
import { useQueryClient } from "@tanstack/react-query";

const schema = z.object({ name: z.string().trim().min(2).max(120), protocol: z.enum(["all", "http", "https", "socks4a", "socks5"]), countries: z.string().transform((value) => value.split(",").map((item) => item.trim().toUpperCase()).filter(Boolean)).refine((values) => values.every((value) => /^[A-Z]{2}$/.test(value)), "Use two-letter country codes separated by commas"), minimumScore: z.coerce.number().min(0).max(100), maximumLatency: z.union([z.literal(""), z.coerce.number().positive()]), strategy: z.enum(["random", "round_robin", "lowest_latency", "weighted_health"]) });
type Inputs = z.input<typeof schema>;
type Values = z.output<typeof schema>;

function rules(values: Values) {
  const items: Record<string, unknown>[] = [{ op: "predicate", field: "health", operator: "in", value: ["healthy", "degraded"] }, { op: "predicate", field: "score", operator: "gte", value: values.minimumScore }];
  if (values.protocol !== "all") items.push({ op: "predicate", field: "protocol", operator: "eq", value: values.protocol });
  if (values.countries.length) items.push({ op: "predicate", field: "country", operator: "in", value: values.countries });
  if (values.maximumLatency !== "") items.push({ op: "predicate", field: "latency_ms", operator: "lte", value: values.maximumLatency });
  return { version: 1, root: { op: "all", rules: items } };
}

export function GlobalCatalogDialog({ workspaceId }: { workspaceId?: string }) {
  const [open, setOpen] = useState(false);
  const [matches, setMatches] = useState<number>();
  const queryClient = useQueryClient();
  const form = useForm<Inputs, unknown, Values>({ resolver: zodResolver(schema), defaultValues: { name: "Global catalog pool", protocol: "all", countries: "", minimumScore: 70, maximumLatency: 1000, strategy: "weighted_health" } });

  async function preview() {
    const values = await schema.parseAsync(form.getValues());
    const path = workspaceId ? `/admin/workspaces/${workspaceId}/global-pools/preview` : "/filters/preview";
    const result = await api.post<{ count: number }>(path, { rules: rules(values), catalog_selection: "global", sample_size: 0 });
    setMatches(result.count);
  }

  async function submit(values: Values) {
    let filterId: string | undefined;
    try {
      if (workspaceId) {
        await api.post<PoolDto>(`/admin/workspaces/${workspaceId}/global-pools`, { name: values.name, rules: rules(values), strategy: values.strategy });
      } else {
        const filter = await api.post<FilterDto>("/filters", { name: `${values.name} filter`, rules: rules(values) });
        filterId = filter.id;
        await api.post<PoolDto>("/pools", { name: values.name, filter_id: filter.id, catalog_selection: "global", strategy: values.strategy, enabled: true });
      }
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["filters"] }), queryClient.invalidateQueries({ queryKey: ["pools"] }), queryClient.invalidateQueries({ queryKey: ["admin", "workspaces", workspaceId, "global-pools"] })]);
      toast.success("Filtered global catalog pool created");
      form.reset(); setMatches(undefined); setOpen(false);
    } catch (error) {
      if (!workspaceId && filterId) await api.delete(`/filters/${filterId}`).catch(() => undefined);
      toast.error(error instanceof ApiError ? error.message : "Could not add the filtered global catalog.");
    }
  }

  return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button variant="outline" size="sm"><Globe2 />Add filtered global</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>Add filtered global catalog</DialogTitle><DialogDescription>Create a workspace pool backed only by global catalog proxies matching these rules.</DialogDescription></DialogHeader><form className="space-y-4" onSubmit={form.handleSubmit(submit)}><div className="space-y-2"><Label htmlFor="global-pool-name">Pool name</Label><Input id="global-pool-name" {...form.register("name", { onChange: () => setMatches(undefined) })} /></div><div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label>Protocol</Label><Controller control={form.control} name="protocol" render={({ field }) => <Select value={field.value} onValueChange={(value) => { field.onChange(value); setMatches(undefined); }}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">Any protocol</SelectItem><SelectItem value="http">HTTP</SelectItem><SelectItem value="https">HTTPS</SelectItem><SelectItem value="socks4a">SOCKS4a</SelectItem><SelectItem value="socks5">SOCKS5</SelectItem></SelectContent></Select>} /></div><div className="space-y-2"><Label htmlFor="global-countries">Countries</Label><Input id="global-countries" placeholder="GB, DE, NL" {...form.register("countries", { onChange: () => setMatches(undefined) })} />{form.formState.errors.countries ? <p className="text-xs text-destructive">{form.formState.errors.countries.message}</p> : null}</div></div><div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor="global-score">Minimum score</Label><Input id="global-score" type="number" min={0} max={100} {...form.register("minimumScore", { onChange: () => setMatches(undefined) })} /></div><div className="space-y-2"><Label htmlFor="global-latency">Maximum latency (ms)</Label><Input id="global-latency" type="number" min={1} {...form.register("maximumLatency", { onChange: () => setMatches(undefined) })} /></div></div><div className="space-y-2"><Label>Rotation strategy</Label><Controller control={form.control} name="strategy" render={({ field }) => <Select value={field.value} onValueChange={field.onChange}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="weighted_health">Weighted health</SelectItem><SelectItem value="lowest_latency">Lowest latency</SelectItem><SelectItem value="round_robin">Round robin</SelectItem><SelectItem value="random">Random</SelectItem></SelectContent></Select>} /></div>{matches !== undefined ? <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm"><span className="font-semibold">{matches}</span> global proxies currently match.</div> : null}<DialogFooter><DialogClose asChild><Button type="button" variant="outline">Cancel</Button></DialogClose><Button type="button" variant="secondary" onClick={() => void preview().catch((error) => toast.error(error instanceof ApiError ? error.message : "Could not preview global proxies."))}>Preview</Button><Button type="submit" disabled={form.formState.isSubmitting || matches === 0}>{form.formState.isSubmitting ? <LoaderCircle className="animate-spin" /> : null}Create global pool</Button></DialogFooter></form></DialogContent></Dialog>;
}
