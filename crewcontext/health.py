"""Health check API for CrewContext.

Provides Kubernetes-style health endpoints for monitoring and orchestration.

Usage:
    from crewcontext.health import HealthChecker
    
    checker = HealthChecker()
    checker.add_check("postgres", check_postgres)
    checker.add_check("neo4j", check_neo4j)
    
    # Get health status
    status = checker.get_status()
    if status["healthy"]:
        print("All systems operational")
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


@dataclass
class HealthCheckResult:
    """Result of a single health check."""

    name: str
    healthy: bool
    message: str
    latency_ms: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "healthy": self.healthy,
            "message": self.message,
            "latency_ms": round(self.latency_ms, 2),
            "timestamp": self.timestamp.isoformat(),
            "error": self.error,
        }


@dataclass
class HealthStatus:
    """Overall health status of the system."""

    healthy: bool
    checks: List[HealthCheckResult]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    uptime_seconds: float = 0.0
    version: str = "0.2.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "timestamp": self.timestamp.isoformat(),
            "uptime_seconds": round(self.uptime_seconds, 2),
            "version": self.version,
            "checks": [check.to_dict() for check in self.checks],
        }


class HealthChecker:
    """Manages health checks for CrewContext components.

    Supports:
    - Liveness checks: Is the service running?
    - Readiness checks: Is the service ready to accept traffic?
    - Startup checks: Has the service initialized successfully?

    Usage:
        checker = HealthChecker()
        checker.add_check("postgres", lambda: pg_store.connect())
        checker.add_check("neo4j", lambda: projector.connect(), required=False)

        status = checker.get_status()
        print(f"Healthy: {status.healthy}")
    """

    def __init__(self, service_name: str = "crewcontext"):
        self.service_name = service_name
        self._checks: Dict[str, Callable[[], bool]] = {}
        self._required: Dict[str, bool] = {}
        self._last_results: Dict[str, HealthCheckResult] = {}
        self._start_time = datetime.now(timezone.utc)
        self._initialized = False

    def add_check(
        self,
        name: str,
        check_fn: Callable[[], bool],
        required: bool = True,
    ) -> None:
        """Add a health check.

        Args:
            name: Unique name for the check.
            check_fn: Function that returns True if healthy.
            required: If False, failure doesn't affect overall health.
        """
        self._checks[name] = check_fn
        self._required[name] = required

    def remove_check(self, name: str) -> bool:
        """Remove a health check."""
        if name in self._checks:
            del self._checks[name]
            del self._required[name]
            return True
        return False

    def run_check(self, name: str) -> HealthCheckResult:
        """Run a single health check.

        Args:
            name: Name of the check to run.

        Returns:
            HealthCheckResult with status and timing.
        """
        if name not in self._checks:
            return HealthCheckResult(
                name=name,
                healthy=False,
                message=f"Unknown check: {name}",
                latency_ms=0,
                error="Check not found",
            )

        check_fn = self._checks[name]
        start_time = time.perf_counter()

        try:
            result = check_fn()
            latency_ms = (time.perf_counter() - start_time) * 1000

            if result:
                return HealthCheckResult(
                    name=name,
                    healthy=True,
                    message="OK",
                    latency_ms=latency_ms,
                )
            else:
                return HealthCheckResult(
                    name=name,
                    healthy=False,
                    message="Check returned False",
                    latency_ms=latency_ms,
                )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult(
                name=name,
                healthy=False,
                message=str(e),
                latency_ms=latency_ms,
                error=type(e).__name__,
            )

    def get_status(self) -> HealthStatus:
        """Run all health checks and return overall status.

        Returns:
            HealthStatus with results from all checks.
        """
        results: List[HealthCheckResult] = []
        all_healthy = True

        for name in self._checks:
            result = self.run_check(name)
            results.append(result)
            self._last_results[name] = result

            # Check affects overall health only if required
            if self._required.get(name, True) and not result.healthy:
                all_healthy = False

        uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds()

        return HealthStatus(
            healthy=all_healthy,
            checks=results,
            uptime_seconds=uptime,
            version="0.2.0",
        )

    def is_healthy(self) -> bool:
        """Quick check if service is healthy."""
        status = self.get_status()
        return status.healthy

    def is_ready(self) -> bool:
        """Check if service is ready to accept traffic.

        Same as is_healthy(), but can be overridden for more complex logic.
        """
        return self.is_healthy()

    def is_live(self) -> bool:
        """Check if service is alive (liveness probe).

        Always returns True if the process is running.
        """
        return True

    def mark_initialized(self) -> None:
        """Mark service as successfully initialized."""
        self._initialized = True

    def is_initialized(self) -> bool:
        """Check if service has completed initialization."""
        return self._initialized

    def to_dict(self) -> Dict[str, Any]:
        """Get health status as dictionary."""
        return self.get_status().to_dict()

    def to_json(self) -> str:
        """Get health status as JSON string."""
        import json

        return json.dumps(self.to_dict(), indent=2)


# Default health checker instance
_default_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """Get the default health checker instance."""
    global _default_checker
    if _default_checker is None:
        _default_checker = HealthChecker()
    return _default_checker


def add_health_check(
    name: str, check_fn: Callable[[], bool], required: bool = True
) -> None:
    """Add a check to the default health checker."""
    get_health_checker().add_check(name, check_fn, required)


def get_health_status() -> Dict[str, Any]:
    """Get health status from the default checker."""
    return get_health_checker().get_status().to_dict()
