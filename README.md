# Proxy Hide

Proxy Hide is a multi-tenant, self-hosted proxy inventory, checking, filtering,
pooling, and rotation platform. Operators maintain a shared masked catalog while
workspace owners can combine it with private upstreams and publish authenticated
HTTP proxy endpoints.

## Containers

The default deployment has four long-running containers. The control-plane and
data-plane processes share one backend container to keep a small self-hosted
installation easy to operate.

| Container | Purpose | Default port |
| --- | --- | --- |
| `web` | Next.js operations console | `3000` |
| `backend` | FastAPI, scheduler, job worker, and explicit HTTP/CONNECT gateway | `8000`, `9000` |
| `postgres` | Authoritative state | internal |
| `redis` | Sessions, streams, and pool notifications | internal |

On startup, `backend` applies pending database migrations and then launches the
API, scheduler, worker, and gateway as separate Python processes. If migration
fails or a required process exits, the container fails instead of running a
partial platform.

## Start locally

1. Copy `.env.example` to `.env` and replace all three development secrets.
2. Run `make up`. This builds and starts the four containers in the background.
3. Open <http://localhost:3000> and create the first platform administrator.

Until the first account exists, `/` and `/login` open the one-time setup page.
After setup, that page closes and the normal sign-in screen is used. `make admin`
remains available to replace an administrator password from the host.

Use `make logs` to follow the combined backend and web logs, and `make down` to
stop the installation.

## Endpoints: how other apps connect

An endpoint maps a way of connecting to a pool, and the pool's filter decides which
tested proxies can be used. There are two kinds:

- **Dedicated `ip:port`** (default for new endpoints in the console). The endpoint gets
  its own port from `GATEWAY_LISTENER_PORTS`, and clients just use `host:port` as an
  HTTP, HTTPS-via-CONNECT, or SOCKS5 proxy with no username or password. Because there
  are no credentials, the endpoint must have a client IP allowlist, and one that allows
  every address (`0.0.0.0/0`) is refused. Use your LAN or Docker network range, for
  example `192.168.0.0/16`.
- **Credentials** on the shared ports (`9000` HTTP, `1080` SOCKS5). A username and
  one-time secret select the endpoint. This is also available on a dedicated port.

Rotation is chosen per endpoint, or inherited from the pool:

| Mode | Behavior |
| --- | --- |
| By list (`round_robin`) | Next proxy in list order on every connection, skipping failed ones |
| Random (`random`) | A random healthy proxy per connection |
| Fastest (`lowest_latency`) | The lowest-latency healthy proxy, falling back down the list |
| Best quality (`weighted_health`) | Random, weighted towards higher health scores |
| No rotation (`sticky`) | Stay on one proxy until it fails, then move to the next and stay there |

Within one connection the gateway tries up to three proxies before giving up, in every mode.

## Share a list link

For apps that want a list of proxies rather than one address, open a pool's menu in the
console and choose **Share list link**. It creates a secret, revocable URL like
`https://your-host/api/v1/lists/ph_list_...` that serves the pool's current members, so the
list stays fresh as proxies are checked and replaced.

| Query | Result |
| --- | --- |
| *(none)* | One `scheme://[user:pass@]host:port` per line |
| `?format=hostport` | Plain `host:port` lines |
| `?format=json` | Objects with host, port, credentials, country, latency and score |
| `&protocol=http` | Only that type: `http`, `https`, `socks4a`, or `socks5` |

The full URL is shown once and only a hash of the token is stored, so revoke and create
a new link if it is lost. Anyone holding the URL can read the list, including upstream
passwords, and the token appears in access logs of anything in front of the API.

By default a link serves only the proxies your own workspace added. Global-catalog
addresses are masked everywhere else in the app, so including them is a per-link opt-in
that also requires the workspace's global catalog grant. The response header
`X-Excluded-Global-Count` reports how many members were left out, which explains an
unexpectedly short list. Set `PUBLIC_LIST_BASE_URL` if the API is served from a different
origin than `WEB_ORIGIN`.

## Docker Hub images

Only two project images are needed. Both are published in the private
`tonyliuzj/proxy-hide` Docker Hub repository, using the `backend` and `web`
tags. PostgreSQL and Redis use their official images.

The `docker` GitHub Actions workflow builds both images for `linux/amd64` and
`linux/arm64` and pushes them with the `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`
repository secrets (the token needs Read & Write access, and the Docker Hub repository
should already exist and be private). Each component gets a moving tag from `main`
(`backend`, `web`), an immutable `backend-<short sha>` / `web-<short sha>` tag per
commit, and `backend-1.2.3` / `web-1.2.3` when a `v1.2.3` tag is pushed. Pull requests
only check that the images build. Pin a deployment to a commit or version tag instead of
the moving tag when you need to roll back.

`make up` builds the project images from the checked-out source. To deploy the
published images instead, authenticate to Docker Hub and start Compose without
building:

```console
docker login
docker compose pull
docker compose up -d --no-build
```

The backend image includes the API, scheduler, worker, gateway, and migrations;
there are no separate project images for those internal processes.

The web console is served over plaintext only for local development. In
production, place the web/API origin behind HTTPS. Publish a TLS-wrapped HTTP
proxy listener on port 443 through an external L4 terminator and forward it to
the backend on port 9000. Configure its CIDR in `TRUSTED_PROXY_CIDRS` before
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
