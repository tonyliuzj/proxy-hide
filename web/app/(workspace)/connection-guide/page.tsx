"use client";

import Link from "next/link";
import { BookOpen, CircleAlert, ExternalLink, KeyRound, Network } from "lucide-react";
import { CopyButton } from "@/components/copy-button";
import { PageHeader } from "@/components/page-header";
import { QueryError, TableLoading } from "@/components/query-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApiQuery } from "@/lib/api/hooks";
import { useEndpoints } from "@/lib/api/resources";
import { useState } from "react";

interface ConnectionGuide {
  secure_host: string;
  secure_port: number;
  plaintext_host: string;
  plaintext_port: number;
  socks_host: string;
  socks_port: number;
}

function CodeExample({ value }: { value: string }) {
  return <div className="flex min-w-0 items-start rounded-md border bg-[#172227] pl-4 text-white"><pre className="min-w-0 flex-1 overflow-x-auto py-3 text-xs leading-5"><code>{value}</code></pre><CopyButton value={value} label="Copy example" /></div>;
}

export default function ConnectionGuidePage() {
  const endpoints = useEndpoints({ page_size: 100 });
  const guide = useApiQuery<ConnectionGuide>(["connection-guide"], "/endpoints/connection-guide");
  const [selectedId, setSelectedId] = useState("");
  const selected = endpoints.data?.items.find((endpoint) => endpoint.id === selectedId) ?? endpoints.data?.items.find((endpoint) => endpoint.enabled) ?? endpoints.data?.items[0];

  if (endpoints.isLoading || guide.isLoading) return <><PageHeader title="Connection guide" /><div className="p-6"><Card><TableLoading /></Card></div></>;
  if (endpoints.isError || guide.isError) return <><PageHeader title="Connection guide" /><div className="p-6"><Card><QueryError onRetry={() => { void endpoints.refetch(); void guide.refetch(); }} /></Card></div></>;

  const username = selected?.username ?? "YOUR_USERNAME";
  const secret = "YOUR_SECRET";
  const secureAddress = `${guide.data?.secure_host}:${guide.data?.secure_port}`;
  const plaintextAddress = `${guide.data?.plaintext_host}:${guide.data?.plaintext_port}`;
  const secureUrl = `https://${username}:${secret}@${secureAddress}`;
  const plaintextUrl = `http://${username}:${secret}@${plaintextAddress}`;
  const socksAddress = `${guide.data?.socks_host}:${guide.data?.socks_port}`;
  const socksUrl = `socks5h://${username}:${secret}@${socksAddress}`;
  const curl = `curl --proxy '${secureUrl}' 'https://api.ipify.org?format=json'`;
  const environment = `export HTTPS_PROXY='${secureUrl}'\nexport HTTP_PROXY='${secureUrl}'\ncurl 'https://api.ipify.org?format=json'`;
  const address = selected?.proxyAddress ?? "";
  const portHttpUrl = `http://${address}`;
  const portSocksUrl = `socks5h://${address}`;
  const portCurl = `curl --proxy '${portHttpUrl}' 'https://api.ipify.org?format=json'`;
  const portEnvironment = `export HTTPS_PROXY='${portHttpUrl}'\nexport HTTP_PROXY='${portHttpUrl}'\ncurl 'https://api.ipify.org?format=json'`;
  const portPython = `import requests\n\nproxy = "${portHttpUrl}"\nresponse = requests.get(\n    "https://api.ipify.org?format=json",\n    proxies={"http": proxy, "https": proxy},\n    timeout=30,\n)\nprint(response.json())`;
  const portSocks = `curl --proxy '${portSocksUrl}' 'https://api.ipify.org?format=json'`;
  const python = `import requests\n\nproxy = "${secureUrl}"\nresponse = requests.get(\n    "https://api.ipify.org?format=json",\n    proxies={"http": proxy, "https": proxy},\n    timeout=30,\n)\nprint(response.json())`;
  const git = `git config --global http.proxy '${secureUrl}'\ngit config --global https.proxy '${secureUrl}'`;
  const socks = `curl --proxy '${socksUrl}' 'https://api.ipify.org?format=json'\n\n# Python: pip install requests[socks]\nproxies = {"http": "${socksUrl}", "https": "${socksUrl}"}`;

  return <>
    <PageHeader title="Connection guide" description="Connect applications to this workspace's rotating proxy pools." actions={<Button asChild variant="outline" size="sm"><Link href="/endpoints">Manage endpoints <ExternalLink /></Link></Button>} />
    <div className="space-y-5 p-4 sm:p-6">
      {!selected ? <Card><CardContent className="flex flex-col items-center gap-3 py-10 text-center"><Network className="size-8 text-muted-foreground" /><div><p className="font-medium">Publish an endpoint first</p><p className="mt-1 text-sm text-muted-foreground">An endpoint supplies the username that connects your application to a proxy pool.</p></div><Button asChild><Link href="/endpoints">Go to endpoints</Link></Button></CardContent></Card> : <>
        <Card><CardHeader><CardTitle className="flex items-center gap-2"><BookOpen className="size-4" />Choose an endpoint</CardTitle></CardHeader><CardContent className="space-y-4"><Select value={selected.id} onValueChange={setSelectedId}><SelectTrigger className="max-w-md"><SelectValue /></SelectTrigger><SelectContent>{endpoints.data?.items.map((endpoint) => <SelectItem key={endpoint.id} value={endpoint.id}>{endpoint.name} — {endpoint.proxyAddress ?? endpoint.username}{endpoint.enabled ? "" : " (disabled)"}</SelectItem>)}</SelectContent></Select><div className="grid gap-3 sm:grid-cols-2"><div className="rounded-md border p-3"><p className="text-xs font-medium text-muted-foreground">Secure gateway</p><p className="mt-1 font-mono text-sm">{secureAddress}</p></div><div className="rounded-md border p-3"><p className="text-xs font-medium text-muted-foreground">Compatibility gateway</p><p className="mt-1 font-mono text-sm">{plaintextAddress}</p></div></div></CardContent></Card>
        {selected.proxyAddress ? <>
        <Card><CardHeader><CardTitle className="flex items-center gap-2"><Network className="size-4" />Proxy address</CardTitle></CardHeader><CardContent className="space-y-3"><p className="text-sm text-muted-foreground">This endpoint has its own port. Give apps the address below; there is no username or password. The same port accepts HTTP/CONNECT and SOCKS5.</p><CodeExample value={address} /><div className="grid gap-3 sm:grid-cols-2"><div className="rounded-md border p-3"><p className="text-xs font-medium text-muted-foreground">HTTP proxy URL</p><p className="mt-1 break-all font-mono text-sm">{portHttpUrl}</p></div><div className="rounded-md border p-3"><p className="text-xs font-medium text-muted-foreground">SOCKS5 proxy URL</p><p className="mt-1 break-all font-mono text-sm">{portSocksUrl}</p></div></div></CardContent></Card>
        <Card><CardHeader><CardTitle>Client examples</CardTitle></CardHeader><CardContent><Tabs defaultValue="curl"><TabsList><TabsTrigger value="curl">cURL</TabsTrigger><TabsTrigger value="environment">Environment</TabsTrigger><TabsTrigger value="python">Python</TabsTrigger><TabsTrigger value="socks">SOCKS5</TabsTrigger></TabsList><TabsContent value="curl"><CodeExample value={portCurl} /></TabsContent><TabsContent value="environment"><CodeExample value={portEnvironment} /></TabsContent><TabsContent value="python"><CodeExample value={portPython} /></TabsContent><TabsContent value="socks"><CodeExample value={portSocks} /></TabsContent></Tabs></CardContent></Card>
        <Card><CardHeader><CardTitle>Connection checklist</CardTitle></CardHeader><CardContent><ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground"><li>Make sure the endpoint and its pool are enabled and the pool has eligible proxies.</li><li>Connect from a machine inside the endpoint&apos;s allowed networks. Behind Docker or NAT the gateway may see a translated address, so allow that one.</li><li>Use this host and port, not the shared gateway on port {guide.data?.plaintext_port}.</li><li>Confirm the returned IP differs from your client IP, then configure the same proxy URL in your application.</li></ol></CardContent></Card>
        </> : <>
        <Card><CardHeader><CardTitle className="flex items-center gap-2"><KeyRound className="size-4" />Credentials</CardTitle></CardHeader><CardContent className="space-y-3"><p className="text-sm">Username: <code className="rounded bg-muted px-1.5 py-0.5">{username}</code>. Replace <code className="rounded bg-muted px-1.5 py-0.5">YOUR_SECRET</code> in every example with the one-time secret shown when the endpoint was created or regenerated.</p><div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><CircleAlert className="mt-0.5 size-4 shrink-0" /><p>Secrets cannot be recovered. If it was not saved, regenerate it from Endpoints. URL-encode special characters when manually building a proxy URL.</p></div></CardContent></Card>
        <Card><CardHeader><CardTitle>Client examples</CardTitle></CardHeader><CardContent><Tabs defaultValue="curl"><TabsList><TabsTrigger value="curl">cURL</TabsTrigger><TabsTrigger value="environment">Environment</TabsTrigger><TabsTrigger value="python">Python</TabsTrigger><TabsTrigger value="git">Git</TabsTrigger><TabsTrigger value="socks">SOCKS5</TabsTrigger></TabsList><TabsContent value="curl"><CodeExample value={curl} /></TabsContent><TabsContent value="environment"><CodeExample value={environment} /></TabsContent><TabsContent value="python"><CodeExample value={python} /></TabsContent><TabsContent value="git"><CodeExample value={git} /></TabsContent><TabsContent value="socks"><CodeExample value={socks} /></TabsContent></Tabs></CardContent></Card>
        <Card><CardHeader><CardTitle>Connection checklist</CardTitle></CardHeader><CardContent><ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground"><li>Make sure the endpoint and its pool are enabled and the pool has eligible proxies.</li><li>Use the endpoint username and current secret—not your workspace login password.</li><li>If an IP allowlist is configured, connect from an allowed public IP.</li><li>Prefer the secure gateway. Use <code>{plaintextUrl}</code> only on a trusted network when TLS is unavailable.</li><li>Confirm the returned IP differs from your client IP, then configure the same proxy URL in your application.</li></ol></CardContent></Card>
        </>}
      </>}
    </div>
  </>;
}
