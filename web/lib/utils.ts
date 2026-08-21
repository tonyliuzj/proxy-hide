import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat("en-GB").format(value);
}

export function formatPercent(value: number) {
  return new Intl.NumberFormat("en-GB", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value / 100);
}

export function formatBytes(value: number) {
  if (value === 0) return "0 B";
  const unit = 1024;
  const index = Math.min(Math.floor(Math.log(value) / Math.log(unit)), 4);
  const units = ["B", "KB", "MB", "GB", "TB"];
  return `${(value / unit ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

export function formatRelativeTime(timestamp: string) {
  const seconds = Math.round((new Date(timestamp).getTime() - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (Math.abs(seconds) < 60) return formatter.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
  return formatter.format(Math.round(hours / 24), "day");
}
