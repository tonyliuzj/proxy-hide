"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, LoaderCircle, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { AuthRouteError, AuthRouteLoading } from "@/components/auth-route-state";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api/client";
import type { SessionDto, SetupStatusDto } from "@/lib/api/dto";
import { SETUP_STATUS_QUERY_KEY, useSetupStatusQuery } from "@/lib/api/hooks";

export const setupSchema = z.object({
  email: z.email("Enter a valid email address"),
  password: z.string().min(12, "Use at least 12 characters").max(1024),
  confirmPassword: z.string().min(1, "Confirm your password").max(1024),
}).refine((values) => values.password === values.confirmPassword, { message: "Passwords do not match", path: ["confirmPassword"] });

type SetupValues = z.infer<typeof setupSchema>;

export default function SetupPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const setupStatus = useSetupStatusQuery();
  const [showPassword, setShowPassword] = useState(false);
  const [serverError, setServerError] = useState("");
  const form = useForm<SetupValues>({ resolver: zodResolver(setupSchema), defaultValues: { email: "", password: "", confirmPassword: "" } });
  const session = useQuery({
    queryKey: ["session", "setup"],
    queryFn: () => api.get<SessionDto>("/auth/me"),
    enabled: setupStatus.data?.setup_required === false,
    staleTime: 30_000,
    retry: 1,
  });

  useEffect(() => {
    if (setupStatus.data?.setup_required !== false) return;
    if (session.data) {
      router.replace(session.data.user.role === "platform_admin" ? "/admin" : "/dashboard");
      return;
    }
    if (session.isError) router.replace("/login");
  }, [router, session.data, session.isError, setupStatus.data]);

  async function onSubmit(values: SetupValues) {
    setServerError("");
    try {
      const createdSession = await api.post<SessionDto>("/auth/setup", { email: values.email, password: values.password });
      queryClient.setQueryData<SetupStatusDto>(SETUP_STATUS_QUERY_KEY, { setup_required: false });
      queryClient.setQueryData(["session", "admin"], createdSession);
      router.replace(createdSession.user.role === "platform_admin" ? "/admin" : "/dashboard");
      router.refresh();
    } catch (error) {
      setServerError(error instanceof ApiError ? error.message : "Unable to create the administrator. Try again.");
      if (error instanceof ApiError && error.status === 409) void setupStatus.refetch();
    }
  }

  if (setupStatus.isError) return <AuthRouteError onRetry={() => void setupStatus.refetch()} />;
  if (setupStatus.data?.setup_required !== true) return <AuthRouteLoading label={setupStatus.data ? "Loading session" : undefined} />;

  return <main className="grid min-h-screen bg-[#edf1f1] lg:grid-cols-[minmax(0,1fr)_480px]"><section className="relative hidden overflow-hidden bg-[#172227] p-10 text-white lg:flex lg:flex-col"><div className="absolute inset-0 opacity-[0.08]" style={{ backgroundImage: "linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)", backgroundSize: "32px 32px" }} /><Brand admin href="/" className="relative z-10" /><div className="relative z-10 mt-auto max-w-xl pb-10"><div className="mb-5 flex size-11 items-center justify-center rounded-md border border-white/10 bg-white/5"><ShieldCheck className="size-5 text-[#38c8b2]" /></div><h1 className="text-3xl font-semibold leading-tight">Secure your Proxy Hide control plane.</h1><p className="mt-4 max-w-lg text-base leading-7 text-white/55">Create the first platform administrator before provisioning customer workspaces and proxy inventory.</p></div><p className="relative z-10 text-xs text-white/35">Proxy Hide initial setup</p></section><section className="flex min-h-screen items-center justify-center p-5 sm:p-8"><div className="w-full max-w-sm"><div className="mb-8 lg:hidden"><Brand admin href="/" className="[&_span_span]:!text-foreground" /></div><Card className="border-0 shadow-sm sm:border"><CardHeader className="pb-4"><CardTitle className="text-lg">Create platform admin</CardTitle><CardDescription>This account manages workspaces and the global proxy catalog.</CardDescription></CardHeader><CardContent><form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)} noValidate><div className="space-y-2"><Label htmlFor="email">Admin email</Label><Input id="email" type="email" autoComplete="email" autoFocus aria-invalid={Boolean(form.formState.errors.email)} {...form.register("email")} />{form.formState.errors.email ? <p className="text-xs text-destructive">{form.formState.errors.email.message}</p> : null}</div><div className="space-y-2"><Label htmlFor="password">Password</Label><div className="relative"><Input id="password" type={showPassword ? "text" : "password"} autoComplete="new-password" className="pr-10" aria-invalid={Boolean(form.formState.errors.password)} {...form.register("password")} /><Button type="button" variant="ghost" size="icon-sm" className="absolute right-0.5 top-0.5 text-muted-foreground" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Hide passwords" : "Show passwords"}>{showPassword ? <EyeOff /> : <Eye />}</Button></div>{form.formState.errors.password ? <p className="text-xs text-destructive">{form.formState.errors.password.message}</p> : <p className="text-xs text-muted-foreground">At least 12 characters.</p>}</div><div className="space-y-2"><Label htmlFor="confirm-password">Confirm password</Label><Input id="confirm-password" type={showPassword ? "text" : "password"} autoComplete="new-password" aria-invalid={Boolean(form.formState.errors.confirmPassword)} {...form.register("confirmPassword")} />{form.formState.errors.confirmPassword ? <p className="text-xs text-destructive">{form.formState.errors.confirmPassword.message}</p> : null}</div>{serverError ? <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{serverError}</div> : null}<Button className="w-full" type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? <LoaderCircle className="animate-spin" /> : <ShieldCheck />}{form.formState.isSubmitting ? "Creating administrator" : "Create administrator"}</Button></form></CardContent></Card><p className="mt-5 text-center text-xs text-muted-foreground">Initial setup closes after this account is created.</p></div></section></main>;
}
