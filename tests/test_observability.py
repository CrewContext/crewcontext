"""Tests for Phase 2 observability features."""
import pytest
from datetime import datetime, timezone
import json

from crewcontext.logging_config import (
    setup_logging, get_logger, JSONFormatter, TextFormatter, LogContext
)
from crewcontext.health import (
    HealthChecker, HealthCheckResult, HealthStatus,
    get_health_checker, add_health_check, get_health_status
)
from crewcontext.metrics import MetricsCollector


class TestJSONFormatter:
    """Test structured JSON logging."""

    def test_json_format_basic(self):
        """Test basic JSON log output."""
        formatter = JSONFormatter(service_name="test-service")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        log_data = json.loads(output)

        assert log_data["message"] == "Test message"
        assert log_data["service"] == "test-service"
        assert log_data["level"] == "INFO"
        assert "timestamp" in log_data

    def test_json_format_with_extra(self):
        """Test JSON logging with extra fields."""
        formatter = JSONFormatter(service_name="test")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Event processed",
            args=(),
            exc_info=None,
        )
        record.event_id = "abc123"
        record.agent_id = "agent-1"

        output = formatter.format(record)
        log_data = json.loads(output)

        assert log_data["event_id"] == "abc123"
        assert log_data["agent_id"] == "agent-1"

    def test_text_format(self):
        """Test human-readable text format."""
        formatter = TextFormatter(service_name="test")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)

        assert "INFO" in output
        assert "Test message" in output


class TestHealthChecker:
    """Test health check functionality."""

    def test_healthy_check(self):
        """Test successful health check."""
        checker = HealthChecker()
        checker.add_check("test", lambda: True)

        status = checker.get_status()
        assert status.healthy is True
        assert len(status.checks) == 1
        assert status.checks[0].healthy is True

    def test_unhealthy_check(self):
        """Test failed health check."""
        checker = HealthChecker()
        checker.add_check("test", lambda: False)

        status = checker.get_status()
        assert status.healthy is False

    def test_non_required_check_failure(self):
        """Test that non-required check failure doesn't affect overall health."""
        checker = HealthChecker()
        checker.add_check("required", lambda: True, required=True)
        checker.add_check("optional", lambda: False, required=False)

        status = checker.get_status()
        assert status.healthy is True  # Optional failure doesn't affect health

    def test_check_with_exception(self):
        """Test health check that raises exception."""
        checker = HealthChecker()
        checker.add_check("failing", lambda: 1 / 0)

        status = checker.get_status()
        assert status.healthy is False
        assert status.checks[0].error == "ZeroDivisionError"

    def test_uptime_tracking(self):
        """Test uptime is tracked."""
        checker = HealthChecker()
        status = checker.get_status()
        assert status.uptime_seconds >= 0

    def test_health_check_latency(self):
        """Test latency is measured."""
        checker = HealthChecker()
        checker.add_check("slow", lambda: time.sleep(0.01) or True)

        status = checker.get_status()
        assert status.checks[0].latency_ms >= 10  # At least 10ms

    def test_default_health_checker(self):
        """Test default health checker singleton."""
        checker1 = get_health_checker()
        checker2 = get_health_checker()
        assert checker1 is checker2

    def test_add_health_check_helper(self):
        """Test add_health_check helper function."""
        # Reset default checker
        import crewcontext.health
        crewcontext.health._default_checker = None

        add_health_check("test", lambda: True)
        status = get_health_status()
        assert status["healthy"] is True


class TestMetricsPrometheus:
    """Test Prometheus metrics export."""

    def test_prometheus_counter_export(self):
        """Test counter export to Prometheus format."""
        metrics = MetricsCollector(service_name="test")
        metrics.increment("events.emitted")
        metrics.increment("events.emitted")

        output = metrics.to_prometheus()

        assert "crewcontext_events_emitted" in output
        assert "TYPE crewcontext_events_emitted counter" in output

    def test_prometheus_histogram_export(self):
        """Test histogram export to Prometheus format."""
        metrics = MetricsCollector(service_name="test")
        metrics.histogram("emit.latency_ms", 10.5)
        metrics.histogram("emit.latency_ms", 20.0)
        metrics.histogram("emit.latency_ms", 30.5)

        output = metrics.to_prometheus()

        assert "crewcontext_emit_latency_ms" in output
        assert "TYPE crewcontext_emit_latency_ms summary" in output
        assert "crewcontext_emit_latency_ms_count 3" in output

    def test_prometheus_gauge_export(self):
        """Test gauge export to Prometheus format."""
        metrics = MetricsCollector(service_name="test")
        metrics.set_gauge("connections.active", 5)

        output = metrics.to_prometheus()

        assert "crewcontext_connections_active 5" in output
        assert "TYPE crewcontext_connections_active gauge" in output

    def test_prometheus_name_conversion(self):
        """Test metric name conversion to Prometheus format."""
        metrics = MetricsCollector(service_name="test")

        # Test various name formats
        assert metrics._prometheus_name("test.events") == "crewcontext_events"
        assert metrics._prometheus_name("emit.latency_ms") == "crewcontext_emit_latency_ms"

    def test_prometheus_output_valid(self):
        """Test that Prometheus output is parseable."""
        metrics = MetricsCollector(service_name="test")
        metrics.increment("success")
        metrics.histogram("latency", 100)
        metrics.set_gauge("active", 5)

        output = metrics.to_prometheus()

        # Each line should be either a comment, TYPE declaration, or metric
        for line in output.split("\n"):
            line = line.strip()
            if line:
                assert (
                    line.startswith("#") or
                    " " in line or  # Metric line: "name value"
                    "{" in line  # Metric with labels
                )


class TestEventReplay:
    """Test event replay functionality (requires database)."""

    @pytest.mark.skip(reason="Requires PostgreSQL")
    def test_replay_events(self, pg_store, unique_process_id):
        """Test event replay."""
        from crewcontext.context import ProcessContext

        with ProcessContext(process_id=unique_process_id, agent_id="test") as ctx:
            # Emit some events
            ctx.emit("test.event", {"data": 1})
            ctx.emit("test.event", {"data": 2})

            # Replay
            stats = ctx.replay_events()
            assert stats["events_replayed"] == 2
            assert stats["errors"] == 0

    @pytest.mark.skip(reason="Requires PostgreSQL")
    def test_rebuild_entity_state(self, pg_store, unique_process_id):
        """Test entity state rebuild."""
        from crewcontext.context import ProcessContext

        with ProcessContext(process_id=unique_process_id, agent_id="test") as ctx:
            # Emit events for entity
            ctx.emit("invoice.received", {"amount": 100, "vendor": "V1"}, entity_id="inv-1")
            ctx.emit("invoice.validated", {"valid": True}, entity_id="inv-1")

            # Rebuild state
            state = ctx.rebuild_entity_state("inv-1")
            assert state["version"] == 2
            assert state["entity_id"] == "inv-1"

    @pytest.mark.skip(reason="Requires PostgreSQL")
    def test_export_events_json(self, pg_store, unique_process_id):
        """Test event export to JSON."""
        from crewcontext.context import ProcessContext

        with ProcessContext(process_id=unique_process_id, agent_id="test") as ctx:
            ctx.emit("test.event", {"data": 1})

            output = ctx.export_events(format="json")
            events = json.loads(output)

            assert len(events) == 1
            assert events[0]["data"] == {"data": 1}

    @pytest.mark.skip(reason="Requires PostgreSQL")
    def test_export_events_ndjson(self, pg_store, unique_process_id):
        """Test event export to NDJSON."""
        from crewcontext.context import ProcessContext

        with ProcessContext(process_id=unique_process_id, agent_id="test") as ctx:
            ctx.emit("test.event", {"data": 1})
            ctx.emit("test.event", {"data": 2})

            output = ctx.export_events(format="ndjson")
            lines = output.strip().split("\n")

            assert len(lines) == 2
            json.loads(lines[0])  # Should be valid JSON
            json.loads(lines[1])


# Import logging for tests
import logging

# Import time for latency tests
import time
