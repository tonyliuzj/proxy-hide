from __future__ import annotations

from dataclasses import dataclass

from .errors import Forbidden, PoolUnavailable, ProxyAuthenticationRequired
from .models import (
    EndpointSnapshot,
    GatewaySnapshot,
    decode_basic_credentials,
    verify_endpoint_secret,
)


@dataclass(frozen=True, slots=True)
class AuthenticatedEndpoint:
    endpoint: EndpointSnapshot


class EndpointAuthenticator:
    def __init__(self, hmac_key: bytes) -> None:
        if len(hmac_key) < 16:
            raise ValueError("endpoint HMAC key must contain at least 16 bytes")
        self._hmac_key = hmac_key

    def authenticate(
        self,
        snapshot: GatewaySnapshot,
        proxy_authorization: bytes | str | None,
        client_ip: str,
    ) -> AuthenticatedEndpoint:
        credentials = decode_basic_credentials(proxy_authorization)
        if credentials is None:
            raise ProxyAuthenticationRequired("missing or invalid Proxy-Authorization")
        username, password = credentials
        endpoint = snapshot.endpoints.get(username)
        # Compute a dummy digest for unknown usernames to reduce timing differences.
        expected = endpoint.secret_digest if endpoint else "0" * 64
        valid = verify_endpoint_secret(self._hmac_key, password, expected)
        if endpoint is None or not valid:
            raise ProxyAuthenticationRequired("invalid endpoint credentials")
        if not endpoint.enabled or not endpoint.workspace_enabled:
            raise PoolUnavailable("endpoint or workspace is disabled")
        if not endpoint.allows_ip(client_ip):
            raise Forbidden("source IP is not allowed")
        return AuthenticatedEndpoint(endpoint)
