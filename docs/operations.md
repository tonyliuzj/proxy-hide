# Operations

## External routing

Proxy Hide intentionally does not bundle a reverse proxy or certificate
automation. Route the application origin to `web:3000`; Next.js forwards
`/api/v1` to `api:8000`. A production HTTP proxy URL uses TLS on port 443 at an
external L4 terminator and forwards the decrypted HTTP proxy protocol to
`gateway:9000`. The direct port 9000 listener is compatibility-only.

Only accept PROXY protocol metadata from the configured terminator CIDRs.
Untrusted connections are interpreted as ordinary HTTP proxy traffic and may
not override their source address with forwarded headers.

## Failure behavior

- PostgreSQL is the authoritative source for workspaces, endpoint credentials,
  health, operations, and immutable pool revisions.
- Redis delivers jobs and revision notifications. A gateway with a previously
  loaded snapshot can serve it for 60 seconds during Redis loss, then returns
  `503`. A gateway without an initial snapshot is not ready.
- Upstream selection tries no more than three distinct routes within a 12-second
  setup budget. It never retries after request or tunnel bytes are exposed.
- Existing tunnels are not force-closed by a Redis outage or credential change;
  they end after five idle minutes or one hour total.

## Retention

Scheduled maintenance keeps check attempts for 30 days, source runs for 90
days, minute traffic for 7 days, hourly traffic for 13 months, recent pool
revisions for 7 days or 10 revisions, and audit events for one year. Traffic
rollups never contain request bodies, authorization headers, or destination
URLs.

## Backup and upgrades

Back up PostgreSQL before upgrading. Redis AOF is useful for operational
continuity but is not a substitute for the database backup. Deploy new images,
run `alembic upgrade head` once, and then restart API, scheduler, workers, and
gateway. Never run multiple incompatible schema versions concurrently.
