from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models import (
    CatalogSelection,
    HealthStatus,
    JobStatus,
    JobType,
    OperationStatus,
    PoolStrategy,
    ProxyProtocol,
    TargetAvailability,
    TargetKind,
    UserRole,
    WorkspaceStatus,
)


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


T = TypeVar("T")


class Page[T](Schema):
    items: list[T]
    total: int
    page: int
    page_size: int


class Message(Schema):
    message: str


class LoginRequest(Schema):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class SetupRequest(Schema):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) < 3:
            raise ValueError("email must contain at least 3 characters")
        return normalized

    @field_validator("password")
    @classmethod
    def limit_password_bytes(cls, value: str) -> str:
        if len(value.encode()) > 1024:
            raise ValueError("password must not exceed 1024 bytes")
        return value


class SetupStatus(Schema):
    setup_required: bool


class WorkspaceSummary(Schema):
    id: UUID
    name: str
    slug: str
    status: WorkspaceStatus


class UserView(Schema):
    id: UUID
    email: str
    role: UserRole
    workspace_id: UUID | None


class SessionView(Schema):
    user: UserView
    workspace: WorkspaceSummary | None
    csrf_token: str


class WorkspaceLimitsInput(Schema):
    max_private_proxies: int = Field(default=10_000, ge=0, le=10_000_000)
    max_sources: int = Field(default=20, ge=0, le=10_000)
    max_custom_targets: int = Field(default=10, ge=0, le=10_000)
    max_filters: int = Field(default=20, ge=0, le=10_000)
    max_pools: int = Field(default=10, ge=0, le=10_000)
    max_endpoints: int = Field(default=10, ge=0, le=10_000)
    max_concurrent_checks: int = Field(default=100, ge=1, le=100_000)
    max_gateway_connections: int = Field(default=100, ge=1, le=1_000_000)
    requests_per_minute: int = Field(default=600, ge=1, le=100_000_000)
    global_catalog_enabled: bool = True
    destination_ports: list[int] = Field(default_factory=lambda: [80, 443], max_length=100)

    @field_validator("destination_ports")
    @classmethod
    def valid_ports(cls, value: list[int]) -> list[int]:
        if any(port < 1 or port > 65535 for port in value):
            raise ValueError("destination ports must be between 1 and 65535")
        return sorted(set(value))


class WorkspaceLimitsView(WorkspaceLimitsInput):
    workspace_id: UUID


class WorkspaceCreate(Schema):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=2, max_length=80)
    owner_email: str = Field(min_length=3, max_length=320)
    owner_password: str = Field(min_length=12, max_length=1024)
    limits: WorkspaceLimitsInput = Field(default_factory=WorkspaceLimitsInput)

    @field_validator("owner_email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class WorkspaceUpdate(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: WorkspaceStatus | None = None
    limits: WorkspaceLimitsInput | None = None


class WorkspaceAdminView(WorkspaceSummary):
    owner: UserView
    limits: WorkspaceLimitsView
    created_at: datetime


class PasswordReplace(Schema):
    password: str = Field(min_length=12, max_length=1024)


class PasswordChange(Schema):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class ProxyImportRequest(Schema):
    text: str = Field(min_length=1, max_length=20_000_000)
    default_protocol: ProxyProtocol = ProxyProtocol.HTTP


class ProxyPreviewRow(Schema):
    protocol: ProxyProtocol
    host: str
    port: int
    username: str | None
    identity_hash: str


class ProxyInvalidRow(Schema):
    line: int
    value: str
    error: str


class ProxyImportPreview(Schema):
    valid: list[ProxyPreviewRow]
    invalid: list[ProxyInvalidRow]
    duplicate_lines: list[int]
    valid_count: int
    invalid_count: int
    duplicate_count: int


class ProxyImportResult(Schema):
    imported: int
    duplicates: int
    invalid: int
    operation_id: UUID


class TargetAvailabilityView(Schema):
    target_id: UUID
    availability: TargetAvailability
    checked_at: datetime


class ProxyView(Schema):
    id: UUID
    scope: Literal["global", "private"]
    protocol: ProxyProtocol
    host: str | None = None
    port: int | None = None
    credentials: str | None = None
    country_code: str | None
    asn: int | None
    active: bool
    health: HealthStatus = HealthStatus.UNKNOWN
    score: float = 0
    latency_ms: float | None = None
    success_rate: float = 0


class SourceCreate(Schema):
    name: str = Field(min_length=1, max_length=120)
    url: HttpUrl
    username: str | None = Field(default=None, max_length=1024)
    password: str | None = Field(default=None, max_length=1024)
    default_protocol: ProxyProtocol = ProxyProtocol.HTTP
    enabled: bool = True
    refresh_interval_minutes: int = Field(default=60, ge=5, le=1440)


class SourceUpdate(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: HttpUrl | None = None
    username: str | None = Field(default=None, max_length=1024)
    password: str | None = Field(default=None, max_length=1024)
    clear_credentials: bool = False
    default_protocol: ProxyProtocol | None = None
    enabled: bool | None = None
    refresh_interval_minutes: int | None = Field(default=None, ge=5, le=1440)


class SourceView(Schema):
    id: UUID
    name: str
    url: str
    default_protocol: ProxyProtocol
    enabled: bool
    refresh_interval_minutes: int
    has_credentials: bool
    last_run_at: datetime | None
    last_run_status: str | None
    created_at: datetime


class SourceRunAccepted(Schema):
    operation_id: UUID
    job_id: UUID


class TargetCreate(Schema):
    name: str = Field(min_length=1, max_length=120)
    kind: TargetKind = TargetKind.CUSTOM
    enabled: bool = True
    method: Literal["GET", "HEAD", "POST"] = "GET"
    url: HttpUrl | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    secret_headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(default=None, max_length=65_536)
    status_ranges: list[tuple[int, int]] = Field(default_factory=lambda: [(200, 399)])
    required_literals: list[str] = Field(default_factory=list, max_length=20)
    forbidden_literals: list[str] = Field(default_factory=list, max_length=20)
    required_patterns: list[str] = Field(default_factory=list, max_length=20)
    forbidden_patterns: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("status_ranges")
    @classmethod
    def valid_status_ranges(cls, value: list[tuple[int, int]]) -> list[tuple[int, int]]:
        if not value or any(low < 100 or high > 599 or low > high for low, high in value):
            raise ValueError("status ranges must be ordered values between 100 and 599")
        return value


class TargetUpdate(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    method: Literal["GET", "HEAD", "POST"] | None = None
    url: HttpUrl | None = None
    headers: dict[str, str] | None = None
    secret_headers: dict[str, str] | None = None
    clear_secret_headers: bool = False
    body: str | None = Field(default=None, max_length=65_536)
    clear_body: bool = False
    status_ranges: list[tuple[int, int]] | None = None
    required_literals: list[str] | None = None
    forbidden_literals: list[str] | None = None
    required_patterns: list[str] | None = None
    forbidden_patterns: list[str] | None = None

    @field_validator("status_ranges")
    @classmethod
    def valid_status_ranges(
        cls, value: list[tuple[int, int]] | None
    ) -> list[tuple[int, int]] | None:
        if value is not None and (
            not value or any(low < 100 or high > 599 or low > high for low, high in value)
        ):
            raise ValueError("status ranges must be ordered values between 100 and 599")
        return value


class TargetView(Schema):
    id: UUID
    name: str
    kind: TargetKind
    enabled: bool
    method: str
    url: str | None
    headers: dict[str, str]
    has_secret_headers: bool
    has_body: bool
    status_ranges: list[list[int]]
    required_literals: list[str]
    forbidden_literals: list[str]
    required_patterns: list[str]
    forbidden_patterns: list[str]
    created_at: datetime


class TargetCheckAccepted(Schema):
    operation_id: UUID
    job_id: UUID


class FilterCreate(Schema):
    name: str = Field(min_length=1, max_length=120)
    rules: dict[str, Any]


class FilterUpdate(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    rules: dict[str, Any] | None = None


class FilterView(Schema):
    id: UUID
    name: str
    version: int
    rules: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class FilterPreviewRequest(Schema):
    rules: dict[str, Any]
    catalog_selection: CatalogSelection = CatalogSelection.COMBINED
    sample_size: int = Field(default=10, ge=0, le=50)


class FilterPreviewResult(Schema):
    count: int
    sample: list[ProxyView]


class PoolCreate(Schema):
    name: str = Field(min_length=1, max_length=120)
    filter_id: UUID
    catalog_selection: CatalogSelection = CatalogSelection.COMBINED
    strategy: PoolStrategy = PoolStrategy.WEIGHTED_HEALTH
    enabled: bool = True


class PoolUpdate(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    filter_id: UUID | None = None
    catalog_selection: CatalogSelection | None = None
    strategy: PoolStrategy | None = None
    enabled: bool | None = None


class PoolView(Schema):
    id: UUID
    name: str
    filter_id: UUID
    catalog_selection: CatalogSelection
    strategy: PoolStrategy
    enabled: bool
    current_revision: int | None
    materialized_at: datetime | None
    created_at: datetime


class EndpointCreate(Schema):
    name: str = Field(min_length=1, max_length=120)
    pool_id: UUID
    username: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,63}$")
    enabled: bool = True
    ip_allowlist: list[str] = Field(default_factory=list, max_length=100)


class EndpointUpdate(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    pool_id: UUID | None = None
    enabled: bool | None = None
    ip_allowlist: list[str] | None = Field(default=None, max_length=100)


class EndpointView(Schema):
    id: UUID
    name: str
    pool_id: UUID
    username: str
    enabled: bool
    ip_allowlist: list[str]
    secret_rotated_at: datetime | None
    created_at: datetime


class EndpointCreated(EndpointView):
    secret: str
    plaintext_url: str
    secure_url: str


class JobView(Schema):
    id: UUID
    type: JobType
    status: JobStatus
    entity_id: UUID | None
    attempt: int
    max_attempts: int
    progress_current: int
    progress_total: int
    error: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class CheckAttemptView(Schema):
    id: UUID
    job_id: UUID
    proxy_id: UUID
    target_id: UUID | None
    success: bool
    latency_ms: float | None
    error_code: str | None
    error_message: str | None
    availability: TargetAvailability | None
    checked_at: datetime


class OperationView(Schema):
    id: UUID
    kind: str
    status: OperationStatus
    progress_current: int
    progress_total: int
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    created_at: datetime
    finished_at: datetime | None


class AuditEventView(Schema):
    id: UUID
    actor_user_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    ip_address: str | None
    details: dict[str, Any]
    created_at: datetime


class TrafficPoint(Schema):
    bucket_start: datetime
    requests: int
    successes: int
    failures: int
    bytes_up: int
    bytes_down: int
    average_latency_ms: float | None


class TrafficSummary(Schema):
    requests: int
    successes: int
    failures: int
    bytes_up: int
    bytes_down: int
    average_latency_ms: float | None
    points: list[TrafficPoint]


class DashboardSummary(Schema):
    proxies_total: int
    proxies_healthy: int
    sources_total: int
    pools_total: int
    pools_ready: int
    endpoints_total: int
    active_jobs: int
    requests_24h: int
    successful_requests_24h: int
    recent_checks: list[JobView] = Field(default_factory=list)


class UsageView(Schema):
    private_proxies: int
    sources: int
    custom_targets: int
    filters: int
    pools: int
    endpoints: int


class WorkspaceSettingsView(Schema):
    workspace: WorkspaceSummary
    limits: WorkspaceLimitsView
    usage: UsageView


class WorkspaceSettingsUpdate(Schema):
    name: str = Field(min_length=1, max_length=120)
