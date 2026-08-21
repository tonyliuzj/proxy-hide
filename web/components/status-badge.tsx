import { Badge, type badgeVariants } from "@/components/ui/badge";
import type { VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const tones: Record<string, VariantProps<typeof badgeVariants>["variant"]> = {
  healthy: "success",
  active: "success",
  available: "success",
  passed: "success",
  succeeded: "success",
  enabled: "success",
  degraded: "warning",
  rate_limited: "warning",
  running: "info",
  queued: "info",
  unknown: "secondary",
  paused: "secondary",
  disabled: "secondary",
  unhealthy: "destructive",
  down: "destructive",
  blocked: "destructive",
  unavailable: "destructive",
  failed: "destructive",
  timeout: "warning",
  suspended: "destructive",
  dead: "destructive",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const label = status.replaceAll("_", " ");
  return <Badge variant={tones[status] ?? "outline"} className={cn("capitalize", className)}>{label}</Badge>;
}
