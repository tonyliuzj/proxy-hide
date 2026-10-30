"use client";

import { KeyRound, Network, TriangleAlert } from "lucide-react";
import { CopyButton } from "@/components/copy-button";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import type { EndpointCredentials } from "@/lib/api/types";

function CopyRow({ label, value, copyLabel, note }: { label: string; value: string; copyLabel: string; note?: string }) {
  return <div className="space-y-2"><Label>{label}</Label><div className="flex min-w-0 items-center rounded-md border bg-muted/30 pl-3"><code className="min-w-0 flex-1 overflow-x-auto py-2 text-xs">{value}</code><CopyButton value={value} label={copyLabel} /></div>{note ? <p className="text-xs text-muted-foreground">{note}</p> : null}</div>;
}

export function EndpointCredentialsDialog({ credentials, onClose }: { credentials?: EndpointCredentials; onClose: () => void }) {
  const address = credentials?.proxyAddress ?? null;
  const open = Boolean(credentials);
  return <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
    <DialogContent className="max-w-2xl" showCloseButton={false}>
      {credentials && address && credentials.secret === null ? <>
        <DialogHeader><div className="mb-1 flex size-9 items-center justify-center rounded-md bg-emerald-50 text-emerald-700"><Network className="size-4" /></div><DialogTitle>Endpoint ready</DialogTitle><DialogDescription>Point an app at this address. No username or password is needed.</DialogDescription></DialogHeader>
        <div className="space-y-4">
          <CopyRow label="Proxy address" value={address} copyLabel="Copy address" />
          <CopyRow label="HTTP proxy URL" value={`http://${address}`} copyLabel="Copy HTTP URL" note="Works for http and https sites; https goes through CONNECT." />
          <CopyRow label="SOCKS5 proxy URL" value={`socks5h://${address}`} copyLabel="Copy SOCKS5 URL" note="The same port also speaks SOCKS5." />
          <p className="text-xs text-muted-foreground">Only clients in the allowed networks can connect. From outside the Docker network, the gateway may see a translated address such as the bridge gateway, so allow that instead of the original client.</p>
        </div>
      </> : <>
        <DialogHeader><div className="mb-1 flex size-9 items-center justify-center rounded-md bg-emerald-50 text-emerald-700"><KeyRound className="size-4" /></div><DialogTitle>Endpoint credentials</DialogTitle><DialogDescription>The secret cannot be recovered after this dialog closes.</DialogDescription></DialogHeader>
        {credentials ? <div className="space-y-4">
          <div className="flex gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><TriangleAlert className="mt-0.5 size-4 shrink-0" /><p>Store these credentials now. Regenerating the secret immediately invalidates the previous one.</p></div>
          {credentials.secureUrl ? <CopyRow label="Secure listener" value={credentials.secureUrl} copyLabel="Copy secure URL" /> : null}
          {credentials.plaintextUrl ? <CopyRow label="Plaintext compatibility listener" value={credentials.plaintextUrl} copyLabel="Copy plaintext URL" note="Port 9000 exposes Basic credentials in plaintext. Use it only on a trusted network." /> : null}
        </div> : null}
      </>}
      <DialogFooter><Button onClick={onClose}>{credentials && credentials.secret === null ? "Done" : "I stored the credentials"}</Button></DialogFooter>
    </DialogContent>
  </Dialog>;
}
