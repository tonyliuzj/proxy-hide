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
import type { PoolDto } from "@/lib/api/dto";
import { useFilters } from "@/lib/api/resources";
import { useQueryClient } from "@tanstack/react-query";

const schema = z.object({ name: z.string().trim().min(2).max(120), filterId: z.string().min(1, "Select a filter"), catalogSelection: z.enum(["combined", "private", "global"]), strategy: z.enum(["random", "round_robin", "lowest_latency", "weighted_health"]), enabled: z.boolean() });
type Values = z.infer<typeof schema>;

export function PoolDialog() {
  const [open, setOpen] = useState(false); const filters = useFilters(); const queryClient = useQueryClient();
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { name: "", filterId: "", catalogSelection: "combined", strategy: "weighted_health", enabled: true } });
  async function submit(values: Values) { try { await api.post<PoolDto>("/pools", { name: values.name, filter_id: values.filterId, catalog_selection: values.catalogSelection, strategy: values.strategy, enabled: values.enabled }); toast.success("Pool created and materialisation queued"); await queryClient.invalidateQueries({ queryKey: ["pools"] }); form.reset(); setOpen(false); } catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not create pool."); } }
  return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button size="sm" disabled={!filters.data?.items.length}><Plus />Create pool</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>Create pool</DialogTitle><DialogDescription>Select a versioned filter and rotation strategy. Members are materialised asynchronously.</DialogDescription></DialogHeader><form className="space-y-4" onSubmit={form.handleSubmit(submit)}><div className="space-y-2"><Label htmlFor="pool-name">Name</Label><Input id="pool-name" placeholder="Google UK" {...form.register("name")} /></div><div className="space-y-2"><Label>Filter</Label><Controller control={form.control} name="filterId" render={({ field }) => <Select value={field.value} onValueChange={field.onChange}><SelectTrigger className="w-full"><SelectValue placeholder="Select a filter" /></SelectTrigger><SelectContent>{filters.data?.items.map((filter) => <SelectItem value={filter.id} key={filter.id}>{filter.name}</SelectItem>)}</SelectContent></Select>} />{form.formState.errors.filterId ? <p className="text-xs text-destructive">Select a filter.</p> : null}</div><div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label>Catalog</Label><Controller control={form.control} name="catalogSelection" render={({ field }) => <Select value={field.value} onValueChange={field.onChange}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="combined">Private + global</SelectItem><SelectItem value="private">Private only</SelectItem><SelectItem value="global">Global only</SelectItem></SelectContent></Select>} /></div><div className="space-y-2"><Label>Rotation</Label><Controller control={form.control} name="strategy" render={({ field }) => <Select value={field.value} onValueChange={field.onChange}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="weighted_health">Weighted health</SelectItem><SelectItem value="round_robin">Round robin</SelectItem><SelectItem value="lowest_latency">Lowest latency</SelectItem><SelectItem value="random">Random</SelectItem></SelectContent></Select>} /></div></div><div className="flex items-center justify-between rounded-md border p-3"><div><Label htmlFor="pool-enabled">Publish when ready</Label><p className="mt-1 text-xs text-muted-foreground">Allow endpoints to use the latest successful revision.</p></div><Controller control={form.control} name="enabled" render={({ field }) => <Switch id="pool-enabled" checked={field.value} onCheckedChange={field.onChange} />} /></div><DialogFooter><DialogClose asChild><Button type="button" variant="outline">Cancel</Button></DialogClose><Button type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? <LoaderCircle className="animate-spin" /> : null}Create pool</Button></DialogFooter></form></DialogContent></Dialog>;
}
