"""Metrics collection for CrewContext.

Provides counters, histograms, and failure tracking for observability.

Usage:
    metrics = MetricsCollector()
    metrics.increment("events.emitted", {"type": "invoice.received"})
    metrics.histogram("emit.latency_ms", 42.5)
    metrics.record_failure("neo4j.project", event_id, error)
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class FailedOperation:
    """Record of a failed operation for tracking/alerting."""
    operation: str
    identifier: str  # event_id, entity_id, etc.
    error: str
    error_type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    retry_count: int = 0


class MetricsCollector:
    """Collects and exposes metrics for observability.

    Thread-safe for basic operations. For production use,
    integrate with Prometheus, Datadog, or similar.
    """

    def __init__(self, service_name: str = "crewcontext"):
        self.service_name = service_name
        self._counters: Dict[str, int] = defaultdict(int)
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._gauges: Dict[str, float] = {}
        self._failures: List[FailedOperation] = []
        self._last_success: Dict[str, datetime] = {}
        self._start_time = datetime.now(timezone.utc)

    # -- counters ------------------------------------------------------------

    def increment(self, name: str, tags: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter metric.

        Args:
            name: Metric name (e.g. "events.emitted").
            tags: Optional labels for segmentation.
        """
        key = self._make_key(name, tags)
        self._counters[key] += 1
        log.debug("Metric: %s = %d", key, self._counters[key])

    def get_counter(self, name: str, tags: Optional[Dict[str, str]] = None) -> int:
        """Get current counter value."""
        key = self._make_key(name, tags)
        return self._counters.get(key, 0)

    # -- histograms ----------------------------------------------------------

    def histogram(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Record a histogram value (e.g. latency).

        Args:
            name: Metric name (e.g. "emit.latency_ms").
            value: Numeric value to record.
            tags: Optional labels for segmentation.
        """
        key = self._make_key(name, tags)
        self._histograms[key].append(value)
        # Keep only last 1000 values to prevent memory growth
        if len(self._histograms[key]) > 1000:
            self._histograms[key] = self._histograms[key][-1000:]

    def get_histogram_stats(
        self, name: str, tags: Optional[Dict[str, str]] = None
    ) -> Dict[str, float]:
        """Get statistics for a histogram metric."""
        key = self._make_key(name, tags)
        values = self._histograms.get(key, [])
        if not values:
            return {"count": 0, "min": 0, "max": 0, "avg": 0, "p50": 0, "p95": 0, "p99": 0}

        sorted_values = sorted(values)
        count = len(sorted_values)
        return {
            "count": count,
            "min": sorted_values[0],
            "max": sorted_values[-1],
            "avg": sum(sorted_values) / count,
            "p50": sorted_values[int(count * 0.5)],
            "p95": sorted_values[min(int(count * 0.95), count - 1)],
            "p99": sorted_values[min(int(count * 0.99), count - 1)],
        }

    # -- gauges --------------------------------------------------------------

    def set_gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge metric (instant value)."""
        key = self._make_key(name, tags)
        self._gauges[key] = value

    def get_gauge(self, name: str, tags: Optional[Dict[str, str]] = None) -> Optional[float]:
        """Get current gauge value."""
        key = self._make_key(name, tags)
        return self._gauges.get(key)

    # -- failure tracking ----------------------------------------------------

    def record_failure(
        self,
        operation: str,
        identifier: str,
        error: Exception,
        retry_count: int = 0,
    ) -> None:
        """Record a failed operation for tracking/alerting.

        Args:
            operation: Operation name (e.g. "neo4j.project").
            identifier: Related ID (event_id, entity_id, etc.).
            error: The exception that was raised.
            retry_count: Number of retry attempts made.
        """
        failure = FailedOperation(
            operation=operation,
            identifier=identifier,
            error=str(error),
            error_type=type(error).__name__,
            retry_count=retry_count,
        )
        self._failures.append(failure)
        # Keep only last 100 failures
        if len(self._failures) > 100:
            self._failures = self._failures[-100:]

        log.warning(
            "Operation failed: %s (id=%s, error=%s)",
            operation, identifier, type(error).__name__,
        )

    def get_recent_failures(
        self, operation: Optional[str] = None, limit: int = 10
    ) -> List[FailedOperation]:
        """Get recent failures, optionally filtered by operation."""
        failures = self._failures
        if operation:
            failures = [f for f in failures if f.operation == operation]
        return failures[-limit:]

    def get_failure_rate(self, operation: str, window_seconds: int = 300) -> float:
        """Calculate failure rate for an operation over a time window."""
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - window_seconds

        recent = [
            f for f in self._failures
            if f.operation == operation and f.timestamp.timestamp() > cutoff
        ]

        # Get counter for successful operations
        success_key = f"{self.service_name}.{operation}.success"
        successes = self._counters.get(success_key, 0)

        total = len(recent) + successes
        if total == 0:
            return 0.0
        return len(recent) / total

    # -- success tracking ----------------------------------------------------

    def record_success(self, operation: str) -> None:
        """Record a successful operation."""
        key = f"{self.service_name}.{operation}.success"
        self._counters[key] += 1
        self._last_success[operation] = datetime.now(timezone.utc)

    def time_since_last_success(self, operation: str) -> Optional[float]:
        """Get seconds since last successful operation."""
        last = self._last_success.get(operation)
        if last is None:
            return None
        return (datetime.now(timezone.utc) - last).total_seconds()

    # -- utility -------------------------------------------------------------

    def _make_key(self, name: str, tags: Optional[Dict[str, str]] = None) -> str:
        """Create a metric key with optional tags."""
        base = f"{self.service_name}.{name}"
        if tags:
            tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
            return f"{base}{{{tag_str}}}"
        return base

    # -- export --------------------------------------------------------------

    def export(self) -> Dict[str, Any]:
        """Export all metrics for external systems."""
        return {
            "counters": dict(self._counters),
            "histograms": {
                k: self.get_histogram_stats(k.replace(f"{self.service_name}.", "").split("{")[0])
                for k in self._histograms.keys()
            },
            "gauges": dict(self._gauges),
            "recent_failures": [
                {
                    "operation": f.operation,
                    "identifier": f.identifier,
                    "error": f.error,
                    "error_type": f.error_type,
                    "timestamp": f.timestamp.isoformat(),
                    "retry_count": f.retry_count,
                }
                for f in self._failures[-10:]
            ],
            "uptime_seconds": (datetime.now(timezone.utc) - self._start_time).total_seconds(),
        }

    def reset(self) -> None:
        """Reset all metrics (useful for testing)."""
        self._counters.clear()
        self._histograms.clear()
        self._gauges.clear()
        self._failures.clear()
        self._last_success.clear()

    # -- Prometheus export --------------------------------------------------

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus text exposition format.

        Returns:
            Metrics in Prometheus format for scraping.

        Usage:
            # In your HTTP server
            @app.get("/metrics")
            def metrics():
                return Response(ctx.metrics.to_prometheus(), media_type="text/plain")
        """
        lines = []

        # Export counters
        for key, value in self._counters.items():
            metric_name = self._prometheus_name(key)
            lines.append(f"# TYPE {metric_name} counter")
            lines.append(f"{metric_name} {value}")

        # Export histograms with stats
        for key, values in self._histograms.items():
            if not values:
                continue
            metric_name = self._prometheus_name(key)
            stats = self.get_histogram_stats(key.replace(f"{self.service_name}.", "").split("{")[0])

            lines.append(f"# TYPE {metric_name} summary")
            lines.append(f"{metric_name}_count {stats['count']}")
            lines.append(f"{metric_name}_sum {sum(values):.3f}")
            lines.append(f"{metric_name}{{quantile=\"0.5\"}} {stats['p50']:.3f}")
            lines.append(f"{metric_name}{{quantile=\"0.95\"}} {stats['p95']:.3f}")
            lines.append(f"{metric_name}{{quantile=\"0.99\"}} {stats['p99']:.3f}")

        # Export gauges
        for key, value in self._gauges.items():
            metric_name = self._prometheus_name(key)
            lines.append(f"# TYPE {metric_name} gauge")
            lines.append(f"{metric_name} {value}")

        return "\n".join(lines)

    def _prometheus_name(self, name: str) -> str:
        """Convert metric name to Prometheus format.

        Converts:
        - Dots to underscores
        - Removes special characters
        - Ensures valid Prometheus name
        """
        # Remove service prefix if present
        if name.startswith(f"{self.service_name}."):
            name = name[len(self.service_name) + 1:]

        # Replace dots with underscores
        name = name.replace(".", "_")

        # Remove any invalid characters
        name = "".join(c if c.isalnum() or c == "_" else "_" for c in name)

        # Ensure starts with letter
        if name and not name[0].isalpha():
            name = "m_" + name

        return f"crewcontext_{name}"


# -- context manager for timing ----------------------------------------------

class measure_time:
    """Context manager for measuring operation duration.

    Usage:
        with metrics.measure_time("operation.name"):
            do_something()
    """

    def __init__(self, metrics: MetricsCollector, operation: str, tags: Optional[Dict[str, str]] = None):
        self.metrics = metrics
        self.operation = operation
        self.tags = tags
        self.start_time: Optional[float] = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = (time.perf_counter() - self.start_time) * 1000
        self.metrics.histogram(f"{self.operation}.ms", elapsed_ms, self.tags)
        if exc_type is None:
            self.metrics.record_success(self.operation)
        return False  # Don't suppress exceptions
