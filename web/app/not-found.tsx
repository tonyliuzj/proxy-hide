import Link from "next/link";
import { ArrowLeft, RouteOff } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return <main className="flex min-h-screen items-center justify-center p-6"><div className="max-w-md text-center"><div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-md border bg-card"><RouteOff className="size-6 text-muted-foreground" /></div><h1 className="text-xl font-semibold">Page not found</h1><p className="mt-2 text-sm text-muted-foreground">The page may have moved or you may not have access to this workspace resource.</p><Button asChild className="mt-5"><Link href="/dashboard"><ArrowLeft />Back to dashboard</Link></Button></div></main>;
}
