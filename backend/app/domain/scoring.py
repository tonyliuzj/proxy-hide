from __future__ import annotations

from dataclasses import dataclass

from app.models import HealthStatus

SUCCESS_ALPHA = 0.3
LATENCY_ALPHA = 0.2
MIN_LATENCY_MS = 200.0
MAX_LATENCY_MS = 5_000.0


def ewma(previous: float | None, sample: float, alpha: float) -> float:
    if previous is None:
        return sample
    return alpha * sample + (1.0 - alpha) * previous


def latency_factor(latency_ms: float | None) -> float:
    if latency_ms is None:
        return 0.0
    bounded = min(max(latency_ms, MIN_LATENCY_MS), MAX_LATENCY_MS)
    return 1.0 - (bounded - MIN_LATENCY_MS) / (MAX_LATENCY_MS - MIN_LATENCY_MS)


def health_score(success_ewma: float, latency_ewma_ms: float | None) -> float:
    success = min(max(success_ewma, 0.0), 1.0)
    return round(100.0 * (0.8 * success + 0.2 * latency_factor(latency_ewma_ms)), 2)


def classify_health(score: float, valid_checks: int) -> HealthStatus:
    if valid_checks < 3:
        return HealthStatus.UNKNOWN
    if score >= 70:
        return HealthStatus.HEALTHY
    if score >= 40:
        return HealthStatus.DEGRADED
    return HealthStatus.UNHEALTHY


@dataclass(frozen=True, slots=True)
class HealthUpdate:
    success_ewma: float
    latency_ewma_ms: float | None
    score: float
    status: HealthStatus
    valid_checks: int


def update_health(
    *,
    prior_success_ewma: float | None,
    prior_latency_ewma_ms: float | None,
    prior_valid_checks: int,
    succeeded: bool,
    latency_ms: float | None,
) -> HealthUpdate:
    success = ewma(prior_success_ewma, 1.0 if succeeded else 0.0, SUCCESS_ALPHA)
    latency = prior_latency_ewma_ms
    if succeeded and latency_ms is not None:
        latency = ewma(prior_latency_ewma_ms, max(0.0, latency_ms), LATENCY_ALPHA)
    valid_checks = prior_valid_checks + 1
    score = health_score(success, latency)
    return HealthUpdate(success, latency, score, classify_health(score, valid_checks), valid_checks)
