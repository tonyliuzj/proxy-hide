"""Gateway exceptions with stable client-facing status mappings."""


class GatewayError(Exception):
    status_code = 502
    reason = "Bad Gateway"
    code = "gateway_error"


class BadRequest(GatewayError):
    status_code = 400
    reason = "Bad Request"
    code = "bad_request"


class ProxyAuthenticationRequired(GatewayError):
    status_code = 407
    reason = "Proxy Authentication Required"
    code = "proxy_authentication_required"


class Forbidden(GatewayError):
    status_code = 403
    reason = "Forbidden"
    code = "forbidden"


class PoolUnavailable(GatewayError):
    status_code = 503
    reason = "Service Unavailable"
    code = "pool_unavailable"


class UpstreamFailure(GatewayError):
    status_code = 502
    reason = "Bad Gateway"
    code = "upstream_failure"


class GatewayTimeout(GatewayError):
    status_code = 504
    reason = "Gateway Timeout"
    code = "gateway_timeout"


class DestinationDenied(Forbidden):
    code = "destination_denied"


class ProtocolError(BadRequest):
    code = "protocol_error"


class UpstreamConnectError(UpstreamFailure):
    """An upstream failed before any client-visible response was committed."""


class UpstreamAuthError(UpstreamConnectError):
    """Upstream credentials were refused. Never map this to client 407."""


class UpstreamTimeout(UpstreamConnectError):
    """An individual upstream attempt timed out."""
