export type HealthState = "healthy" | "degraded" | "unhealthy" | "unknown";
export type ProxyProtocol = "http" | "https" | "socks4a" | "socks5";
export type TargetAvailability = "available" | "blocked" | "rate_limited" | "unavailable" | "unknown";

export interface ListResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface WorkspaceLimits {
  max_private_proxies: number;
  max_sources: number;
  max_custom_targets: number;
  max_filters: number;
  max_pools: number;
  max_endpoints: number;
  max_concurrent_checks: number;
  max_gateway_connections: number;
  requests_per_minute: number;
  global_catalog_enabled: boolean;
  destination_ports: number[];
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  status: "active" | "suspended";
  limits: WorkspaceLimits;
}

export interface Usage {
  private_proxies: number;
  sources: number;
  custom_targets: number;
  filters: number;
  pools: number;
  endpoints: number;
}

export interface WorkspaceSettings {
  workspace: Omit<Workspace, "limits">;
  limits: WorkspaceLimits;
  usage: Usage;
}

export interface CurrentUser {
  id: string;
  email: string;
  role: "workspace_owner" | "platform_admin";
  workspace: Workspace | null;
}

export interface Metric {
  label: string;
  value: string;
  change: number;
  hint: string;
}

export interface ProxyRecord {
  id: string;
  host: string;
  port: number;
  protocol: ProxyProtocol;
  country: string;
  countryCode: string;
  city: string;
  score: number;
  latencyMs: number;
  successRate: number;
  status: HealthState;
  google: TargetAvailability;
  bing: TargetAvailability;
  sourceName: string;
  lastCheckedAt?: string;
}

export interface Source {
  id: string;
  name: string;
  url: string;
  scope: "global" | "private";
  defaultProtocol: ProxyProtocol;
  enabled: boolean;
  lastRunStatus: "queued" | "running" | "succeeded" | "failed" | "dead" | null;
  proxyCount: number | null;
  healthyCount: number | null;
  refreshIntervalMinutes: number;
  lastRunAt?: string;
}

export interface Target {
  id: string;
  name: string;
  url: string;
  kind: "google" | "bing" | "custom";
  enabled: boolean;
  method: "GET" | "HEAD" | "POST";
  statusRanges: [number, number][];
  requiredLiterals?: string[];
  forbiddenLiterals?: string[];
  availabilityRate: number | null;
  lastCheckedAt?: string;
}

export interface ProxyFilter {
  id: string;
  name: string;
  summary: string;
  countryCodes: string[];
  minimumScore: number;
  targetName?: string;
  targetAvailability?: TargetAvailability;
  matchingCount: number | null;
  updatedAt: string;
  rules?: Record<string, unknown>;
}

export type RotationStrategy = "random" | "round_robin" | "lowest_latency" | "weighted_health";

export interface Pool {
  id: string;
  name: string;
  filterName: string;
  strategy: RotationStrategy;
  enabled: boolean;
  catalogSelection: "global" | "private" | "combined";
  currentRevision: number;
  eligibleCount: number | null;
  activeConnections: number | null;
  averageLatencyMs: number | null;
  updatedAt: string;
}

export interface Endpoint {
  id: string;
  name: string;
  username: string;
  poolName: string;
  enabled: boolean;
  ipAllowlist: string[];
  requests24h: number | null;
  successRate: number | null;
  lastUsedAt?: string;
  createdAt: string;
}

export interface EndpointCredentials extends Endpoint {
  secret: string;
  plaintextUrl: string;
  secureUrl: string;
}

export interface CheckRun {
  id: string;
  proxy: string;
  checkType: "general" | "google" | "bing" | "custom";
  target: string;
  result: "passed" | "failed" | "timeout";
  latencyMs?: number;
  errorCode?: string;
  createdAt: string;
}

export interface JobRun {
  id: string;
  type: "check_proxy" | "check_target" | "refresh_source" | "materialize_pool" | "publish_snapshot" | "retention";
  status: "queued" | "running" | "succeeded" | "failed" | "dead";
  entityId?: string;
  attempt: number;
  maxAttempts: number;
  progressCurrent: number;
  progressTotal: number;
  errorCode?: string;
  createdAt: string;
  startedAt?: string;
  finishedAt?: string;
}

export interface TrafficPoint {
  bucketStart: string;
  requests: number;
  successes: number;
  failures: number;
  bytesUp: number;
  bytesDown: number;
  averageLatencyMs: number;
}

export interface TrafficBreakdown {
  id: string;
  name: string;
  requests: number;
  successes: number;
  failures: number;
  bytesUp: number;
  bytesDown: number;
  averageLatencyMs: number;
}

export interface TrafficData {
  series: TrafficPoint[];
  byEndpoint: TrafficBreakdown[];
  byPool: TrafficBreakdown[];
}

export interface TrafficSummary {
  requests: number;
  successes: number;
  failures: number;
  bytesUp: number;
  bytesDown: number;
  averageLatencyMs: number;
  points: TrafficPoint[];
}

export interface DashboardData {
  metrics: Metric[];
  traffic: TrafficPoint[];
  pools: Pool[];
  recentChecks: CheckRun[];
}

export interface DashboardSummary {
  proxiesTotal: number;
  proxiesHealthy: number;
  sourcesTotal: number;
  poolsTotal: number;
  poolsReady: number;
  endpointsTotal: number;
  activeJobs: number;
  requests24h: number;
  successfulRequests24h: number;
  recentChecks: JobRun[];
}

export interface AdminWorkspace {
  id: string;
  name: string;
  slug: string;
  ownerEmail: string;
  status: "active" | "suspended";
  proxies: number;
  requests30d: number;
  createdAt: string;
  limits: WorkspaceLimits;
}

export interface GatewayNode {
  id: string;
  region: string;
  version: string;
  status: HealthState;
  activeConnections: number;
  eventLoopLagMs: number;
  snapshotAgeSeconds: number;
  lastSeenAt: string;
}

export interface AuditEvent {
  id: string;
  workspaceName: string;
  actor: string;
  action: string;
  resource: string;
  ipAddress: string;
  createdAt: string;
}
