from __future__ import annotations

from collections.abc import Iterable

from .errors import BadRequest

_HOP_BY_HOP = {
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"proxy-connection",
    b"te",
    b"trailer",
    b"transfer-encoding",
    b"upgrade",
}


def first_header(headers: Iterable[tuple[bytes, bytes]], name: bytes) -> bytes | None:
    target = name.lower()
    for key, value in headers:
        if key.lower() == target:
            return value
    return None


def sanitized_request_headers(
    headers: Iterable[tuple[bytes, bytes]],
    *,
    authority: str,
    keep_alive: bool = False,
) -> list[tuple[bytes, bytes]]:
    values = list(headers)
    connection_tokens: set[bytes] = set()
    host_values: list[bytes] = []
    has_transfer_encoding = False
    content_lengths: set[bytes] = set()
    for key, value in values:
        lower = key.lower()
        if lower == b"connection":
            connection_tokens.update(
                item.strip().lower() for item in value.split(b",") if item.strip()
            )
        elif lower == b"host":
            host_values.append(value.strip())
        elif lower == b"transfer-encoding":
            has_transfer_encoding = True
        elif lower == b"content-length":
            content_lengths.add(value.strip())
    if has_transfer_encoding and content_lengths:
        raise BadRequest("Transfer-Encoding with Content-Length is not allowed")
    if len(content_lengths) > 1:
        raise BadRequest("conflicting Content-Length headers")
    if len(host_values) > 1 and len(set(host_values)) > 1:
        raise BadRequest("conflicting Host headers")

    stripped = _HOP_BY_HOP | connection_tokens
    result = [
        (key, value)
        for key, value in values
        if key.lower() not in stripped and key.lower() != b"host"
    ]
    result.insert(0, (b"host", authority.encode("ascii")))
    result.append((b"connection", b"keep-alive" if keep_alive else b"close"))
    return result


def sanitized_response_headers(headers: Iterable[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    values = list(headers)
    connection_tokens: set[bytes] = set()
    for key, value in values:
        if key.lower() == b"connection":
            connection_tokens.update(
                item.strip().lower() for item in value.split(b",") if item.strip()
            )
    stripped = _HOP_BY_HOP | connection_tokens
    result = [(key, value) for key, value in values if key.lower() not in stripped]
    result.append((b"connection", b"close"))
    return result
