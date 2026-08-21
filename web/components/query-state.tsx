import { AlertTriangle, Inbox, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export function TableLoading({ rows = 6 }: { rows?: number }) {
  return <div className="space-y-2 p-4">{Array.from({ length: rows }).map((_, index) => <Skeleton key={index} className="h-10 w-full" />)}</div>;
}

export function QueryError({ onRetry, message = "We could not load this data from the API." }: { onRetry: () => void; message?: string }) {
  return <div className="flex min-h-56 flex-col items-center justify-center p-8 text-center"><div className="mb-3 flex size-10 items-center justify-center rounded-md bg-red-50 text-destructive"><AlertTriangle className="size-5" /></div><p className="text-sm font-medium">Data unavailable</p><p className="mt-1 max-w-sm text-sm text-muted-foreground">{message}</p><Button variant="outline" size="sm" className="mt-4" onClick={onRetry}><RotateCcw />Retry</Button></div>;
}

export function QueryEmpty({ title = "Nothing here yet", description }: { title?: string; description: string }) {
  return <div className="flex min-h-56 flex-col items-center justify-center p-8 text-center"><div className="mb-3 flex size-10 items-center justify-center rounded-md bg-muted text-muted-foreground"><Inbox className="size-5" /></div><p className="text-sm font-medium">{title}</p><p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p></div>;
}
