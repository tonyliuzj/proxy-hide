from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class ProxyProtocol(StrEnum):
    HTTP = "http"
    HTTPS = "https"
    SOCKS4A = "socks4a"
    SOCKS5 = "socks5"


class PoolStrategy(StrEnum):
    RANDOM = "random"
    ROUND_ROBIN = "round_robin"
    LOWEST_LATENCY = "lowest_latency"
    WEIGHTED_HEALTH = "weighted_health"


def _secret(value: object) -> str | None:
    if value is None:
        return None
    result = str(value)
    return result if result else None


@dataclass(frozen=True, slots=True)
class UpstreamRoute:
    id: str
    protocol: ProxyProtocol
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    score: float = 0.0
    latency_ms: float | None = None
    tls_server_name: str | None = None
    resolved_ips: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> UpstreamRoute:
        protocol = ProxyProtocol(str(data.get("protocol", "http")).lower())
        port = int(data["port"])
        if not 1 <= port <= 65535:
            raise ValueError("upstream port is outside 1..65535")
        host = str(data["host"]).strip().rstrip(".")
        if not host:
            raise ValueError("upstream host is required")
        resolved = tuple(str(item) for item in data.get("resolved_ips", ()) if item)
        return cls(
            id=str(data["id"]),
            protocol=protocol,
            host=host,
            port=port,
            username=_secret(data.get("username")),
            password=_secret(data.get("password")),
            score=max(0.0, min(100.0, float(data.get("score", 0.0)))),
            latency_ms=(
                max(0.0, float(data["latency_ms"])) if data.get("latency_ms") is not None else None
            ),
            tls_server_name=_secret(data.get("tls_server_name")),
            resolved_ips=resolved,
        )

    def public_dict(self) -> dict[str, Any]:
        """A deliberately redacted representation suitable for logs."""
        return {
            "id": self.id,
            "protocol": self.protocol.value,
            "host": "[redacted]",
            "port": self.port,
            "score": self.score,
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True, slots=True)
class PoolSnapshot:
    id: str
    revision: int
    strategy: PoolStrategy
    routes: tuple[UpstreamRoute, ...]

    @classmethod
    def from_dict(cls, pool_id: str, data: Mapping[str, Any]) -> PoolSnapshot:
        return cls(
            id=str(data.get("id", pool_id)),
            revision=int(data.get("revision", 0)),
            strategy=PoolStrategy(str(data.get("strategy", "random"))),
            routes=tuple(UpstreamRoute.from_dict(route) for route in data.get("routes", ())),
        )


@dataclass(frozen=True, slots=True)
class EndpointSnapshot:
    id: str
    workspace_id: str
    username: str
    secret_digest: str
    pool_id: str
    enabled: bool = True
    workspace_enabled: bool = True
    ip_allowlist: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()
    destination_ports: frozenset[int] = frozenset({80, 443})
    requests_per_minute: int = 600
    max_connections: int = 100

    @classmethod
    def from_dict(cls, username: str, data: Mapping[str, Any]) -> EndpointSnapshot:
        networks = tuple(
            ipaddress.ip_network(str(item), strict=False) for item in data.get("ip_allowlist", ())
        )
        ports = frozenset(int(item) for item in data.get("destination_ports", (80, 443)))
        return cls(
            id=str(data["id"]),
            workspace_id=str(data["workspace_id"]),
            username=str(data.get("username", username)),
            secret_digest=str(data["secret_digest"]).lower(),
            pool_id=str(data["pool_id"]),
            enabled=bool(data.get("enabled", True)),
            workspace_enabled=bool(
                data.get("workspace_enabled", data.get("workspace_status", "active") == "active")
            ),
            ip_allowlist=networks,
            destination_ports=ports,
            requests_per_minute=max(1, int(data.get("requests_per_minute", 600))),
            max_connections=max(
                1,
                int(data.get("max_connections", data.get("max_gateway_connections", 100))),
            ),
        )

    def allows_ip(self, value: str) -> bool:
        if not self.ip_allowlist:
            return True
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return False
        return any(address in network for network in self.ip_allowlist)


@dataclass(frozen=True, slots=True)
class GatewaySnapshot:
    version: int
    generated_at: datetime
    endpoints: Mapping[str, EndpointSnapshot]
    pools: Mapping[str, PoolSnapshot]
    loaded_monotonic: float = field(default=0.0, compare=False)

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], *, loaded_monotonic: float = 0.0
    ) -> GatewaySnapshot:
        generated = data.get("generated_at")
        if isinstance(generated, datetime):
            generated_at = generated
        elif generated:
            generated_at = datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
        else:
            generated_at = datetime.now(UTC)
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=UTC)

        raw_pools = data.get("pools", {})
        pools = {
            str(key): PoolSnapshot.from_dict(str(key), value) for key, value in raw_pools.items()
        }
        endpoints = {
            str(key): EndpointSnapshot.from_dict(str(key), value)
            for key, value in data.get("endpoints", {}).items()
        }
        return cls(
            version=int(data.get("version", 0)),
            generated_at=generated_at,
            endpoints=MappingProxyType(endpoints),
            pools=MappingProxyType(pools),
            loaded_monotonic=float(loaded_monotonic),
        )

    @classmethod
    def from_json(cls, payload: str | bytes, *, loaded_monotonic: float = 0.0) -> GatewaySnapshot:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError("gateway snapshot must be a JSON object")
        return cls.from_dict(value, loaded_monotonic=loaded_monotonic)

    @classmethod
    def empty(cls) -> GatewaySnapshot:
        return cls(
            version=0,
            generated_at=datetime.fromtimestamp(0, UTC),
            endpoints=MappingProxyType({}),
            pools=MappingProxyType({}),
            loaded_monotonic=0.0,
        )


def decode_basic_credentials(header: bytes | str | None) -> tuple[str, str] | None:
    if header is None:
        return None
    if isinstance(header, bytes):
        try:
            value = header.decode("ascii")
        except UnicodeDecodeError:
            return None
    else:
        value = header
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "basic" or not token:
        return None
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator or not username:
        return None
    return username, password


def endpoint_secret_digest(key: bytes, secret: str) -> str:
    return hmac.new(key, secret.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_endpoint_secret(key: bytes, secret: str, expected: str) -> bool:
    return hmac.compare_digest(endpoint_secret_digest(key, secret), expected.lower())
