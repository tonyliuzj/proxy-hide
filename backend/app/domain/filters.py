from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, exists, false, not_, or_
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    HealthStatus,
    ProxyHealth,
    ProxyProtocol,
    ProxyRoute,
    ProxyScope,
    TargetAvailability,
    TargetHealth,
)


class FilterValidationError(ValueError):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("filter rules are invalid")


@dataclass(frozen=True, slots=True)
class ValidatedFilter:
    version: int
    root: dict[str, Any]


_FIELD_OPERATORS = {
    "protocol": {"eq", "neq", "in", "not_in"},
    "catalog_scope": {"eq", "neq", "in", "not_in"},
    "country": {"eq", "neq", "in", "not_in"},
    "asn": {"eq", "neq", "in", "not_in"},
    "latency_ms": {"eq", "neq", "lt", "lte", "gt", "gte"},
    "success_rate": {"eq", "neq", "lt", "lte", "gt", "gte"},
    "score": {"eq", "neq", "lt", "lte", "gt", "gte"},
    "health": {"eq", "neq", "in", "not_in"},
    "target_availability": {"eq", "neq", "in", "not_in"},
}
_ENUM_FIELDS: dict[str, type[enum.Enum]] = {
    "protocol": ProxyProtocol,
    "catalog_scope": ProxyScope,
    "health": HealthStatus,
    "target_availability": TargetAvailability,
}
_MAX_DEPTH = 8
_MAX_NODES = 100


def _path(parts: tuple[str | int, ...]) -> str:
    return ".".join(str(part) for part in parts)


def validate_filter(payload: dict[str, Any]) -> ValidatedFilter:
    errors: list[dict[str, str]] = []
    version = payload.get("version", 1)
    if version != 1:
        errors.append({"field": "version", "message": "only filter version 1 is supported"})
    root = payload.get("root", payload if "op" in payload else None)
    if not isinstance(root, dict):
        errors.append({"field": "root", "message": "root must be an expression object"})
        raise FilterValidationError(errors)

    node_count = 0

    def visit(node: Any, path: tuple[str | int, ...], depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > _MAX_NODES:
            errors.append({"field": _path(path), "message": "filter exceeds 100 nodes"})
            return
        if depth > _MAX_DEPTH:
            errors.append({"field": _path(path), "message": "filter exceeds 8 levels"})
            return
        if not isinstance(node, dict):
            errors.append({"field": _path(path), "message": "expression must be an object"})
            return
        op = node.get("op")
        if op in {"all", "any"}:
            rules = node.get("rules")
            if not isinstance(rules, list) or not rules:
                errors.append(
                    {"field": _path((*path, "rules")), "message": "rules cannot be empty"}
                )
                return
            for index, rule in enumerate(rules):
                visit(rule, (*path, "rules", index), depth + 1)
            return
        if op == "not":
            if "rule" not in node:
                errors.append({"field": _path((*path, "rule")), "message": "rule is required"})
                return
            visit(node["rule"], (*path, "rule"), depth + 1)
            return
        if op != "predicate":
            errors.append({"field": _path((*path, "op")), "message": "unknown expression op"})
            return
        field = node.get("field")
        operator = node.get("operator")
        if field not in _FIELD_OPERATORS:
            errors.append({"field": _path((*path, "field")), "message": "unknown field"})
            return
        if operator not in _FIELD_OPERATORS[field]:
            errors.append(
                {
                    "field": _path((*path, "operator")),
                    "message": "operator is not allowed for field",
                }
            )
            return
        value = node.get("value")
        values: list[Any]
        if operator in {"in", "not_in"}:
            if not isinstance(value, list) or not value:
                errors.append(
                    {
                        "field": _path((*path, "value")),
                        "message": "value must be a non-empty list",
                    }
                )
                return
            values = value
        else:
            values = [value]
        if field in _ENUM_FIELDS:
            enum_cls = _ENUM_FIELDS[field]
            for item in values:
                try:
                    enum_cls(item)
                except (TypeError, ValueError):
                    errors.append(
                        {"field": _path((*path, "value")), "message": f"invalid {field} value"}
                    )
        elif field == "country":
            if any(
                not isinstance(item, str) or len(item) != 2 or not item.isalpha() for item in values
            ):
                errors.append(
                    {
                        "field": _path((*path, "value")),
                        "message": "country must be a two-letter code",
                    }
                )
        elif field in {"asn", "latency_ms", "success_rate", "score"}:
            if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in values):
                errors.append(
                    {"field": _path((*path, "value")), "message": "value must be numeric"}
                )
            if field in {"success_rate", "score"} and any(
                isinstance(item, (int, float)) and not 0 <= item <= 100 for item in values
            ):
                errors.append({"field": _path((*path, "value")), "message": "value must be 0-100"})
        if field == "target_availability":
            try:
                UUID(str(node.get("target_id")))
            except (TypeError, ValueError):
                errors.append(
                    {"field": _path((*path, "target_id")), "message": "target_id must be a UUID"}
                )

    visit(root, ("root",), 1)
    if errors:
        raise FilterValidationError(errors)
    return ValidatedFilter(version=1, root=root)


def _comparison(column: Any, operator: str, value: Any) -> ColumnElement[bool]:
    if operator == "eq":
        return cast(ColumnElement[bool], column == value)
    if operator == "neq":
        return cast(ColumnElement[bool], column != value)
    if operator == "lt":
        return cast(ColumnElement[bool], column < value)
    if operator == "lte":
        return cast(ColumnElement[bool], column <= value)
    if operator == "gt":
        return cast(ColumnElement[bool], column > value)
    if operator == "gte":
        return cast(ColumnElement[bool], column >= value)
    if operator == "in":
        return cast(ColumnElement[bool], column.in_(value))
    if operator == "not_in":
        return cast(ColumnElement[bool], column.not_in(value))
    raise AssertionError(f"unsupported validated operator: {operator}")


def compile_filter(payload: dict[str, Any], workspace_id: UUID) -> ColumnElement[bool]:
    validated = validate_filter(payload)

    def compile_node(node: dict[str, Any]) -> ColumnElement[bool]:
        op = node["op"]
        if op == "all":
            return and_(*(compile_node(rule) for rule in node["rules"]))
        if op == "any":
            return or_(*(compile_node(rule) for rule in node["rules"]))
        if op == "not":
            return not_(compile_node(node["rule"]))

        field = node["field"]
        operator = node["operator"]
        value = node["value"]
        if field == "country":
            if isinstance(value, list):
                value = [item.upper() for item in value]
            elif isinstance(value, str):
                value = value.upper()
        enum_cls = _ENUM_FIELDS.get(field)
        if enum_cls is not None and field != "target_availability":
            if isinstance(value, list):
                value = [enum_cls(item) for item in value]
            else:
                value = enum_cls(value)
        columns = {
            "protocol": ProxyRoute.protocol,
            "catalog_scope": ProxyRoute.scope,
            "country": ProxyRoute.country_code,
            "asn": ProxyRoute.asn,
            "latency_ms": ProxyHealth.latency_ewma_ms,
            "success_rate": ProxyHealth.success_ewma * 100.0,
            "score": ProxyHealth.score,
            "health": ProxyHealth.status,
        }
        if field in columns:
            return _comparison(columns[field], operator, value)
        target_id = UUID(str(node["target_id"]))
        availability_values = (
            [TargetAvailability(item) for item in value]
            if isinstance(value, list)
            else TargetAvailability(value)
        )
        match = exists().where(
            TargetHealth.workspace_id == workspace_id,
            TargetHealth.target_id == target_id,
            TargetHealth.proxy_id == ProxyRoute.id,
            _comparison(TargetHealth.availability, operator, availability_values),
        )
        return match

    return compile_node(validated.root)


def catalog_scope_clause(selection: str, workspace_id: UUID) -> ColumnElement[bool]:
    if selection == "global":
        return ProxyRoute.scope == ProxyScope.GLOBAL
    if selection == "private":
        return and_(ProxyRoute.scope == ProxyScope.PRIVATE, ProxyRoute.workspace_id == workspace_id)
    if selection == "combined":
        private_route = aliased(ProxyRoute)
        shadowed_global = exists().where(
            private_route.scope == ProxyScope.PRIVATE,
            private_route.workspace_id == workspace_id,
            private_route.active.is_(True),
            private_route.identity_hash == ProxyRoute.identity_hash,
        )
        return or_(
            and_(ProxyRoute.scope == ProxyScope.GLOBAL, not_(shadowed_global)),
            and_(ProxyRoute.scope == ProxyScope.PRIVATE, ProxyRoute.workspace_id == workspace_id),
        )
    return false()


def empty_filter() -> dict[str, Any]:
    return {
        "version": 1,
        "root": {
            "op": "all",
            "rules": [{"op": "predicate", "field": "health", "operator": "eq", "value": "healthy"}],
        },
    }


def referenced_target_ids(payload: dict[str, Any]) -> set[UUID]:
    validated = validate_filter(payload)
    identifiers: set[UUID] = set()

    def visit(node: dict[str, Any]) -> None:
        if node["op"] in {"all", "any"}:
            for rule in node["rules"]:
                visit(rule)
        elif node["op"] == "not":
            visit(node["rule"])
        elif node.get("field") == "target_availability":
            identifiers.add(UUID(str(node["target_id"])))

    visit(validated.root)
    return identifiers
