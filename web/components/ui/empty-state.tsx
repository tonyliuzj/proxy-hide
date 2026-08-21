import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export function EmptyState({ icon: Icon, title, description, action, className }: { icon: LucideIcon; title: string; description: string; action?: React.ReactNode; className?: string }) {
  return <div className={cn("flex min-h-56 flex-col items-center justify-center gap-3 p-8 text-center", className)}><div className="flex size-10 items-center justify-center rounded-md border bg-muted/40"><Icon className="size-5 text-muted-foreground" /></div><div><p className="text-sm font-medium">{title}</p><p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p></div>{action}</div>;
}
