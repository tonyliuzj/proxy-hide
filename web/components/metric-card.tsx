import type { LucideIcon } from "lucide-react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function MetricCard({ label, value, hint, change, icon: Icon }: { label: string; value: string; hint: string; change?: number; icon: LucideIcon }) {
  const favourable = label.toLowerCase().includes("latency") ? (change ?? 0) < 0 : (change ?? 0) > 0;
  const ChangeIcon = change === 0 || change === undefined ? Minus : change > 0 ? ArrowUpRight : ArrowDownRight;
  return <Card><CardContent className="p-4"><div className="flex items-start justify-between"><div className="flex size-8 items-center justify-center rounded-md bg-muted text-muted-foreground"><Icon className="size-4" /></div>{change !== undefined ? <span className={cn("flex items-center text-xs font-medium", change === 0 ? "text-muted-foreground" : favourable ? "text-emerald-700" : "text-red-700")}><ChangeIcon className="mr-0.5 size-3.5" />{Math.abs(change)}%</span> : null}</div><p className="mt-4 text-2xl font-semibold tabular-nums">{value}</p><p className="mt-1 text-xs font-medium text-foreground/70">{label}</p><p className="mt-0.5 text-xs text-muted-foreground">{hint}</p></CardContent></Card>;
}
