"use client";

import { KeyRound, TriangleAlert } from "lucide-react";
import { CopyButton } from "@/components/copy-button";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import type { EndpointCredentials } from "@/lib/api/types";

export function EndpointCredentialsDialog({ credentials, onClose }: { credentials?: EndpointCredentials; onClose: () => void }) {
  return <Dialog open={Boolean(credentials)} onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent className="max-w-2xl" showCloseButton={false}>
      <DialogHeader><div className="mb-1 flex size-9 items-center justify-center rounded-md bg-emerald-50 text-emerald-700"><KeyRound className="size-4" /></div><DialogTitle>Endpoint credentials</DialogTitle><DialogDescription>The secret cannot be recovered after this dialog closes.</DialogDescription></DialogHeader>
      {credentials ? <div className="space-y-4">
        <div className="flex gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><TriangleAlert className="mt-0.5 size-4 shrink-0" /><p>Store these credentials now. Regenerating the secret immediately invalidates the previous one.</p></div>
        <div className="space-y-2"><Label>Secure listener</Label><div className="flex min-w-0 items-center rounded-md border bg-muted/30 pl-3"><code className="min-w-0 flex-1 overflow-x-auto py-2 text-xs">{credentials.secureUrl}</code><CopyButton value={credentials.secureUrl} label="Copy secure URL" /></div></div>
        <div className="space-y-2"><Label>Plaintext compatibility listener</Label><div className="flex min-w-0 items-center rounded-md border bg-muted/30 pl-3"><code className="min-w-0 flex-1 overflow-x-auto py-2 text-xs">{credentials.plaintextUrl}</code><CopyButton value={credentials.plaintextUrl} label="Copy plaintext URL" /></div><p className="text-xs text-muted-foreground">Port 9000 exposes Basic credentials in plaintext. Use it only on a trusted network.</p></div>
      </div> : null}
      <DialogFooter><Button onClick={onClose}>I stored the credentials</Button></DialogFooter>
    </DialogContent>
  </Dialog>;
}
