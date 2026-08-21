"use client";

import { LoaderCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import type { SessionDto } from "@/lib/api/dto";
import { useApiQuery } from "@/lib/api/hooks";

export default function HomePage() {
  const router = useRouter();
  const session = useApiQuery<SessionDto>(["session", "root"], "/auth/me");
  useEffect(() => {
    if (session.data) router.replace(session.data.user.role === "platform_admin" ? "/admin" : "/dashboard");
    if (session.isError) router.replace("/login");
  }, [router, session.data, session.isError]);
  return <main className="flex min-h-screen items-center justify-center"><LoaderCircle className="size-5 animate-spin text-muted-foreground" aria-label="Loading session" /></main>;
}
