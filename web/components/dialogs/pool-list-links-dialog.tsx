"use client";

import { Link2, LoaderCircle, TriangleAlert, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { CopyButton } from "@/components/copy-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api, ApiError } from "@/lib/api/client";
import type { PoolListLinkCreatedDto } from "@/lib/api/dto";
import { usePoolListLinks } from "@/lib/api/resources";
import type { Pool, PoolListLink } from "@/lib/api/types";
import { formatRelativeTime } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

function CopyRow({ label, value, note }: { label: string; value: string; note?: string }) {
  return <div className="space-y-1.5"><Label>{label}</Label><div className="flex min-w-0 items-center rounded-md border bg-muted/30 pl-3"><code className="min-w-0 flex-1 overflow-x-auto py-2 text-xs">{value}</code><CopyButton value={value} label={`Copy ${label}`} /></div>{note ? <p className="text-xs text-muted-foreground">{note}</p> : null}</div>;
}

export function PoolListLinksDialog({ pool, onClose }: { pool: Pool; onClose: () => void }) {
  const links = usePoolListLinks(pool.id);
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [includeGlobal, setIncludeGlobal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<string>();

  async function create() {
    setBusy(true);
    try {
      const dto = await api.post<PoolListLinkCreatedDto>(`/pools/${pool.id}/list-links`, { name: name.trim(), include_global: includeGlobal });
      setCreated(dto.url);
      setName("");
      await queryClient.invalidateQueries({ queryKey: ["pool-list-links", pool.id] });
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not create the link.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(link: PoolListLink) {
    if (!window.confirm(`Revoke "${link.name}"? Apps using this URL will stop receiving the list immediately.`)) return;
    try {
      await api.delete(`/pools/${pool.id}/list-links/${link.id}`);
      await queryClient.invalidateQueries({ queryKey: ["pool-list-links", pool.id] });
      toast.success("Link revoked");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not revoke the link.");
    }
  }

  const items = links.data ?? [];
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent className="max-w-2xl">
      <DialogHeader><DialogTitle className="flex items-center gap-2"><Link2 className="size-4" />Share list link: {pool.name}</DialogTitle><DialogDescription>An app that fetches this URL gets the pool&apos;s current working proxies, always up to date. Anyone holding the URL can read the list, including any proxy passwords, so treat it like a password.</DialogDescription></DialogHeader>
      <div className="space-y-5">
        {created ? <div className="space-y-3 rounded-md border border-emerald-200 bg-emerald-50/50 p-3">
          <div className="flex gap-2 text-sm text-amber-900"><TriangleAlert className="mt-0.5 size-4 shrink-0" /><p>Copy it now. The full URL is not shown again.</p></div>
          <CopyRow label="Proxy URLs" value={created} note="One proxy per line, like http://user:pass@host:port." />
          <CopyRow label="host:port only" value={`${created}?format=hostport`} note="Plain host:port lines, for tools that do not accept URLs." />
          <CopyRow label="JSON" value={`${created}?format=json`} note="Add &protocol=http (or https, socks4a, socks5) to any of these to filter by type." />
        </div> : null}
        <div className="space-y-3 rounded-md border p-3">
          <div className="space-y-2"><Label htmlFor="list-link-name">New link name</Label><Input id="list-link-name" placeholder="Scraper" value={name} maxLength={120} onChange={(event) => setName(event.target.value)} /></div>
          <div className="flex items-center justify-between gap-4"><div><Label htmlFor="list-link-global">Include global catalog proxies</Label><p className="mt-1 text-xs text-muted-foreground">Off by default. Global proxy addresses are otherwise hidden from workspaces; turning this on reveals them to anyone with this link.</p></div><Switch id="list-link-global" checked={includeGlobal} onCheckedChange={setIncludeGlobal} /></div>
          <Button size="sm" disabled={busy || !name.trim()} onClick={() => void create()}>{busy ? <LoaderCircle className="animate-spin" /> : null}Create link</Button>
        </div>
        <div className="space-y-2">
          <p className="text-sm font-medium">Active links</p>
          {links.isLoading ? <p className="text-sm text-muted-foreground">Loading…</p> : !items.length ? <p className="text-sm text-muted-foreground">No links yet.</p> : <ul className="divide-y rounded-md border">{items.map((link) => <li key={link.id} className="flex items-center justify-between gap-3 px-3 py-2"><div className="min-w-0"><p className="truncate text-sm font-medium">{link.name} {link.includeGlobal ? <Badge variant="outline">includes global</Badge> : null}</p><p className="text-xs text-muted-foreground"><code>{link.tokenPrefix}…</code> · {link.lastUsedAt ? `last fetched ${formatRelativeTime(link.lastUsedAt)}` : "never fetched"}</p></div><Button variant="ghost" size="icon-sm" aria-label={`Revoke ${link.name}`} onClick={() => void revoke(link)}><Trash2 /></Button></li>)}</ul>}
        </div>
      </div>
    </DialogContent>
  </Dialog>;
}
