# Operations

## External routing

Proxy Hide intentionally does not bundle a reverse proxy or certificate
automation. Route the application origin to `web:3000`; Next.js forwards
`/api/v1` to `backend:8000`. A production HTTP proxy URL uses TLS on port 443 at
an external L4 terminator and forwards the decrypted HTTP proxy protocol to
`backend:9000`. The direct port 9000 listener is compatibility-only.

Only accept PROXY protocol metadata from the configured terminator CIDRs.
Untrusted connections are interpreted as ordinary HTTP proxy traffic and may
not override their source address with forwarded headers.

## Runtime layout

The standard Compose deployment runs exactly four persistent containers:
`web`, `backend`, `postgres`, and `redis`. The backend container runs the API,
scheduler, Redis Stream worker, and proxy gateway as separate child processes.
It applies Alembic migrations before starting any of them and exits if a
required process stops, allowing Compose to restart the complete backend as one
unit.

This consolidated layout is the supported self-hosted default. It deliberately
trades independent process scaling for fewer containers and simpler upgrades.

## First-run ownership

When the user table is empty, the web origin opens a one-time administrator
setup page. Complete this before exposing the installation to an untrusted
network: the first successful submission becomes the platform administrator.
The database serializes concurrent attempts, and setup closes as soon as any
user exists. Later administrator password recovery remains available through
the host-only `make admin` command.

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
continuity but is not a substitute for the database backup. Deploy the new
`backend` and `web` images together. The backend applies pending migrations
before it starts its API, scheduler, worker, or gateway processes; if migration
fails, the backend remains unavailable. Never run multiple incompatible schema
versions concurrently.
