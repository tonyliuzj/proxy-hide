import { describe, expect, it } from "vitest";
import { adaptDashboardSummary, adaptEndpointCredentials, adaptProxy, adaptTrafficSummary } from "@/lib/api/adapters";

describe("API adapters", () => {
  it("keeps global proxy addresses masked", () => {
    const proxy = adaptProxy({ id: "p1", scope: "global", protocol: "http", host: null, port: null, credentials: null, country_code: "GB", asn: 64500, active: true, health: "healthy", score: 92, latency_ms: 180, success_rate: 99 });
    expect(proxy.host).toBe("Managed route");
    expect(proxy.port).toBe(0);
    expect(proxy.sourceName).toBe("Global catalog");
  });

  it("maps one-time endpoint URLs without deriving them in the client", () => {
    const endpoint = adaptEndpointCredentials({ id: "e1", name: "UK", pool_id: "pool1", username: "google-uk", enabled: true, ip_allowlist: [], secret_rotated_at: null, created_at: "2026-08-21T00:00:00Z", secret: "secret", plaintext_url: "http://provided", secure_url: "https://provided" });
    expect(endpoint.secret).toBe("secret");
    expect(endpoint.plaintextUrl).toBe("http://provided");
    expect(endpoint.secureUrl).toBe("https://provided");
  });

  it("maps dashboard jobs and traffic aggregates", () => {
    const summary = adaptDashboardSummary({ proxies_total: 10, proxies_healthy: 8, sources_total: 2, pools_total: 1, pools_ready: 1, endpoints_total: 1, active_jobs: 1, requests_24h: 100, successful_requests_24h: 98, recent_checks: [{ id: "j1", type: "check_proxy", status: "queued", entity_id: null, attempt: 0, max_attempts: 5, progress_current: 0, progress_total: 0, error: null, created_at: "2026-08-21T00:00:00Z", started_at: null, finished_at: null }] });
    const traffic = adaptTrafficSummary({ requests: 5, successes: 4, failures: 1, bytes_up: 10, bytes_down: 20, average_latency_ms: null, points: [] });
    expect(summary.recentChecks[0]?.type).toBe("check_proxy");
    expect(traffic.averageLatencyMs).toBe(0);
    expect(traffic.bytesDown).toBe(20);
  });
});
