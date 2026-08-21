import { AlertTriangle, LoaderCircle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

export function AuthRouteLoading({ label = "Checking platform status" }: { label?: string }) {
  return <main className="flex min-h-screen items-center justify-center bg-[#edf1f1]"><LoaderCircle className="size-5 animate-spin text-muted-foreground" aria-label={label} /></main>;
}

export function AuthRouteError({ onRetry }: { onRetry: () => void }) {
  return <main className="flex min-h-screen items-center justify-center bg-[#edf1f1] p-5"><div className="w-full max-w-sm rounded-md border bg-card p-6 text-center shadow-sm"><div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-md bg-red-50 text-destructive"><AlertTriangle className="size-5" /></div><h1 className="text-base font-semibold">Platform unavailable</h1><p className="mt-2 text-sm leading-6 text-muted-foreground">Proxy Hide could not determine whether initial setup is required.</p><Button variant="outline" className="mt-5" onClick={onRetry}><RotateCcw />Retry</Button></div></main>;
}
