from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


def enum_type(enum_cls: type[enum.Enum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
        length=max(len(member.value) for member in enum_cls),
    )


class WorkspaceStatus(enum.StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserRole(enum.StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    WORKSPACE_OWNER = "workspace_owner"
    WORKSPACE_OPERATOR = "workspace_operator"
    WORKSPACE_VIEWER = "workspace_viewer"


class AlertSeverity(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(enum.StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class WebhookDeliveryStatus(enum.StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProxyScope(enum.StrEnum):
    GLOBAL = "global"
    PRIVATE = "private"


class ProxyProtocol(enum.StrEnum):
    HTTP = "http"
    HTTPS = "https"
    SOCKS4A = "socks4a"
    SOCKS5 = "socks5"


class HealthStatus(enum.StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class TargetAvailability(enum.StrEnum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    BLOCKED = "blocked"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"


class TargetKind(enum.StrEnum):
    GOOGLE = "google"
    BING = "bing"
    BRAVE = "brave"
    STARTPAGE = "startpage"
    DUCKDUCKGO = "duckduckgo"
    WIKIPEDIA = "wikipedia"
    CUSTOM = "custom"


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"


class JobType(enum.StrEnum):
    CHECK_PROXY = "check_proxy"
    CHECK_TARGET = "check_target"
    REFRESH_SOURCE = "refresh_source"
    MATERIALIZE_POOL = "materialize_pool"
    PUBLISH_SNAPSHOT = "publish_snapshot"
    RETENTION = "retention"


class PoolStrategy(enum.StrEnum):
    RANDOM = "random"
    ROUND_ROBIN = "round_robin"
    LOWEST_LATENCY = "lowest_latency"
    WEIGHTED_HEALTH = "weighted_health"
    STICKY = "sticky"


class CatalogSelection(enum.StrEnum):
    GLOBAL = "global"
    PRIVATE = "private"
    COMBINED = "combined"


class OperationStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    status: Mapped[WorkspaceStatus] = mapped_column(
        enum_type(WorkspaceStatus, "workspace_status"), default=WorkspaceStatus.ACTIVE
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    limits: Mapped[WorkspaceLimit] = relationship(
        back_populates="workspace", uselist=False, cascade="all, delete-orphan"
    )


class WorkspaceLimit(TimestampMixin, Base):
    __tablename__ = "workspace_limits"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    max_private_proxies: Mapped[int] = mapped_column(Integer, default=10_000)
    max_sources: Mapped[int] = mapped_column(Integer, default=20)
    max_custom_targets: Mapped[int] = mapped_column(Integer, default=10)
    max_filters: Mapped[int] = mapped_column(Integer, default=20)
    max_pools: Mapped[int] = mapped_column(Integer, default=10)
    max_endpoints: Mapped[int] = mapped_column(Integer, default=10)
    max_concurrent_checks: Mapped[int] = mapped_column(Integer, default=100)
    max_gateway_connections: Mapped[int] = mapped_column(Integer, default=100)
    requests_per_minute: Mapped[int] = mapped_column(Integer, default=600)
    global_catalog_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    destination_ports: Mapped[list[int]] = mapped_column(JSON, default=lambda: [80, 443])
    retention_days: Mapped[int] = mapped_column(Integer, default=30)

    workspace: Mapped[Workspace] = relationship(back_populates="limits")


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[UserRole] = mapped_column(enum_type(UserRole, "user_role"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(role = 'platform_admin' AND workspace_id IS NULL) OR "
            "(role IN ('workspace_owner', 'workspace_operator', 'workspace_viewer') "
            "AND workspace_id IS NOT NULL)",
            name="role_workspace",
        ),
    )


class APIToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_tokens"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["read"])
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_ip: Mapped[str | None] = mapped_column(String(45))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_api_token_name"),)


class ProxyRoute(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "proxy_routes"

    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[ProxyScope] = mapped_column(enum_type(ProxyScope, "proxy_scope"), index=True)
    protocol: Mapped[ProxyProtocol] = mapped_column(enum_type(ProxyProtocol, "proxy_protocol"))
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    password_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manual: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    asn: Mapped[int | None] = mapped_column(Integer, index=True)
    exit_ip: Mapped[str | None] = mapped_column(String(45))

    health: Mapped[ProxyHealth | None] = relationship(
        back_populates="proxy", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("port >= 1 AND port <= 65535", name="valid_port"),
        CheckConstraint(
            "(scope = 'global' AND workspace_id IS NULL) OR "
            "(scope = 'private' AND workspace_id IS NOT NULL)",
            name="scope_workspace",
        ),
        UniqueConstraint("workspace_id", "scope", "identity_hash", name="uq_proxy_identity"),
        Index(
            "uq_proxy_global_identity",
            "identity_hash",
            unique=True,
            postgresql_where=(scope == ProxyScope.GLOBAL),
            sqlite_where=(scope == ProxyScope.GLOBAL),
        ),
    )


class ProxyHealth(TimestampMixin, Base):
    __tablename__ = "proxy_health"

    proxy_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("proxy_routes.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[HealthStatus] = mapped_column(
        enum_type(HealthStatus, "health_status"), default=HealthStatus.UNKNOWN, index=True
    )
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    success_ewma: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ewma_ms: Mapped[float | None] = mapped_column(Float)
    valid_checks: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_message: Mapped[str | None] = mapped_column(String(500))

    proxy: Mapped[ProxyRoute] = relationship(back_populates="health")


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[ProxyScope] = mapped_column(enum_type(ProxyScope, "source_scope"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    username_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    password_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    default_protocol: Mapped[ProxyProtocol] = mapped_column(
        enum_type(ProxyProtocol, "source_default_protocol"), default=ProxyProtocol.HTTP
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    refresh_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_status: Mapped[str | None] = mapped_column(String(32))
    consecutive_complete_absences_required: Mapped[int] = mapped_column(Integer, default=2)

    __table_args__ = (
        CheckConstraint(
            "refresh_interval_minutes >= 5 AND refresh_interval_minutes <= 1440",
            name="refresh_interval",
        ),
        CheckConstraint(
            "(scope = 'global' AND workspace_id IS NULL) OR "
            "(scope = 'private' AND workspace_id IS NOT NULL)",
            name="scope_workspace",
        ),
    )


class SourceMembership(TimestampMixin, Base):
    __tablename__ = "source_memberships"

    source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    proxy_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("proxy_routes.id", ondelete="CASCADE"), primary_key=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    absent_complete_runs: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_runs"

    source_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sources.id", ondelete="CASCADE"))
    workspace_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    status: Mapped[JobStatus] = mapped_column(enum_type(JobStatus, "source_run_status"))
    complete_snapshot: Mapped[bool] = mapped_column(Boolean, default=False)
    parsed_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0)
    added_count: Mapped[int] = mapped_column(Integer, default=0)
    deactivated_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Target(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "targets"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[TargetKind] = mapped_column(enum_type(TargetKind, "target_kind"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    method: Mapped[str] = mapped_column(String(8), default="GET")
    url: Mapped[str | None] = mapped_column(Text)
    headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    secret_headers_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    body_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    status_ranges: Mapped[list[list[int]]] = mapped_column(JSON, default=lambda: [[200, 399]])
    required_literals: Mapped[list[str]] = mapped_column(JSON, default=list)
    forbidden_literals: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)
    forbidden_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_target_name"),
        UniqueConstraint("workspace_id", "id", name="uq_target_workspace_id"),
    )


class TargetHealth(TimestampMixin, Base):
    __tablename__ = "target_health"

    workspace_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    target_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    proxy_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    availability: Mapped[TargetAvailability] = mapped_column(
        enum_type(TargetAvailability, "target_availability"), index=True
    )
    latency_ms: Mapped[float | None] = mapped_column(Float)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "target_id"],
            ["targets.workspace_id", "targets.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["proxy_id"], ["proxy_routes.id"], ondelete="CASCADE"),
    )


class Filter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "filters"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    rules: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_filter_name"),
        UniqueConstraint("workspace_id", "id", name="uq_filter_workspace_id"),
    )


class Pool(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pools"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    filter_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    catalog_selection: Mapped[CatalogSelection] = mapped_column(
        enum_type(CatalogSelection, "catalog_selection"), default=CatalogSelection.COMBINED
    )
    strategy: Mapped[PoolStrategy] = mapped_column(enum_type(PoolStrategy, "pool_strategy"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    current_revision: Mapped[int | None] = mapped_column(Integer)
    materialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "filter_id"], ["filters.workspace_id", "filters.id"]),
        UniqueConstraint("workspace_id", "name", name="uq_pool_name"),
        UniqueConstraint("workspace_id", "id", name="uq_pool_workspace_id"),
    )


class PoolRevision(TimestampMixin, Base):
    __tablename__ = "pool_revisions"

    workspace_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    pool_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    rule_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "pool_id"], ["pools.workspace_id", "pools.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("pool_id", "revision", name="uq_pool_revision_ref"),
    )


class PoolMember(Base):
    __tablename__ = "pool_members"

    pool_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    proxy_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("proxy_routes.id", ondelete="CASCADE"), primary_key=True
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        ForeignKeyConstraint(
            ["pool_id", "revision"],
            ["pool_revisions.pool_id", "pool_revisions.revision"],
            ondelete="CASCADE",
        ),
    )


class Endpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "endpoints"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    pool_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    secret_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ip_allowlist: Mapped[list[str]] = mapped_column(JSON, default=list)
    secret_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A dedicated port is advertised as plain ip:port. When require_auth is false the
    # gateway trusts ip_allowlist alone, so the API refuses an empty allowlist.
    listen_port: Mapped[int | None] = mapped_column(Integer)
    require_auth: Mapped[bool] = mapped_column(Boolean, default=True)
    # Overrides the pool's rotation mode for this endpoint only.
    strategy: Mapped[PoolStrategy | None] = mapped_column(
        enum_type(PoolStrategy, "endpoint_strategy")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "pool_id"], ["pools.workspace_id", "pools.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("workspace_id", "name", name="uq_endpoint_name"),
        UniqueConstraint("listen_port", name="uq_endpoint_listen_port"),
        UniqueConstraint("workspace_id", "id", name="uq_endpoint_workspace_id"),
    )


class CheckJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "check_jobs"

    workspace_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    type: Mapped[JobType] = mapped_column(enum_type(JobType, "job_type"), index=True)
    status: Mapped[JobStatus] = mapped_column(
        enum_type(JobStatus, "job_status"), default=JobStatus.QUEUED, index=True
    )
    entity_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    deduplication_key: Mapped[str] = mapped_column(String(255), unique=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CheckAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "check_attempts"

    workspace_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    job_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("check_jobs.id", ondelete="CASCADE"))
    proxy_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("proxy_routes.id", ondelete="CASCADE"))
    target_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("targets.id", ondelete="CASCADE")
    )
    success: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(80), index=True)
    error_message: Mapped[str | None] = mapped_column(String(500))
    availability: Mapped[TargetAvailability | None] = mapped_column(
        enum_type(TargetAvailability, "attempt_target_availability")
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Operation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "operations"

    workspace_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    kind: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[OperationStatus] = mapped_column(
        enum_type(OperationStatus, "operation_status"), default=OperationStatus.PENDING
    )
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "outbox_events"

    topic: Mapped[str] = mapped_column(String(120), index=True)
    aggregate_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))


class TrafficRollup(Base):
    __tablename__ = "traffic_rollups"

    workspace_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    endpoint_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    pool_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    granularity: Mapped[str] = mapped_column(String(8), primary_key=True)
    requests: Mapped[int] = mapped_column(BigInteger, default=0)
    successes: Mapped[int] = mapped_column(BigInteger, default=0)
    failures: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_up: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_down: Mapped[int] = mapped_column(BigInteger, default=0)
    latency_sum_ms: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "endpoint_id"],
            ["endpoints.workspace_id", "endpoints.id"],
            ondelete="CASCADE",
        ),
    )


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"

    workspace_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[UUID | None] = mapped_column(Uuid)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Alert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alerts"

    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        enum_type(AlertSeverity, "alert_severity"), index=True
    )
    status: Mapped[AlertStatus] = mapped_column(
        enum_type(AlertStatus, "alert_status"), default=AlertStatus.OPEN, index=True
    )
    code: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(String(1000))
    resource_type: Mapped[str | None] = mapped_column(String(80))
    resource_id: Mapped[UUID | None] = mapped_column(Uuid)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    acknowledged_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Webhook(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "webhooks"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(Text)
    secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    events: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_delivery_status: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_webhook_name"),)


class WebhookDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "webhook_deliveries"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    webhook_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("webhooks.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(120), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[WebhookDeliveryStatus] = mapped_column(
        enum_type(WebhookDeliveryStatus, "webhook_delivery_status"),
        default=WebhookDeliveryStatus.PENDING,
        index=True,
    )
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[str | None] = mapped_column(String(1000))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
