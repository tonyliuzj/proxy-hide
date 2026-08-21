import { Button } from "@/components/ui/button";

export function PaginationBar({ page, pageSize, total, onPageChange }: { page: number; pageSize: number; total: number; onPageChange: (page: number) => void }) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return <div className="flex items-center justify-between border-t px-4 py-3 text-xs text-muted-foreground"><span>{from}-{to} of {total}</span><div className="flex gap-2"><Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>Previous</Button><Button variant="outline" size="sm" disabled={to >= total} onClick={() => onPageChange(page + 1)}>Next</Button></div></div>;
}
