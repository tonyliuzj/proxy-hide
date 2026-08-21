import { cn } from "@/lib/utils";

export function PageHeader({ title, description, actions, className }: { title: string; description?: string; actions?: React.ReactNode; className?: string }) {
  return <div className={cn("flex flex-col gap-3 border-b bg-background px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6", className)}><div className="min-w-0"><h1 className="text-lg font-semibold leading-tight">{title}</h1>{description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}</div>{actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}</div>;
}
