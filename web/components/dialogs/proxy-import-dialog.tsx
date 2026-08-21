"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { FileUp, LoaderCircle, Upload } from "lucide-react";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api/client";
import type { ProxyImportPreviewDto, ProxyImportResultDto } from "@/lib/api/dto";
import { useQueryClient } from "@tanstack/react-query";

const schema = z.object({ text: z.string().min(1, "Paste at least one proxy").max(20_000_000), defaultProtocol: z.enum(["http", "https", "socks4a", "socks5"]) });
type Values = z.infer<typeof schema>;

export function ProxyImportDialog({ admin = false }: { admin?: boolean }) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<ProxyImportPreviewDto>();
  const [working, setWorking] = useState(false);
  const queryClient = useQueryClient();
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { text: "", defaultProtocol: "http" } });
  const basePath = admin ? "/admin/proxies" : "/proxies";

  async function previewImport(values: Values) {
    setWorking(true);
    try {
      const result = await api.post<ProxyImportPreviewDto>(`${basePath}/import/preview`, { text: values.text, default_protocol: values.defaultProtocol });
      setPreview(result);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not preview this import.");
    } finally {
      setWorking(false);
    }
  }

  async function commitImport() {
    const values = form.getValues();
    setWorking(true);
    try {
      const result = await api.post<ProxyImportResultDto>(`${basePath}/import`, { text: values.text, default_protocol: values.defaultProtocol });
      toast.success(`${result.imported} proxies queued for initial checks`);
      await queryClient.invalidateQueries({ queryKey: admin ? ["admin", "proxies"] : ["proxies"] });
      setOpen(false);
      setPreview(undefined);
      form.reset();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not import proxies.");
    } finally {
      setWorking(false);
    }
  }

  return <Dialog open={open} onOpenChange={(value) => { setOpen(value); if (!value) setPreview(undefined); }}>
    <DialogTrigger asChild><Button size="sm"><Upload />Import proxies</Button></DialogTrigger>
    <DialogContent className="max-w-2xl">
      <DialogHeader><DialogTitle>Import {admin ? "global" : "private"} proxies</DialogTitle><DialogDescription>Paste one proxy per line. Credentials are encrypted after import and never shown again.</DialogDescription></DialogHeader>
      <form className="space-y-4" onSubmit={form.handleSubmit(previewImport)}>
        <div className="grid gap-4 sm:grid-cols-[180px_1fr]">
          <div className="space-y-2"><Label>Default protocol</Label><Controller control={form.control} name="defaultProtocol" render={({ field }) => <Select value={field.value} onValueChange={(value) => { field.onChange(value); setPreview(undefined); }}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="http">HTTP</SelectItem><SelectItem value="https">HTTPS</SelectItem><SelectItem value="socks4a">SOCKS4a</SelectItem><SelectItem value="socks5">SOCKS5</SelectItem></SelectContent></Select>} /></div>
          <div className="space-y-2"><Label htmlFor="proxy-file">Load text file</Label><div className="relative"><Input id="proxy-file" type="file" accept=".txt,text/plain" className="file:mr-3 file:border-0 file:bg-transparent file:text-sm" onChange={async (event) => { const file = event.target.files?.[0]; if (file) { form.setValue("text", await file.text(), { shouldValidate: true }); setPreview(undefined); } }} /><FileUp className="pointer-events-none absolute right-3 top-2.5 size-4 text-muted-foreground" /></div></div>
        </div>
        <div className="space-y-2"><Label htmlFor="proxy-text">Proxy list</Label><Textarea id="proxy-text" rows={10} className="font-mono text-xs" placeholder={"185.44.72.19:3128\nsocks5://user:password@51.89.12.204:1080"} {...form.register("text", { onChange: () => setPreview(undefined) })} />{form.formState.errors.text ? <p className="text-xs text-destructive">{form.formState.errors.text.message}</p> : <p className="text-xs text-muted-foreground">Supports URI, host:port, and host:port:username:password formats.</p>}</div>
        {preview ? <div className="grid grid-cols-3 divide-x rounded-md border bg-muted/30 py-3 text-center"><div><p className="text-lg font-semibold text-emerald-700">{preview.valid_count}</p><p className="text-xs text-muted-foreground">Valid</p></div><div><p className="text-lg font-semibold text-amber-700">{preview.duplicate_count}</p><p className="text-xs text-muted-foreground">Duplicates</p></div><div><p className="text-lg font-semibold text-red-700">{preview.invalid_count}</p><p className="text-xs text-muted-foreground">Invalid</p></div></div> : null}
        <DialogFooter><DialogClose asChild><Button variant="outline" type="button">Cancel</Button></DialogClose>{preview ? <Button type="button" onClick={commitImport} disabled={working || preview.valid_count === 0}>{working ? <LoaderCircle className="animate-spin" /> : null}Import {preview.valid_count}</Button> : <Button type="submit" disabled={working}>{working ? <LoaderCircle className="animate-spin" /> : null}Preview import</Button>}</DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
