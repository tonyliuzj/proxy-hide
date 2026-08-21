from __future__ import annotations

from app.domain.scoring import classify_health, health_score, latency_factor, update_health
from app.models import HealthStatus


def test_latency_factor_boundaries_and_score() -> None:
    assert latency_factor(100) == 1
    assert latency_factor(5_000) == 0
    assert latency_factor(10_000) == 0
    assert health_score(1, 200) == 100
    assert health_score(0, 200) == 20


def test_health_stays_unknown_until_three_checks() -> None:
    state = None
    success = None
    latency = None
    checks = 0
    for _ in range(3):
        state = update_health(
            prior_success_ewma=success,
            prior_latency_ewma_ms=latency,
            prior_valid_checks=checks,
            succeeded=True,
            latency_ms=250,
        )
        success, latency, checks = state.success_ewma, state.latency_ewma_ms, state.valid_checks
    assert state is not None
    assert state.status == HealthStatus.HEALTHY
    assert state.score > 90


def test_classification_thresholds() -> None:
    assert classify_health(99, 2) == HealthStatus.UNKNOWN
    assert classify_health(70, 3) == HealthStatus.HEALTHY
    assert classify_health(40, 3) == HealthStatus.DEGRADED
    assert classify_health(39.99, 3) == HealthStatus.UNHEALTHY
