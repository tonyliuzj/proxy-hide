import type { WorkspaceLimits } from "@/lib/api/types";

export const DEFAULT_WORKSPACE_LIMITS: WorkspaceLimits = {
  max_private_proxies: 10_000,
  max_sources: 20,
  max_custom_targets: 10,
  max_filters: 20,
  max_pools: 10,
  max_endpoints: 10,
  max_concurrent_checks: 100,
  max_gateway_connections: 100,
  requests_per_minute: 600,
  global_catalog_enabled: true,
  destination_ports: [80, 443],
};
