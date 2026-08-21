"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }
  return <Tooltip><TooltipTrigger asChild><Button variant="ghost" size="icon-sm" onClick={copy} aria-label={label}>{copied ? <Check className="text-emerald-600" /> : <Copy />}</Button></TooltipTrigger><TooltipContent>{copied ? "Copied" : label}</TooltipContent></Tooltip>;
}
