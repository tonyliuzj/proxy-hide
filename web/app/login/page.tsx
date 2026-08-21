"use client";

import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { Eye, EyeOff, LoaderCircle, LockKeyhole } from "lucide-react";
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
import type { SessionDto } from "@/lib/api/dto";
import { useSetupStatusQuery } from "@/lib/api/hooks";

export const loginSchema = z.object({
  email: z.email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password").max(1024),
});

type LoginValues = z.infer<typeof loginSchema>;

export default function LoginPage() {
  const router = useRouter();
  const setupStatus = useSetupStatusQuery();
  const [showPassword, setShowPassword] = useState(false);
  const [serverError, setServerError] = useState("");
  const form = useForm<LoginValues>({ resolver: zodResolver(loginSchema), defaultValues: { email: "", password: "" } });

  useEffect(() => {
    if (setupStatus.data?.setup_required) router.replace("/setup");
  }, [router, setupStatus.data]);

  async function onSubmit(values: LoginValues) {
    setServerError("");
    try {
      const session = await api.post<SessionDto>("/auth/login", values);
      router.push(session.user.role === "platform_admin" ? "/admin" : "/dashboard");
      router.refresh();
    } catch (error) {
      setServerError(error instanceof ApiError ? error.message : "Unable to sign in. Try again.");
    }
  }

  if (setupStatus.isError) return <AuthRouteError onRetry={() => void setupStatus.refetch()} />;
  if (setupStatus.data?.setup_required !== false) return <AuthRouteLoading />;

  return <main className="grid min-h-screen bg-[#edf1f1] lg:grid-cols-[minmax(0,1fr)_480px]"><section className="relative hidden overflow-hidden bg-[#172227] p-10 text-white lg:flex lg:flex-col"><div className="absolute inset-0 opacity-[0.08]" style={{ backgroundImage: "linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)", backgroundSize: "32px 32px" }} /><Brand className="relative z-10" /><div className="relative z-10 mt-auto max-w-xl pb-10"><div className="mb-5 flex size-11 items-center justify-center rounded-md border border-white/10 bg-white/5"><LockKeyhole className="size-5 text-[#38c8b2]" /></div><h1 className="text-3xl font-semibold leading-tight">Proxy operations, contained in your workspace.</h1><p className="mt-4 max-w-lg text-base leading-7 text-white/55">Monitor proxy health, materialise qualified pools, and operate authenticated gateway endpoints from one control plane.</p></div><p className="relative z-10 text-xs text-white/35">Proxy Hide control plane</p></section><section className="flex min-h-screen items-center justify-center p-5 sm:p-8"><div className="w-full max-w-sm"><div className="mb-8 lg:hidden"><Brand className="[&_span_span]:!text-foreground" /></div><Card className="border-0 shadow-sm sm:border"><CardHeader className="pb-4"><CardTitle className="text-lg">Sign in</CardTitle><CardDescription>Use your workspace owner or platform admin account.</CardDescription></CardHeader><CardContent><form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)} noValidate><div className="space-y-2"><Label htmlFor="email">Email</Label><Input id="email" type="email" autoComplete="email" autoFocus aria-invalid={Boolean(form.formState.errors.email)} {...form.register("email")} />{form.formState.errors.email ? <p className="text-xs text-destructive">{form.formState.errors.email.message}</p> : null}</div><div className="space-y-2"><Label htmlFor="password">Password</Label><div className="relative"><Input id="password" type={showPassword ? "text" : "password"} autoComplete="current-password" className="pr-10" aria-invalid={Boolean(form.formState.errors.password)} {...form.register("password")} /><Button type="button" variant="ghost" size="icon-sm" className="absolute right-0.5 top-0.5 text-muted-foreground" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? <EyeOff /> : <Eye />}</Button></div>{form.formState.errors.password ? <p className="text-xs text-destructive">{form.formState.errors.password.message}</p> : null}</div>{serverError ? <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{serverError}</div> : null}<Button className="w-full" type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? <LoaderCircle className="animate-spin" /> : null}{form.formState.isSubmitting ? "Signing in" : "Sign in"}</Button></form></CardContent></Card><p className="mt-5 text-center text-xs text-muted-foreground">Protected by secure, same-site sessions.</p></div></section></main>;
}
