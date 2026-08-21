from __future__ import annotations

import asyncio
import ipaddress
import struct
from dataclasses import dataclass

from .errors import ProtocolError

SIGNATURE = b"\r\n\r\n\x00\r\nQUIT\n"


@dataclass(frozen=True, slots=True)
class ProxyPeer:
    source_ip: str
    source_port: int
    destination_ip: str
    destination_port: int


async def read_proxy_v2(reader: asyncio.StreamReader, *, read_timeout: float = 3.0) -> ProxyPeer:
    try:
        header = await asyncio.wait_for(reader.readexactly(16), timeout=read_timeout)
    except (TimeoutError, asyncio.IncompleteReadError) as exc:
        raise ProtocolError("missing PROXY v2 header") from exc
    if header[:12] != SIGNATURE or header[12] >> 4 != 2:
        raise ProtocolError("invalid PROXY v2 signature or version")
    command = header[12] & 0x0F
    family_protocol = header[13]
    length = struct.unpack("!H", header[14:])[0]
    if command != 1:
        raise ProtocolError("PROXY v2 LOCAL command is not accepted")
    if length > 512:
        raise ProtocolError("PROXY v2 header is too large")
    try:
        payload = await asyncio.wait_for(reader.readexactly(length), timeout=read_timeout)
    except (TimeoutError, asyncio.IncompleteReadError) as exc:
        raise ProtocolError("truncated PROXY v2 header") from exc

    if family_protocol == 0x11 and len(payload) >= 12:
        source = str(ipaddress.ip_address(payload[:4]))
        destination = str(ipaddress.ip_address(payload[4:8]))
        source_port, destination_port = struct.unpack("!HH", payload[8:12])
    elif family_protocol == 0x21 and len(payload) >= 36:
        source = str(ipaddress.ip_address(payload[:16]))
        destination = str(ipaddress.ip_address(payload[16:32]))
        source_port, destination_port = struct.unpack("!HH", payload[32:36])
    else:
        raise ProtocolError("unsupported PROXY v2 address family or transport")
    return ProxyPeer(source, source_port, destination, destination_port)


def peer_is_trusted(
    peer_ip: str,
    trusted_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    try:
        address = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    return any(address in network for network in trusted_networks)
