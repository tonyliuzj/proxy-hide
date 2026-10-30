from __future__ import annotations

import base64
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

    def authenticate_listener(
        self,
        snapshot: GatewaySnapshot,
        port: int,
        proxy_authorization: bytes | str | None,
        client_ip: str,
    ) -> AuthenticatedEndpoint:
        """Authenticate a client of a dedicated ``ip:port`` listener.

        An open listener trusts the client address alone, so an empty allowlist
        is refused instead of being treated as "any address".
        """
        endpoint = snapshot.listeners.get(port)
        if endpoint is None:
            raise PoolUnavailable("no endpoint is bound to this port")
        if endpoint.require_auth:
            authenticated = self.authenticate(snapshot, proxy_authorization, client_ip)
            if authenticated.endpoint.id != endpoint.id:
                raise ProxyAuthenticationRequired("invalid endpoint credentials")
            return authenticated
        if not endpoint.enabled or not endpoint.workspace_enabled:
            raise PoolUnavailable("endpoint or workspace is disabled")
        if not endpoint.ip_allowlist or not endpoint.allows_ip(client_ip):
            raise Forbidden("source IP is not allowed")
        return AuthenticatedEndpoint(endpoint)

    def authenticate_credentials(
        self, snapshot: GatewaySnapshot, username: str, password: str, client_ip: str
    ) -> AuthenticatedEndpoint:
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        return self.authenticate(snapshot, f"Basic {token}", client_ip)
