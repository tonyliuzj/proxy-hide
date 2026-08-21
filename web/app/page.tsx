"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { AuthRouteError, AuthRouteLoading } from "@/components/auth-route-state";
import { api } from "@/lib/api/client";
import type { SessionDto } from "@/lib/api/dto";
import { useSetupStatusQuery } from "@/lib/api/hooks";

export default function HomePage() {
  const router = useRouter();
  const setupStatus = useSetupStatusQuery();
  const session = useQuery({
    queryKey: ["session", "root"],
    queryFn: () => api.get<SessionDto>("/auth/me"),
    enabled: setupStatus.data?.setup_required === false,
    staleTime: 30_000,
    retry: 1,
  });
  useEffect(() => {
    if (setupStatus.data?.setup_required) {
      router.replace("/setup");
      return;
    }
    if (setupStatus.data?.setup_required !== false) return;
    if (session.data) router.replace(session.data.user.role === "platform_admin" ? "/admin" : "/dashboard");
    if (session.isError) router.replace("/login");
  }, [router, session.data, session.isError, setupStatus.data]);
  if (setupStatus.isError) return <AuthRouteError onRetry={() => void setupStatus.refetch()} />;
  return <AuthRouteLoading label={setupStatus.data?.setup_required === false ? "Loading session" : undefined} />;
}
