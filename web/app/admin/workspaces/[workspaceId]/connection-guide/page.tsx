"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, CircleAlert, KeyRound } from "lucide-react";
import { useState } from "react";
import { CopyButton } from "@/components/copy-button";
import { PageHeader } from "@/components/page-header";
import { QueryError, TableLoading } from "@/components/query-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { EndpointDto } from "@/lib/api/dto";
import { useApiQuery } from "@/lib/api/hooks";

interface AdminGuide {
  workspace_name: string;
  secure_host: string;
  secure_port: number;
  plaintext_host: string;
  plaintext_port: number;
  endpoints: EndpointDto[];
}

function Example({ value }: { value: string }) {
  return <div className="flex min-w-0 items-start rounded-md border bg-[#172227] pl-4 text-white"><pre className="min-w-0 flex-1 overflow-x-auto py-3 text-xs leading-5"><code>{value}</code></pre><CopyButton value={value} label="Copy example" /></div>;
}

export default function AdminWorkspaceConnectionGuidePage() {
  const workspaceId = String(useParams<{ workspaceId: string }>().workspaceId);
  const guide = useApiQuery<AdminGuide>(["admin", "workspaces", workspaceId, "connection-guide"], `/admin/workspaces/${workspaceId}/connection-guide`);
  const [selectedId, setSelectedId] = useState("");
  if (guide.isLoading) return <><PageHeader title="Connection guide" /><div className="p-6"><Card><TableLoading /></Card></div></>;
  if (guide.isError || !guide.data) return <><PageHeader title="Connection guide" /><div className="p-6"><Card><QueryError onRetry={() => guide.refetch()} /></Card></div></>;
  const selected = guide.data.endpoints.find((endpoint) => endpoint.id === selectedId) ?? guide.data.endpoints.find((endpoint) => endpoint.enabled) ?? guide.data.endpoints[0];
  const username = selected?.username ?? "YOUR_USERNAME";
  const secureUrl = `https://${username}:YOUR_SECRET@${guide.data.secure_host}:${guide.data.secure_port}`;
  const plaintextUrl = `http://${username}:YOUR_SECRET@${guide.data.plaintext_host}:${guide.data.plaintext_port}`;
  const curl = `curl --proxy '${secureUrl}' 'https://api.ipify.org?format=json'`;
  const environment = `export HTTPS_PROXY='${secureUrl}'\nexport HTTP_PROXY='${secureUrl}'\ncurl 'https://api.ipify.org?format=json'`;
  const python = `import requests\n\nproxy = "${secureUrl}"\nresponse = requests.get("https://api.ipify.org?format=json", proxies={"http": proxy, "https": proxy}, timeout=30)\nprint(response.json())`;

  return <><PageHeader title={`${guide.data.workspace_name} connection guide`} description="Instructions the workspace user can follow to connect to its proxy pools." actions={<Button asChild variant="outline" size="sm"><Link href={`/admin/workspaces/${workspaceId}`}><ArrowLeft />Workspace</Link></Button>} /><div className="space-y-5 p-4 sm:p-6">
    <Card><CardHeader><CardTitle>Workspace endpoint</CardTitle></CardHeader><CardContent className="space-y-4">{selected ? <><Select value={selected.id} onValueChange={setSelectedId}><SelectTrigger className="max-w-md"><SelectValue /></SelectTrigger><SelectContent>{guide.data.endpoints.map((endpoint) => <SelectItem key={endpoint.id} value={endpoint.id}>{endpoint.name} — {endpoint.username}{endpoint.enabled ? "" : " (disabled)"}</SelectItem>)}</SelectContent></Select><div className="grid gap-3 sm:grid-cols-2"><div className="rounded-md border p-3"><p className="text-xs text-muted-foreground">Secure gateway</p><p className="mt-1 font-mono text-sm">{guide.data.secure_host}:{guide.data.secure_port}</p></div><div className="rounded-md border p-3"><p className="text-xs text-muted-foreground">Compatibility gateway</p><p className="mt-1 font-mono text-sm">{guide.data.plaintext_host}:{guide.data.plaintext_port}</p></div></div></> : <div className="text-sm text-muted-foreground">This workspace has no endpoint yet. The workspace owner must publish one from its Endpoints page.</div>}</CardContent></Card>
    {selected ? <><Card><CardHeader><CardTitle className="flex items-center gap-2"><KeyRound className="size-4" />Credentials</CardTitle></CardHeader><CardContent className="space-y-3"><p className="text-sm">Use username <code className="rounded bg-muted px-1.5 py-0.5">{username}</code> and replace <code className="rounded bg-muted px-1.5 py-0.5">YOUR_SECRET</code> with the endpoint secret.</p><div className="flex gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><CircleAlert className="mt-0.5 size-4 shrink-0" />The secret is shown only when created or regenerated. It cannot be viewed by the platform administrator.</div></CardContent></Card><Card><CardHeader><CardTitle>Copyable examples</CardTitle></CardHeader><CardContent><Tabs defaultValue="curl"><TabsList><TabsTrigger value="curl">cURL</TabsTrigger><TabsTrigger value="environment">Environment</TabsTrigger><TabsTrigger value="python">Python</TabsTrigger></TabsList><TabsContent value="curl"><Example value={curl} /></TabsContent><TabsContent value="environment"><Example value={environment} /></TabsContent><TabsContent value="python"><Example value={python} /></TabsContent></Tabs></CardContent></Card><Card><CardHeader><CardTitle>Compatibility listener</CardTitle></CardHeader><CardContent><p className="mb-3 text-sm text-muted-foreground">Use only on a trusted network when the secure listener is unavailable.</p><Example value={plaintextUrl} /></CardContent></Card></> : null}
  </div></>;
}
