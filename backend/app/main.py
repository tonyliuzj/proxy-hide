from __future__ import annotations

import ipaddress
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.api import (
    admin,
    audit,
    auth,
    checks,
    endpoints,
    filters,
    inventory,
    operations,
    pools,
    sources,
    targets,
    traffic,
)
from app.api.dashboard import dashboard_router, settings_router
from app.config import get_settings
from app.db import SessionLocal, dispose_engine
from app.errors import install_exception_handlers
from app.middleware import CSRFMiddleware, RequestContextMiddleware
from app.sessions import SessionStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    app.state.redis = redis
    app.state.session_store = SessionStore(redis, settings)
    yield
    await redis.aclose()
    await dispose_engine()


settings = get_settings()
app = FastAPI(
    title="Proxy Hide API",
    version="0.1.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs" if settings.environment != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
)
app.add_middleware(CSRFMiddleware)
app.add_middleware(RequestContextMiddleware)
install_exception_handlers(app)

api = APIRouter(prefix="/api/v1")
api.include_router(auth.router)
api.include_router(admin.router)
api.include_router(inventory.admin_router)
api.include_router(sources.admin_router)
api.include_router(inventory.router)
api.include_router(sources.router)
api.include_router(targets.router)
api.include_router(filters.router)
api.include_router(pools.router)
api.include_router(endpoints.router)
api.include_router(checks.router)
api.include_router(traffic.router)
api.include_router(audit.router)
api.include_router(operations.router)
api.include_router(dashboard_router)
api.include_router(settings_router)
app.include_router(api)


@app.get("/health/live", include_in_schema=False)
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def ready(request: Request) -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "unavailable"
    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
    healthy = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "unavailable", "checks": checks},
    )


@app.get("/probe/v1/echo", include_in_schema=False)
async def probe_echo(
    request: Request,
    nonce: str = Query(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
) -> JSONResponse:
    immediate_peer = request.client.host if request.client else "unknown"
    client_ip = immediate_peer
    try:
        peer_address = ipaddress.ip_address(immediate_peer)
        trusted = any(
            peer_address in ipaddress.ip_network(cidr, strict=False)
            for cidr in settings.trusted_api_proxy_cidrs
        )
        if trusted:
            forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
            if forwarded:
                client_ip = ipaddress.ip_address(forwarded).compressed
    except ValueError:
        client_ip = immediate_peer
    bucket = int(time.time() // 60)
    rate_key = f"proxyhide:probe-rate:{client_ip}:{bucket}"
    count = await request.app.state.redis.incr(rate_key)
    if count == 1:
        await request.app.state.redis.expire(rate_key, 61)
    if count > settings.probe_requests_per_minute:
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limit_exceeded"},
            headers={"Retry-After": "60", "Cache-Control": "no-store"},
        )
    response = JSONResponse({"nonce": nonce, "ip": client_ip})
    response.headers["Cache-Control"] = "no-store"
    return response
