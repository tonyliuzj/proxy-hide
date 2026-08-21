from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import maxminddb


@dataclass(frozen=True, slots=True)
class GeoIPResult:
    country_code: str | None
    asn: int | None


class GeoIPResolver:
    """Lazy, optional lookup over a MaxMind-compatible database."""

    def __init__(self, database_path: str | None) -> None:
        self.database_path = Path(database_path) if database_path else None
        self._reader: Any | None = None
        self._open_attempted = False

    def lookup(self, address: str) -> GeoIPResult | None:
        try:
            ipaddress.ip_address(address)
        except ValueError:
            return None
        reader = self._get_reader()
        if reader is None:
            return None
        try:
            record = reader.get(address)
        except (OSError, ValueError, maxminddb.errors.InvalidDatabaseError):
            return None
        if not isinstance(record, Mapping):
            return None
        return GeoIPResult(
            country_code=_country_code(record),
            asn=_integer(record.get("autonomous_system_number")),
        )

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None

    def _get_reader(self) -> Any | None:
        if self._reader is not None:
            return self._reader
        if self._open_attempted or self.database_path is None:
            return None
        self._open_attempted = True
        try:
            self._reader = maxminddb.open_database(str(self.database_path))
        except (OSError, maxminddb.errors.InvalidDatabaseError):
            return None
        return self._reader


def _country_code(record: Mapping[str, Any]) -> str | None:
    for field in ("country", "registered_country", "represented_country"):
        value = record.get(field)
        if isinstance(value, Mapping):
            code = value.get("iso_code")
            if isinstance(code, str) and len(code) == 2:
                return code.upper()
    return None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
