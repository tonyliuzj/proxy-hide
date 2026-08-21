from __future__ import annotations

import pytest

from app.domain.proxies import ProxyParseError, parse_proxy, parse_proxy_text
from app.models import ProxyProtocol


@pytest.mark.parametrize(
    ("value", "protocol", "host", "port", "username", "password"),
    [
        ("HTTP://Example.COM:8080", ProxyProtocol.HTTP, "example.com", 8080, None, None),
        ("socks5://u:p@[2001:db8::1]:1080", ProxyProtocol.SOCKS5, "2001:db8::1", 1080, "u", "p"),
        ("user:pass@proxy.test:3128", ProxyProtocol.HTTP, "proxy.test", 3128, "user", "pass"),
        ("proxy.test:3128:user:pass", ProxyProtocol.HTTP, "proxy.test", 3128, "user", "pass"),
        ("[2001:db8::2]:1080", ProxyProtocol.HTTP, "2001:db8::2", 1080, None, None),
    ],
)
def test_supported_proxy_formats(value, protocol, host, port, username, password) -> None:
    proxy = parse_proxy(value)
    assert (proxy.protocol, proxy.host, proxy.port, proxy.username, proxy.password) == (
        protocol,
        host,
        port,
        username,
        password,
    )


def test_credentials_are_part_of_identity_and_never_in_redacted_uri() -> None:
    first = parse_proxy("http://alice:secret@example.com:80")
    second = parse_proxy("http://alice:different@example.com:80")
    assert first.identity_hash != second.identity_hash
    assert "secret" not in first.redacted_uri
    assert first.redacted_uri == "http://alice:%2A%2A%2A@example.com:80"


def test_preview_classifies_duplicates_and_invalid_rows() -> None:
    preview = parse_proxy_text(
        "# comment\nexample.com:80\nEXAMPLE.COM:80\ninvalid\nexample.net:70000\n"
    )
    assert len(preview.valid) == 1
    assert preview.duplicate_lines == (3,)
    assert [row.line for row in preview.invalid] == [4, 5]


@pytest.mark.parametrize("value", ["host:0", "host:65536", "host:80:user", "ftp://host:21"])
def test_invalid_proxy_inputs(value: str) -> None:
    with pytest.raises(ProxyParseError):
        parse_proxy(value)
