import type { HealthState, ProxyProtocol, RotationStrategy, TargetAvailability } from "@/lib/api/types";

export interface PageDto<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface WorkspaceSummaryDto {
  id: string;
  name: string;
  slug: string;
  status: "active" | "suspended";
}

export interface WorkspaceLimitsDto {
  workspace_id: string;
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

export interface UserDto {
  id: string;
  email: string;
  role: "workspace_owner" | "workspace_operator" | "workspace_viewer" | "platform_admin";
  workspace_id: string | null;
  active: boolean;
  must_change_password: boolean;
}

export interface SessionDto {
  user: UserDto;
  workspace: WorkspaceSummaryDto | null;
  csrf_token: string;
  must_change_password: boolean;
}

export interface SetupStatusDto {
  setup_required: boolean;
}

export interface WorkspaceAdminDto extends WorkspaceSummaryDto {
  owner: UserDto;
  limits: WorkspaceLimitsDto;
  created_at: string;
}

export interface ProxyDto {
  id: string;
  scope: "global" | "private";
  protocol: ProxyProtocol;
  host: string | null;
  port: number | null;
  credentials: string | null;
  country_code: string | null;
  asn: number | null;
  active: boolean;
  health: HealthState;
  score: number;
  latency_ms: number | null;
  success_rate: number;
}

export interface ProxyImportPreviewDto {
  valid: { protocol: ProxyProtocol; host: string; port: number; username: string | null; identity_hash: string }[];
  invalid: { line: number; value: string; error: string }[];
  duplicate_lines: number[];
  valid_count: number;
  invalid_count: number;
  duplicate_count: number;
}

export interface ProxyImportResultDto {
  imported: number;
  duplicates: number;
  invalid: number;
  operation_id: string;
}

export interface SourceDto {
  id: string;
  name: string;
  url: string;
  default_protocol: ProxyProtocol;
  enabled: boolean;
  refresh_interval_minutes: number;
  has_credentials: boolean;
  last_run_at: string | null;
  last_run_status: string | null;
  created_at: string;
}

export interface TargetDto {
  id: string;
  name: string;
  kind: "google" | "bing" | "brave" | "startpage" | "duckduckgo" | "wikipedia" | "custom";
  enabled: boolean;
  method: "GET" | "HEAD" | "POST";
  url: string | null;
  headers: Record<string, string>;
  has_secret_headers: boolean;
  has_body: boolean;
  status_ranges: [number, number][];
  required_literals: string[];
  forbidden_literals: string[];
  required_patterns: string[];
  forbidden_patterns: string[];
  created_at: string;
}

export interface FilterDto {
  id: string;
  name: string;
  version: number;
  rules: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface PoolDto {
  id: string;
  name: string;
  filter_id: string;
  catalog_selection: "global" | "private" | "combined";
  strategy: RotationStrategy;
  enabled: boolean;
  current_revision: number | null;
  materialized_at: string | null;
  created_at: string;
}

export interface EndpointDto {
  id: string;
  name: string;
  pool_id: string;
  username: string;
  enabled: boolean;
  ip_allowlist: string[];
  listen_port: number | null;
  proxy_address: string | null;
  require_auth: boolean;
  strategy: RotationStrategy | null;
  secret_rotated_at: string | null;
  created_at: string;
}

export interface EndpointCreatedDto extends EndpointDto {
  secret: string | null;
  plaintext_url: string | null;
  secure_url: string | null;
}

export interface JobDto {
  id: string;
  type: "check_proxy" | "check_target" | "refresh_source" | "materialize_pool" | "publish_snapshot" | "retention";
  status: "queued" | "running" | "succeeded" | "failed" | "dead";
  entity_id: string | null;
  attempt: number;
  max_attempts: number;
  progress_current: number;
  progress_total: number;
  error: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface AdminQueuedJobDto extends JobDto {
  workspace_id: string | null;
}

export interface AdminQueueStatisticsDto {
  queued: number;
  running: number;
  total: number;
  items: AdminQueuedJobDto[];
}

export interface TrafficPointDto {
  bucket_start: string;
  requests: number;
  successes: number;
  failures: number;
  bytes_up: number;
  bytes_down: number;
  average_latency_ms: number | null;
}

export interface TrafficSummaryDto {
  requests: number;
  successes: number;
  failures: number;
  bytes_up: number;
  bytes_down: number;
  average_latency_ms: number | null;
  points: TrafficPointDto[];
}

export interface DashboardSummaryDto {
  proxies_total: number;
  proxies_healthy: number;
  sources_total: number;
  pools_total: number;
  pools_ready: number;
  endpoints_total: number;
  active_jobs: number;
  requests_24h: number;
  successful_requests_24h: number;
  recent_checks: JobDto[];
}

export interface UsageDto {
  private_proxies: number;
  sources: number;
  custom_targets: number;
  filters: number;
  pools: number;
  endpoints: number;
}

export interface WorkspaceSettingsDto {
  workspace: WorkspaceSummaryDto;
  limits: WorkspaceLimitsDto;
  usage: UsageDto;
}

export interface TargetAvailabilityDto {
  target_id: string;
  availability: TargetAvailability;
  checked_at: string;
}

export interface AuditEventDto {
  id: string;
  actor_user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  ip_address: string | null;
  details: Record<string, unknown>;
  created_at: string;
}
