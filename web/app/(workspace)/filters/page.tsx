"use client";

import { Braces, Eye, MoreHorizontal, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { FilterDialog } from "@/components/dialogs/filter-dialog";
import { DataToolbar } from "@/components/data-toolbar";
import { PageHeader } from "@/components/page-header";
import { PaginationBar } from "@/components/pagination-bar";
import { QueryEmpty, QueryError, TableLoading } from "@/components/query-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useResourceParams } from "@/hooks/use-resource-params";
import { api, ApiError } from "@/lib/api/client";
import { useFilters } from "@/lib/api/resources";
import type { ProxyFilter } from "@/lib/api/types";
import { formatRelativeTime } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

function fallbackRules(filter: ProxyFilter) {
  const rules: Record<string, unknown>[] = [{ op: "predicate", field: "health", operator: "eq", value: "healthy" }, { op: "predicate", field: "score", operator: "gte", value: filter.minimumScore }];
  if (filter.countryCodes.length) rules.push({ op: "predicate", field: "country", operator: "in", value: filter.countryCodes });
  return { version: 1, root: { op: "all", rules } };
}

export default function FiltersPage() {
  const { params, update } = useResourceParams();
  const query = useFilters({ page: Number(params.page), page_size: Number(params.page_size) });
  const queryClient = useQueryClient();
  const rows = (query.data?.items ?? []).filter((filter) => `${filter.name} ${filter.summary}`.toLowerCase().includes(params.q.toLowerCase()));

  async function preview(filter: ProxyFilter) {
    try {
      const result = await api.post<{ count: number }>("/filters/preview", { rules: filter.rules ?? fallbackRules(filter), catalog_selection: "combined", sample_size: 0 });
      toast.success(`${result.count} proxies currently match ${filter.name}`);
    } catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not preview the filter."); }
  }

  async function remove(filter: ProxyFilter) {
    if (!window.confirm(`Delete ${filter.name}? Pools using it must be removed first.`)) return;
    try {
      await api.delete(`/filters/${filter.id}`);
      await queryClient.invalidateQueries({ queryKey: ["filters"] });
      toast.success("Filter deleted");
    } catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not delete the filter."); }
  }

  return <>
    <PageHeader title="Filters" description="Versioned rules that select qualified proxies from private and global inventory." actions={<FilterDialog />} />
    <div className="p-4 sm:p-6"><Card className="overflow-hidden">
      <DataToolbar value={params.q} onChange={(q) => update({ q })} placeholder="Search filters" />
      {query.isLoading ? <TableLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} /> : rows.length === 0 ? <QueryEmpty title="No filters" description="Create a rule set to qualify proxies for a pool." /> : <>
        <Table><TableHeader><TableRow><TableHead className="pl-5">Filter</TableHead><TableHead>Rule</TableHead><TableHead>Countries</TableHead><TableHead>Matching</TableHead><TableHead>Updated</TableHead><TableHead className="w-12" /></TableRow></TableHeader><TableBody>{rows.map((filter) => <TableRow key={filter.id}>
          <TableCell className="pl-5"><div className="flex items-center gap-3"><div className="flex size-8 items-center justify-center rounded-md bg-muted"><Braces className="size-4 text-muted-foreground" /></div><p className="font-medium">{filter.name}</p></div></TableCell>
          <TableCell className="max-w-md"><p className="truncate font-mono text-xs">{filter.summary}</p></TableCell>
          <TableCell><div className="flex gap-1">{filter.countryCodes.length ? filter.countryCodes.slice(0, 4).map((country) => <Badge variant="outline" key={country}>{country}</Badge>) : <span className="text-muted-foreground">Any</span>}</div></TableCell>
          <TableCell>{filter.matchingCount === null ? <Button variant="ghost" size="sm" onClick={() => void preview(filter)}><Eye />Preview</Button> : <span className="font-semibold tabular-nums">{filter.matchingCount}</span>}</TableCell>
          <TableCell className="text-xs text-muted-foreground">{formatRelativeTime(filter.updatedAt)}</TableCell>
          <TableCell><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`${filter.name} actions`}><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => void preview(filter)}><Eye />Preview matches</DropdownMenuItem><DropdownMenuSeparator /><DropdownMenuItem variant="destructive" onSelect={() => void remove(filter)}><Trash2 />Delete filter</DropdownMenuItem></DropdownMenuContent></DropdownMenu></TableCell>
        </TableRow>)}</TableBody></Table>
        <PaginationBar page={query.data?.page ?? 1} pageSize={query.data?.page_size ?? 25} total={query.data?.total ?? 0} onPageChange={(page) => update({ page: String(page) }, false)} />
      </>}
    </Card></div>
  </>;
}
