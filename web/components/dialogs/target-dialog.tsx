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
import { api, ApiError } from "@/lib/api/client";
import type { TargetDto } from "@/lib/api/dto";
import { useQueryClient } from "@tanstack/react-query";

const targetSchema = z.object({ kind: z.enum(["google", "bing", "brave", "startpage", "duckduckgo", "wikipedia", "custom"]), name: z.string().trim().min(2).max(120), url: z.string(), method: z.enum(["GET", "HEAD", "POST"]), statusLow: z.coerce.number().int().min(100).max(599), statusHigh: z.coerce.number().int().min(100).max(599), requiredLiteral: z.string().max(4096), forbiddenLiteral: z.string().max(4096) }).superRefine((value, context) => { if (value.statusLow > value.statusHigh) context.addIssue({ code: "custom", path: ["statusHigh"], message: "Must be at least the lower status" }); if (value.kind === "custom") { const result = z.url().safeParse(value.url); if (!result.success) context.addIssue({ code: "custom", path: ["url"], message: "Enter a valid public HTTP or HTTPS URL" }); } });
type InputValues = z.input<typeof targetSchema>;
type Values = z.output<typeof targetSchema>;

export function TargetDialog() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const form = useForm<InputValues, unknown, Values>({ resolver: zodResolver(targetSchema), defaultValues: { kind: "custom", name: "", url: "", method: "GET", statusLow: 200, statusHigh: 399, requiredLiteral: "", forbiddenLiteral: "" } });
  const kind = useWatch({ control: form.control, name: "kind" });
  async function submit(values: Values) {
    try {
      await api.post<TargetDto>("/targets", { name: values.name, kind: values.kind, enabled: true, method: values.method, url: values.kind === "custom" ? values.url : null, headers: {}, secret_headers: {}, body: null, status_ranges: [[values.statusLow, values.statusHigh]], required_literals: values.requiredLiteral ? [values.requiredLiteral] : [], forbidden_literals: values.forbiddenLiteral ? [values.forbiddenLiteral] : [], required_patterns: [], forbidden_patterns: [] });
      toast.success("Target created"); await queryClient.invalidateQueries({ queryKey: ["targets"] }); form.reset(); setOpen(false);
    } catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not create target."); }
  }
  return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button size="sm"><Plus />Add target</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>Add target check</DialogTitle><DialogDescription>Classify proxies independently for a built-in search engine or custom HTTP target.</DialogDescription></DialogHeader><form className="space-y-4" onSubmit={form.handleSubmit(submit)}><div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label>Target kind</Label><Controller control={form.control} name="kind" render={({ field }) => <Select value={field.value} onValueChange={(value) => { field.onChange(value); if (value === "google") form.setValue("name", "Google Search"); if (value === "bing") form.setValue("name", "Bing Search"); }}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="custom">Custom URL</SelectItem><SelectItem value="google">Google Search</SelectItem><SelectItem value="bing">Bing Search</SelectItem></SelectContent></Select>} /></div><div className="space-y-2"><Label htmlFor="target-name">Name</Label><Input id="target-name" {...form.register("name")} />{form.formState.errors.name ? <p className="text-xs text-destructive">Enter a target name.</p> : null}</div></div>{kind === "custom" ? <div className="space-y-2"><Label htmlFor="target-url">URL</Label><Input id="target-url" type="url" placeholder="https://example.com/health" {...form.register("url")} />{form.formState.errors.url ? <p className="text-xs text-destructive">{form.formState.errors.url.message}</p> : <p className="text-xs text-muted-foreground">Private, loopback, and metadata addresses are rejected.</p>}</div> : <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">Proxy Hide supplies and maintains the built-in {kind === "google" ? "Google" : "Bing"} request.</div>}<div className="grid grid-cols-3 gap-3"><div className="space-y-2"><Label>Method</Label><Controller control={form.control} name="method" render={({ field }) => <Select value={field.value} onValueChange={field.onChange}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="GET">GET</SelectItem><SelectItem value="HEAD">HEAD</SelectItem><SelectItem value="POST">POST</SelectItem></SelectContent></Select>} /></div><div className="space-y-2"><Label htmlFor="status-low">Status from</Label><Input id="status-low" type="number" {...form.register("statusLow")} /></div><div className="space-y-2"><Label htmlFor="status-high">Status to</Label><Input id="status-high" type="number" {...form.register("statusHigh")} />{form.formState.errors.statusHigh ? <p className="text-xs text-destructive">{form.formState.errors.statusHigh.message}</p> : null}</div></div><div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor="required-literal">Response must contain</Label><Input id="required-literal" placeholder="Optional literal" {...form.register("requiredLiteral")} /></div><div className="space-y-2"><Label htmlFor="forbidden-literal">Response must not contain</Label><Input id="forbidden-literal" placeholder="Optional literal" {...form.register("forbiddenLiteral")} /></div></div><DialogFooter><DialogClose asChild><Button type="button" variant="outline">Cancel</Button></DialogClose><Button type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? <LoaderCircle className="animate-spin" /> : null}Create target</Button></DialogFooter></form></DialogContent></Dialog>;
}
