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

## Dedicated endpoint ports

Dedicated ports (`GATEWAY_LISTENER_PORTS`, default `10000-10019`) are opened and closed
by the gateway as endpoints are published and deleted; no restart is needed. Compose
publishes the whole range, so narrow it to what you use.

A port without credentials trusts the client address alone. Its allowlist is mandatory,
`/0` allowlists are rejected, and a gateway that somehow holds an open endpoint with an
empty allowlist rejects every client. Behind Docker's userland proxy or NAT the gateway
sees the translated source address, so allow that address (often the Docker bridge
gateway) rather than the original client when you connect from outside the container
network. Do not forward these ports to the public internet.

Deleting an endpoint closes its listening socket immediately; connections already open
finish normally, as with credential changes.

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
