import Link from "next/link";
import { Network } from "lucide-react";
import { cn } from "@/lib/utils";

export function Brand({ compact = false, admin = false, href, className }: { compact?: boolean; admin?: boolean; href?: string; className?: string }) {
  return <Link href={href ?? (admin ? "/admin" : "/dashboard")} className={cn("flex min-w-0 items-center gap-2.5", className)}><span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-[#14a894] text-white shadow-sm"><Network className="size-4.5" /></span>{compact ? null : <span className="min-w-0"><span className="block truncate text-sm font-semibold text-white">Proxy Hide</span><span className="block truncate text-[11px] text-white/50">{admin ? "Platform admin" : "Gateway control"}</span></span>}</Link>;
}
