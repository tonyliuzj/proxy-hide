# Proxy Hide

Proxy Hide is a multi-tenant, self-hosted proxy inventory, checking, filtering,
pooling, and rotation platform. Operators maintain a shared masked catalog while
workspace owners can combine it with private upstreams and publish authenticated
HTTP proxy endpoints.

## Services

| Service | Purpose | Default port |
| --- | --- | --- |
| `web` | Next.js operations console | `3000` |
| `api` | FastAPI control plane and probe endpoint | `8000` |
| `gateway` | Explicit HTTP/CONNECT proxy | `9000` |
| `scheduler` | Durable source/check scheduling | none |
| `worker` | Redis Stream jobs and pool materialization | none |
| `postgres` | Authoritative state | internal |
| `redis` | Sessions, streams, and pool notifications | internal |

## Start locally

1. Copy `.env.example` to `.env` and replace all three development secrets.
2. Run `make bootstrap`.
3. Create the first operator with `make admin`.
4. Run `make up` and open <http://localhost:3000>.

The web console is served over plaintext only for local development. In
production, place the web/API origin behind HTTPS. Publish a TLS-wrapped HTTP
proxy listener on port 443 through an external L4 terminator and forward it to
the gateway on port 9000. Configure its CIDR in `TRUSTED_PROXY_CIDRS` before
accepting PROXY v2 metadata.

Port 9000 remains an optional plaintext compatibility listener. Basic proxy
credentials are not encrypted on that hop, even when the client uses CONNECT.

## Security invariants

- A destination connection can be created only by an upstream connector.
- Empty, stale, suspended, or failed pools return an error and never use the
  host's direct connection.
- Destination and source hostnames are resolved, validated, and pinned before
  use; private, metadata, loopback, and reserved networks are rejected.
- Endpoint secrets are displayed only at creation or regeneration. Upstream
  credentials are encrypted at rest and are never emitted in logs or APIs.
- Customer requests never provide a workspace identifier; it is derived from
  the opaque authenticated session.

## Production inputs

- Mount a MaxMind-compatible database under `./geoip/` and set
  `GEOIP_DATABASE_PATH` to enable exit-IP country and ASN enrichment. Fields
  that are absent from the selected database remain unknown.
- Configure `PROBE_URL` as a publicly reachable controlled echo endpoint. The
  endpoint must return the supplied nonce and the real connecting proxy IP.
- Store encryption keys outside the repository and back up PostgreSQL and Redis
  volumes according to the required recovery point.

See `docs/operations.md` for deployment boundaries and failure behavior.

## Development checks

Run backend tests with `backend/.venv/bin/pytest backend` and frontend checks
from `web/` with `npm run lint`, `npm run typecheck`, `npm test`, and
`npm run build`.

The generated frontend API contract lives at
`web/lib/api/openapi.generated.ts`. With FastAPI listening on
`http://127.0.0.1:8000`, refresh it with `npm --prefix web run openapi:types`
or verify drift with `npm --prefix web run openapi:check`.
