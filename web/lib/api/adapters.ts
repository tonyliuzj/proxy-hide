import type { DashboardSummaryDto, EndpointCreatedDto, EndpointDto, FilterDto, JobDto, PageDto, PoolDto, ProxyDto, SourceDto, TargetDto, TrafficSummaryDto, WorkspaceAdminDto, WorkspaceSettingsDto } from "@/lib/api/dto";
import type { AdminWorkspace, DashboardSummary, Endpoint, EndpointCredentials, JobRun, ListResponse, Pool, ProxyFilter, ProxyRecord, Source, Target, TrafficPoint, TrafficSummary, WorkspaceLimits, WorkspaceSettings } from "@/lib/api/types";

const countryNames = new Intl.DisplayNames(["en"], { type: "region" });

export function adaptPage<TDto, TView>(page: PageDto<TDto>, adapt: (item: TDto) => TView): ListResponse<TView> {
  return { items: page.items.map(adapt), total: page.total, page: page.page, page_size: page.page_size };
}

export function adaptProxy(dto: ProxyDto): ProxyRecord {
  const countryCode = dto.country_code ?? "--";
  return {
    id: dto.id,
    host: dto.host ?? "Managed route",
    port: dto.port ?? 0,
    protocol: dto.protocol,
    country: countryCode === "--" ? "Unknown" : countryNames.of(countryCode) ?? countryCode,
    countryCode,
    city: "",
    score: dto.score,
    latencyMs: dto.latency_ms ?? 0,
    successRate: dto.success_rate,
    status: dto.health,
    google: "unknown",
    bing: "unknown",
    sourceName: dto.scope === "global" ? "Global catalog" : "Private inventory",
    lastCheckedAt: undefined,
  };
}

export function adaptSource(dto: SourceDto): Source {
  return { id: dto.id, name: dto.name, url: dto.url, scope: "private", defaultProtocol: dto.default_protocol, enabled: dto.enabled, lastRunStatus: dto.last_run_status as Source["lastRunStatus"], proxyCount: null, healthyCount: null, refreshIntervalMinutes: dto.refresh_interval_minutes, lastRunAt: dto.last_run_at ?? undefined };
}

export function adaptTarget(dto: TargetDto): Target {
  return { id: dto.id, name: dto.name, url: dto.url ?? "Managed target", kind: dto.kind, enabled: dto.enabled, method: dto.method, statusRanges: dto.status_ranges, requiredLiterals: dto.required_literals, forbiddenLiterals: dto.forbidden_literals, availabilityRate: null };
}

function filterSummary(rules: Record<string, unknown>) {
  const predicates = collectPredicates(rules);
  const parts: string[] = [];
  const country = predicates.find((item) => item.field === "country");
  const score = predicates.find((item) => item.field === "score" && item.operator === "gte");
  const health = predicates.find((item) => item.field === "health");
  if (Array.isArray(country?.value)) parts.push(country.value.map(String).join(", "));
  if (typeof score?.value === "number") parts.push(`score >= ${score.value}`);
  if (typeof health?.value === "string") parts.push(String(health.value));
  return parts.length ? parts.join(" and ") : "Custom rule set";
}

type Predicate = { field?: string; operator?: string; value?: unknown };
function collectPredicates(payload: Record<string, unknown>): Predicate[] {
  const root = (payload.root ?? payload) as unknown;
  const values: Predicate[] = [];
  function visit(node: unknown) {
    if (!node || typeof node !== "object") return;
    const record = node as Record<string, unknown>;
    if (record.op === "predicate") values.push(record as Predicate);
    if (Array.isArray(record.rules)) record.rules.forEach(visit);
    if (record.rule) visit(record.rule);
  }
  visit(root);
  return values;
}

export function adaptFilter(dto: FilterDto): ProxyFilter {
  const predicates = collectPredicates(dto.rules);
  const countries = predicates.find((item) => item.field === "country")?.value;
  const score = predicates.find((item) => item.field === "score" && item.operator === "gte")?.value;
  return { id: dto.id, name: dto.name, summary: filterSummary(dto.rules), countryCodes: Array.isArray(countries) ? countries.map(String) : [], minimumScore: typeof score === "number" ? score : 0, matchingCount: null, updatedAt: dto.updated_at, rules: dto.rules };
}

export function adaptPool(dto: PoolDto): Pool {
  return { id: dto.id, name: dto.name, filterName: dto.filter_id, strategy: dto.strategy, enabled: dto.enabled, catalogSelection: dto.catalog_selection, currentRevision: dto.current_revision ?? 0, eligibleCount: null, activeConnections: null, averageLatencyMs: null, updatedAt: dto.materialized_at ?? dto.created_at };
}

export function adaptEndpoint(dto: EndpointDto): Endpoint {
  return { id: dto.id, name: dto.name, username: dto.username, poolName: dto.pool_id, enabled: dto.enabled, ipAllowlist: dto.ip_allowlist, requests24h: null, successRate: null, createdAt: dto.created_at, lastUsedAt: dto.secret_rotated_at ?? undefined };
}

export function adaptEndpointCredentials(dto: EndpointCreatedDto): EndpointCredentials {
  return {
    ...adaptEndpoint(dto),
    secret: dto.secret,
    plaintextUrl: dto.plaintext_url,
    secureUrl: dto.secure_url,
  };
}

export function adaptTraffic(dto: TrafficSummaryDto): TrafficPoint[] {
  return dto.points.map((point) => ({ bucketStart: point.bucket_start, requests: point.requests, successes: point.successes, failures: point.failures, bytesUp: point.bytes_up, bytesDown: point.bytes_down, averageLatencyMs: point.average_latency_ms ?? 0 }));
}

export function adaptTrafficSummary(dto: TrafficSummaryDto): TrafficSummary {
  return {
    requests: dto.requests,
    successes: dto.successes,
    failures: dto.failures,
    bytesUp: dto.bytes_up,
    bytesDown: dto.bytes_down,
    averageLatencyMs: dto.average_latency_ms ?? 0,
    points: adaptTraffic(dto),
  };
}

export function adaptJob(dto: JobDto): JobRun {
  const errorCode = dto.error && typeof dto.error.code === "string" ? dto.error.code : undefined;
  return { id: dto.id, type: dto.type, status: dto.status, entityId: dto.entity_id ?? undefined, attempt: dto.attempt, maxAttempts: dto.max_attempts, progressCurrent: dto.progress_current, progressTotal: dto.progress_total, errorCode, createdAt: dto.created_at, startedAt: dto.started_at ?? undefined, finishedAt: dto.finished_at ?? undefined };
}

export function adaptDashboardSummary(dto: DashboardSummaryDto): DashboardSummary {
  return {
    proxiesTotal: dto.proxies_total,
    proxiesHealthy: dto.proxies_healthy,
    sourcesTotal: dto.sources_total,
    poolsTotal: dto.pools_total,
    poolsReady: dto.pools_ready,
    endpointsTotal: dto.endpoints_total,
    activeJobs: dto.active_jobs,
    requests24h: dto.requests_24h,
    successfulRequests24h: dto.successful_requests_24h,
    recentChecks: dto.recent_checks.map(adaptJob),
  };
}

function adaptLimits(dto: WorkspaceAdminDto["limits"]): WorkspaceLimits {
  return {
    max_private_proxies: dto.max_private_proxies,
    max_sources: dto.max_sources,
    max_custom_targets: dto.max_custom_targets,
    max_filters: dto.max_filters,
    max_pools: dto.max_pools,
    max_endpoints: dto.max_endpoints,
    max_concurrent_checks: dto.max_concurrent_checks,
    max_gateway_connections: dto.max_gateway_connections,
    requests_per_minute: dto.requests_per_minute,
    global_catalog_enabled: dto.global_catalog_enabled,
    destination_ports: dto.destination_ports,
  };
}

export function adaptWorkspaceSettings(dto: WorkspaceSettingsDto): WorkspaceSettings {
  return {
    workspace: dto.workspace,
    limits: adaptLimits(dto.limits),
    usage: dto.usage,
  };
}

export function adaptAdminWorkspace(dto: WorkspaceAdminDto): AdminWorkspace {
  return { id: dto.id, name: dto.name, slug: dto.slug, ownerEmail: dto.owner.email, status: dto.status, proxies: 0, requests30d: 0, createdAt: dto.created_at, limits: adaptLimits(dto.limits) };
}
