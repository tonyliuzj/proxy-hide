"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { TrafficPoint } from "@/lib/api/types";

function label(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

export function TrafficChart({ data }: { data: TrafficPoint[] }) {
  const chartData = data.map((point) => ({ ...point, label: label(point.bucketStart) }));
  return <div className="h-64 w-full" role="img" aria-label="Requests and failures over time"><ResponsiveContainer width="100%" height="100%"><AreaChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}><defs><linearGradient id="requestsFill" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#087f70" stopOpacity={0.25} /><stop offset="95%" stopColor="#087f70" stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="#e5e9ea" strokeDasharray="3 3" vertical={false} /><XAxis dataKey="label" axisLine={false} tickLine={false} minTickGap={32} /><YAxis axisLine={false} tickLine={false} /><Tooltip contentStyle={{ border: "1px solid #dce2e4", borderRadius: 6, boxShadow: "0 4px 16px rgb(0 0 0 / 0.08)", fontSize: 12 }} /><Area type="monotone" dataKey="requests" stroke="#087f70" strokeWidth={2} fill="url(#requestsFill)" /><Area type="monotone" dataKey="failures" stroke="#c43d42" strokeWidth={1.5} fill="transparent" /></AreaChart></ResponsiveContainer></div>;
}
