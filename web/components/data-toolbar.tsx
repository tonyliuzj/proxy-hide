"use client";

import { Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export function DataToolbar({ value, onChange, placeholder = "Search", filters, actions, className }: { value: string; onChange: (value: string) => void; placeholder?: string; filters?: React.ReactNode; actions?: React.ReactNode; className?: string }) {
  return <div className={cn("flex flex-col gap-2 border-b p-3 sm:flex-row sm:items-center", className)}><div className="relative min-w-0 flex-1 sm:max-w-xs"><Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" /><Input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="pl-8 pr-8" />{value ? <Button variant="ghost" size="icon-sm" className="absolute right-0.5 top-0.5" onClick={() => onChange("")} aria-label="Clear search"><X /></Button> : null}</div>{filters ? <div className="flex flex-wrap items-center gap-2">{filters}</div> : null}{actions ? <div className="sm:ml-auto">{actions}</div> : null}</div>;
}
