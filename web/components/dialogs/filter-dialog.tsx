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
import { api, ApiError } from "@/lib/api/client";
import type { FilterDto, ProxyDto } from "@/lib/api/dto";
import { useTargets } from "@/lib/api/resources";
import { useQueryClient } from "@tanstack/react-query";

export const filterFormSchema = z.object({ name: z.string().trim().min(2).max(120), countries: z.string().transform((value) => value.split(",").map((item) => item.trim().toUpperCase()).filter(Boolean)).refine((values) => values.every((value) => /^[A-Z]{2}$/.test(value)), "Use two-letter country codes separated by commas"), minimumScore: z.coerce.number().min(0).max(100), maximumLatency: z.union([z.literal(""), z.coerce.number().positive()]), targetId: z.string(), targetAvailability: z.enum(["available", "blocked", "rate_limited", "unavailable"]), catalogSelection: z.enum(["combined", "private", "global"]) });
export type FilterFormValues = z.input<typeof filterFormSchema>;
type ParsedValues = z.output<typeof filterFormSchema>;

export function buildFilterRules(values: Pick<ParsedValues, "countries" | "minimumScore" | "maximumLatency" | "targetId" | "targetAvailability">) {
  const rules: Record<string, unknown>[] = [{ op: "predicate", field: "health", operator: "eq", value: "healthy" }, { op: "predicate", field: "score", operator: "gte", value: values.minimumScore }];
  if (values.countries.length) rules.push({ op: "predicate", field: "country", operator: "in", value: values.countries });
  if (values.maximumLatency !== "") rules.push({ op: "predicate", field: "latency_ms", operator: "lte", value: values.maximumLatency });
  if (values.targetId !== "none") rules.push({ op: "predicate", field: "target_availability", operator: "eq", value: values.targetAvailability, target_id: values.targetId });
  return { version: 1, root: { op: "all", rules } };
}

export function FilterDialog() {
  const [open, setOpen] = useState(false);
  const [matchCount, setMatchCount] = useState<number>();
  const [working, setWorking] = useState(false);
  const targets = useTargets();
  const queryClient = useQueryClient();
  const form = useForm<FilterFormValues, unknown, ParsedValues>({ resolver: zodResolver(filterFormSchema), defaultValues: { name: "", countries: "GB", minimumScore: 85, maximumLatency: 500, targetId: "none", targetAvailability: "available", catalogSelection: "combined" } });
  async function parsed() { return filterFormSchema.parseAsync(form.getValues()); }
  async function preview() { setWorking(true); try { const values = await parsed(); const rules = buildFilterRules(values); const result = await api.post<{ count: number; sample: ProxyDto[] }>("/filters/preview", { rules, catalog_selection: values.catalogSelection, sample_size: 5 }); setMatchCount(result.count); } catch (error) { toast.error(error instanceof ApiError ? error.message : "Check the filter fields and retry."); } finally { setWorking(false); } }
  async function submit() { setWorking(true); try { const values = await parsed(); await api.post<FilterDto>("/filters", { name: values.name, rules: buildFilterRules(values) }); toast.success("Filter created"); await queryClient.invalidateQueries({ queryKey: ["filters"] }); form.reset(); setOpen(false); setMatchCount(undefined); } catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not create filter."); } finally { setWorking(false); } }
  return <Dialog open={open} onOpenChange={(value) => { setOpen(value); if (!value) setMatchCount(undefined); }}><DialogTrigger asChild><Button size="sm"><Plus />Create filter</Button></DialogTrigger><DialogContent className="max-w-xl"><DialogHeader><DialogTitle>Create proxy filter</DialogTitle><DialogDescription>All configured conditions must match. Preview uses the current catalog snapshot.</DialogDescription></DialogHeader><form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void submit(); }}><div className="space-y-2"><Label htmlFor="filter-name">Name</Label><Input id="filter-name" placeholder="Google UK premium" {...form.register("name", { onChange: () => setMatchCount(undefined) })} />{form.formState.errors.name ? <p className="text-xs text-destructive">Enter a filter name.</p> : null}</div><div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor="countries">Countries</Label><Input id="countries" placeholder="GB, DE, NL" {...form.register("countries", { onChange: () => setMatchCount(undefined) })} />{form.formState.errors.countries ? <p className="text-xs text-destructive">{form.formState.errors.countries.message}</p> : null}</div><div className="space-y-2"><Label>Catalog</Label><Controller control={form.control} name="catalogSelection" render={({ field }) => <Select value={field.value} onValueChange={(value) => { field.onChange(value); setMatchCount(undefined); }}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="combined">Private + global</SelectItem><SelectItem value="private">Private only</SelectItem><SelectItem value="global">Global only</SelectItem></SelectContent></Select>} /></div></div><div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor="minimum-score">Minimum health score</Label><Input id="minimum-score" type="number" min={0} max={100} {...form.register("minimumScore", { onChange: () => setMatchCount(undefined) })} /></div><div className="space-y-2"><Label htmlFor="maximum-latency">Maximum latency (ms)</Label><Input id="maximum-latency" type="number" min={1} placeholder="No limit" {...form.register("maximumLatency", { onChange: () => setMatchCount(undefined) })} /></div></div><div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label>Target check</Label><Controller control={form.control} name="targetId" render={({ field }) => <Select value={field.value} onValueChange={(value) => { field.onChange(value); setMatchCount(undefined); }}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">No target condition</SelectItem>{targets.data?.items.map((target) => <SelectItem value={target.id} key={target.id}>{target.name}</SelectItem>)}</SelectContent></Select>} /></div><div className="space-y-2"><Label>Required result</Label><Controller control={form.control} name="targetAvailability" render={({ field }) => <Select value={field.value} onValueChange={(value) => { field.onChange(value); setMatchCount(undefined); }}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="available">Available</SelectItem><SelectItem value="blocked">Blocked</SelectItem><SelectItem value="rate_limited">Rate limited</SelectItem><SelectItem value="unavailable">Unavailable</SelectItem></SelectContent></Select>} /></div></div>{matchCount !== undefined ? <div className="flex items-center justify-between rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2"><span className="text-sm text-emerald-900">Current matching proxies</span><span className="text-lg font-semibold text-emerald-800">{matchCount}</span></div> : null}<DialogFooter><DialogClose asChild><Button type="button" variant="outline">Cancel</Button></DialogClose><Button type="button" variant="secondary" onClick={preview} disabled={working}>{working ? <LoaderCircle className="animate-spin" /> : null}Preview</Button><Button type="submit" disabled={working || matchCount === 0}>Create filter</Button></DialogFooter></form></DialogContent></Dialog>;
}
