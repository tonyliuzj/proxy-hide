"use client";

import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/page-header";
import { QueryError, TableLoading } from "@/components/query-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { PageDto } from "@/lib/api/dto";
import { useApiQuery } from "@/lib/api/hooks";

interface Member { id: string; email: string; role: string; active: boolean; must_change_password: boolean }
interface Token { id: string; name: string; token_prefix: string; scopes: string[]; last_used_at: string | null }

export default function AccessPage() {
  const members = useApiQuery<PageDto<Member>>(["members"], "/access/members?page_size=100");
  const tokens = useApiQuery<PageDto<Token>>(["tokens"], "/access/tokens?page_size=100");
  const [email, setEmail] = useState(""); const [password, setPassword] = useState(""); const [tokenName, setTokenName] = useState("");
  async function addMember() { await api.post("/access/members", { email, password, role: "workspace_operator" }); setEmail(""); setPassword(""); await members.refetch(); toast.success("Operator added; password change required at first login."); }
  async function createToken() { const result = await api.post<{ token: string }>("/access/tokens", { name: tokenName, scopes: ["read", "write"] }); setTokenName(""); await tokens.refetch(); window.prompt("Copy this token now. It will not be shown again.", result.token); }
  return <><PageHeader title="Access" description="Workspace members, roles, sessions, and scoped API credentials." /><div className="space-y-5 p-4 sm:p-6"><Card><CardHeader><CardTitle>Add operator</CardTitle></CardHeader><CardContent className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"><div><Label>Email</Label><Input value={email} onChange={(e) => setEmail(e.target.value)} /></div><div><Label>Initial password</Label><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></div><Button disabled={!email || password.length < 12} onClick={() => void addMember()}>Add member</Button></CardContent></Card><Card className="overflow-hidden">{members.isLoading ? <TableLoading /> : members.isError ? <QueryError onRetry={() => members.refetch()} /> : <Table><TableHeader><TableRow><TableHead className="pl-5">Email</TableHead><TableHead>Role</TableHead><TableHead>Status</TableHead><TableHead>Password</TableHead></TableRow></TableHeader><TableBody>{members.data?.items.map((m) => <TableRow key={m.id}><TableCell className="pl-5">{m.email}</TableCell><TableCell>{m.role.replace("workspace_", "")}</TableCell><TableCell>{m.active ? "Active" : "Disabled"}</TableCell><TableCell>{m.must_change_password ? "Change required" : "Current"}</TableCell></TableRow>)}</TableBody></Table>}</Card><Card><CardHeader><CardTitle>API tokens</CardTitle></CardHeader><CardContent className="space-y-4"><div className="flex gap-2"><Input placeholder="Token name" value={tokenName} onChange={(e) => setTokenName(e.target.value)} /><Button disabled={tokenName.length < 2} onClick={() => void createToken()}>Create token</Button></div>{tokens.isLoading ? <TableLoading /> : tokens.isError ? <QueryError onRetry={() => tokens.refetch()} /> : <Table><TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Prefix</TableHead><TableHead>Scopes</TableHead><TableHead>Last used</TableHead></TableRow></TableHeader><TableBody>{tokens.data?.items.map((t) => <TableRow key={t.id}><TableCell>{t.name}</TableCell><TableCell className="font-mono">{t.token_prefix}…</TableCell><TableCell>{t.scopes.join(", ")}</TableCell><TableCell>{t.last_used_at ?? "Never"}</TableCell></TableRow>)}</TableBody></Table>}</CardContent></Card></div></>;
}
