# CrewContext v0.2.0 Improvements

## Summary

This document summarizes the architectural improvements made to CrewContext since v0.1.0. All changes address critical issues identified in the [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md).

**Status:** ✅ Phase 1 (Stability) + ✅ Phase 2 (Observability) Complete

---

## Phase 2: Observability (NEW)

### 1. Structured JSON Logging ✅

**Problem:** Human-readable logs are hard to parse in production log aggregation systems.

**Solution:** Added JSON-formatted structured logging.

```python
from crewcontext.logging_config import setup_logging, get_logger

# Setup at application start
setup_logging(level="INFO", json_format=True, service_name="my-service")

# Use in code
log = get_logger(__name__)
log.info("Event emitted", extra={"event_id": "abc123", "agent_id": "agent-1"})
```

**Output:**
```json
{
  "timestamp": "2026-03-11T22:00:00Z",
  "level": "INFO",
  "logger": "my_module",
  "message": "Event emitted",
  "service": "my-service",
  "event_id": "abc123",
  "agent_id": "agent-1"
}
```

### 2. Health Check API ✅

**Problem:** No Kubernetes-style health endpoints for orchestration.

**Solution:** Added comprehensive health checking with liveness, readiness, and startup probes.

```python
from crewcontext import HealthChecker, ProcessContext

checker = HealthChecker()

# Add checks
checker.add_check("postgres", lambda: pg_store.connect() or True)
checker.add_check("neo4j", lambda: projector.available, required=False)

# Get status
status = checker.get_status()
print(f"Healthy: {status.healthy}")
print(f"Uptime: {status.uptime_seconds}s")

# For Kubernetes
is_live = checker.is_live()      # Liveness probe
is_ready = checker.is_ready()    # Readiness probe
```

**Kubernetes Integration:**
```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 8080
readinessProbe:
  httpGet:
    path: /health/ready
    port: 8080
```

### 3. Event Replay API ✅

**Problem:** No way to rebuild state from events or debug issues by replaying history.

**Solution:** Added event replay and state rebuild capabilities.

```python
with ProcessContext(process_id="p1", agent_id="agent-1") as ctx:
    # Replay events with custom handler
    def handler(event):
        print(f"Event: {event['type']}")
    
    stats = ctx.replay_events(
        entity_id="inv-123",
        replay_handler=handler
    )
    print(f"Replayed {stats['events_replayed']} events")
    
    # Rebuild entity state from events
    state = ctx.rebuild_entity_state("inv-123")
    print(f"Entity version: {state['version']}")
    print(f"Attributes: {state['attributes']}")
    
    # Export events for backup
    json_export = ctx.export_events(format="json")
    ndjson_export = ctx.export_events(format="ndjson")
```

### 4. Prometheus Metrics Export ✅

**Problem:** Metrics were in-memory only, no integration with monitoring systems.

**Solution:** Added Prometheus text exposition format export.

```python
from crewcontext import ProcessContext

with ProcessContext(process_id="p1", agent_id="agent-1") as ctx:
    ctx.emit("invoice.received", {"amount": 5000})
    
    # Export to Prometheus format
    prometheus_metrics = ctx.metrics.to_prometheus()
    
# Example output:
# TYPE crewcontext_emit_success counter
# crewcontext_emit_success 42
# TYPE crewcontext_emit_latency_ms summary
# crewcontext_emit_latency_ms_count 42
# crewcontext_emit_latency_ms_sum 1234.567
# crewcontext_emit_latency_ms{quantile="0.5"} 25.5
# crewcontext_emit_latency_ms{quantile="0.95"} 120.0
```

**FastAPI Integration:**
```python
from fastapi import Response

@app.get("/metrics")
def metrics():
    return Response(
        ctx.metrics.to_prometheus(),
        media_type="text/plain"
    )
```

---

## Phase 1: Stability

**Problem:** Network retries could cause duplicate events, breaking event sourcing guarantees.

**Solution:** Added idempotency key support to prevent duplicate event emission.

### Changes

**New Database Table:**
```sql
CREATE TABLE idempotency_keys (
    process_id      TEXT        NOT NULL,
    idempotency_key TEXT        NOT NULL,
    event_id        TEXT        NOT NULL REFERENCES events(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (process_id, idempotency_key)
);
```

**API Changes:**
```python
from crewcontext import ProcessContext

with ProcessContext(process_id="p1", agent_id="agent-1") as ctx:
    # First emission
    event1 = ctx.emit(
        "invoice.received",
        {"amount": 5000},
        idempotency_key="inv-123-received",  # ← New parameter
    )
    
    # Duplicate emission with same key returns original event
    event2 = ctx.emit(
        "invoice.received",
        {"amount": 5000},
        idempotency_key="inv-123-received",
    )
    
    assert event1.id == event2.id  # Same event returned
```

**Files Modified:**
- `crewcontext/store/postgres.py` — Added `get_event_by_idempotency_key()`, updated `save_event()`
- `crewcontext/store/base.py` — Added abstract method
- `crewcontext/context.py` — Updated `emit()` to check and store idempotency keys

---

## 2. Event Schema Validation with Pydantic ✅

**Problem:** No validation of event data structure — schema drift went undetected.

**Solution:** Added Pydantic-based schema validation with strict mode support.

### Usage

```python
from crewcontext import ProcessContext, EventSchema, ValidationError

# Define your event schema
class InvoiceReceivedEvent(EventSchema):
    invoice_id: str
    vendor_id: str
    amount: float
    currency: str = "USD"
    
    class Config:
        extra = "forbid"  # Reject unknown fields

with ProcessContext(process_id="p1", agent_id="agent-1") as ctx:
    # Register schema
    ctx.register_event_schema("invoice.received", InvoiceReceivedEvent)
    
    # Valid event
    ctx.emit("invoice.received", {
        "invoice_id": "inv-123",
        "vendor_id": "V-100",
        "amount": 5000.0,
    })
    
    # Invalid event - raises ValidationError
    try:
        ctx.emit("invoice.received", {
            "invoice_id": "inv-123",
            # Missing required: vendor_id
            "amount": "not-a-number",  # Wrong type
        })
    except ValidationError as e:
        print(f"Validation failed: {e.errors}")
```

**Files Created:**
- `crewcontext/schema.py` — SchemaRegistry, EventSchema, ValidationError

**Files Modified:**
- `crewcontext/context.py` — Added `register_event_schema()`, `set_schema_strict_mode()`, integrated validation into `emit()`
- `crewcontext/__init__.py` — Exported schema classes
- `pyproject.toml` — Added `pydantic>=2.0` dependency

---

## 3. Neo4j Projector Retry Logic + Metrics ✅

**Problem:** Silent failures in Neo4j projection — graph went stale without alerting.

**Solution:** Added retry logic with exponential backoff, circuit breaker, and metrics collection.

### Features

- **Retry Logic:** 3 retries with exponential backoff (100ms, 200ms, 400ms)
- **Circuit Breaker:** Opens after 5 consecutive failures, resets after 30s
- **Metrics:** Tracks success/failure rates, latency histograms
- **Failure Tracking:** Last 100 failures retained for debugging

### Usage

```python
from crewcontext.context import ProcessContext

with ProcessContext(process_id="p1", agent_id="agent-1") as ctx:
    ctx.emit("invoice.received", {"amount": 5000})
    
    # Access metrics
    metrics = ctx.metrics
    print(f"Events emitted: {metrics.get_counter('emit.success')}")
    print(f"Projection failures: {metrics.get_counter('neo4j_projector.project_event')}")
    
    # Export for monitoring systems
    metrics_export = ctx.get_metrics()
    # Send to Prometheus, Datadog, etc.
```

**Files Modified:**
- `crewcontext/projection/projector.py` — Complete rewrite with retry logic, circuit breaker, metrics
- `crewcontext/metrics.py` — New metrics collection module
- `crewcontext/context.py` — Integrated metrics into ProcessContext

---

## 4. PostgreSQL Connection Retry Logic ✅

**Problem:** Connection failures could hang indefinitely without retry.

**Solution:** Added retry logic with exponential backoff and timeout.

### Features

- **Retries:** 3 attempts with 2^attempt second delays (2s, 4s, 8s)
- **Timeout:** Configurable connection timeout (default: 10s)
- **Metrics:** Connection success/failure tracking

### Configuration

```python
from crewcontext.store.postgres import PostgresStore

store = PostgresStore(
    db_url="postgresql://user:pass@localhost:5432/crewcontext",
    max_retries=3,          # Number of connection attempts
    connect_timeout=10,     # Connection timeout in seconds
)
```

**Files Modified:**
- `crewcontext/store/postgres.py` — Updated `connect()` with retry logic

---

## 5. Metrics Collection Framework ✅

**Problem:** No observability — no way to monitor system health or performance.

**Solution:** Created comprehensive metrics collection framework.

### Metrics Types

- **Counters:** `emit.success`, `emit.idempotent`, `project_event.success`
- **Histograms:** `emit.ms`, `project_event.ms` (latency in milliseconds)
- **Gauges:** For instantaneous values
- **Failure Tracking:** Last 100 failures with error details

### Usage

```python
from crewcontext.metrics import MetricsCollector

metrics = MetricsCollector(service_name="my-service")

# Track operations
metrics.increment("operations.completed", {"status": "success"})
metrics.histogram("operation.latency_ms", 42.5)

# Get statistics
stats = metrics.get_histogram_stats("operation.latency_ms")
# {'count': 100, 'min': 10.5, 'max': 250.0, 'avg': 45.2, 'p50': 40.0, 'p95': 120.0, 'p99': 200.0}

# Export for monitoring
export = metrics.export()
```

**Files Created:**
- `crewcontext/metrics.py` — MetricsCollector, measure_time context manager

---

## 6. Batch Size Limits ✅

**Problem:** No limit on batch event writes — could cause OOM errors.

**Solution:** Added batch size validation with clear error messages.

### Usage

```python
from crewcontext.store.postgres import _MAX_BATCH_SIZE  # = 1000

# This will raise ValueError if > 1000 events
ctx.batch_emit([
    {"event_type": "event", "data": {}}
    for _ in range(2000)
])
# ValueError: Batch size exceeds limit: 2000 > 1000
```

**Files Modified:**
- `crewcontext/store/postgres.py` — Added `_MAX_BATCH_SIZE` constant, validation in `save_events()`

---

## 7. Security Best Practices ✅

**Problem:** Default credentials in examples could be copy-pasted to production.

**Solution:** Updated `.env.example` with security warnings and production guidance.

### Changes

- Clear security warnings at top of file
- `changeme_in_production` placeholders instead of working passwords
- SSL/TLS connection string examples
- Documentation for all configuration options
- Future feature flags documented

**Files Modified:**
- `.env.example` — Complete rewrite with security guidance

---

## 8. Better Debugging with `__repr__` ✅

**Problem:** Hard to debug events/entities in logs without string representations.

**Solution:** Added `__repr__` methods to all core model classes.

### Example Output

```python
>>> event = Event(id="abc123...", type="invoice.received", entity_id="inv-1")
>>> repr(event)
'Event(id=\'abc123...\', type=\'invoice.received\', entity=\'inv-1\')'

>>> entity = Entity(id="inv-1", type="Invoice", version=1, attributes={})
>>> repr(entity)
'Entity(id=\'inv-1\', type=\'Invoice\', version=1)'
```

**Files Modified:**
- `crewcontext/models.py` — Added `__repr__` to Entity, Relation, Event, RoutingDecision

---

## Installation

Update dependencies:

```bash
pip install -e ".[dev]"
```

New dependency:
- `pydantic>=2.0` — For schema validation

---

## Migration Guide

### Database Migration

Run to add new tables:

```bash
crewcontext init-db
```

This will create:
- `idempotency_keys` table
- `events.idempotency_key` column
- New indexes

### Code Changes

**No breaking changes** — all new features are optional:

1. **Idempotency:** Add `idempotency_key` parameter to `emit()` calls where needed
2. **Schema Validation:** Register schemas for event types you want to validate
3. **Metrics:** Access via `ctx.metrics` property

---

## Testing

Run existing tests:

```bash
pytest
```

New test coverage needed for:
- Idempotency key deduplication
- Schema validation errors
- Metrics collection
- Retry logic
- Circuit breaker behavior

---

## Next Steps (v0.2.0 Roadmap)

### Phase 1: Stability ✅ (Complete)
- [x] Idempotency keys
- [x] Schema validation
- [x] Retry logic
- [x] Metrics collection

### Phase 2: Observability (In Progress)
- [ ] Structured JSON logging
- [ ] Health check endpoint
- [ ] Event replay API
- [ ] Prometheus metrics export

### Phase 3: Security
- [ ] Scope-based access control
- [ ] Event encryption at rest
- [ ] Audit logging for queries
- [ ] Secrets management integration

### Phase 4: Integrations
- [ ] CrewAI adapter
- [ ] REST API
- [ ] Webhook emitter
- [ ] CLI export/import commands

---

## Files Changed Summary

### Phase 2 New Files (Observability)
- `crewcontext/logging_config.py` — Structured JSON logging
- `crewcontext/health.py` — Health check API for Kubernetes
- `tests/test_observability.py` — Phase 2 feature tests

### Phase 1 New Files (Stability)
- `crewcontext/schema.py` — Pydantic schema validation
- `crewcontext/metrics.py` — Metrics collection + Prometheus export
- `ARCHITECTURE_REVIEW.md` — Comprehensive architecture review
- `IMPROVEMENTS.md` — This document

### Modified Files
- `crewcontext/context.py` — Event replay API, metrics integration, schema validation, idempotency
- `crewcontext/models.py` — Added `__repr__` methods
- `crewcontext/store/postgres.py` — Idempotency keys, retry logic, batch limits
- `crewcontext/store/base.py` — Added idempotency method
- `crewcontext/projection/projector.py` — Retry logic, circuit breaker, metrics
- `crewcontext/__init__.py` — Exported new classes, version bump to 0.2.0
- `crewcontext/metrics.py` — Added Prometheus export format
- `pyproject.toml` — Added pydantic dependency
- `.env.example` — Security best practices

---

## Contributors

Improvements implemented based on architectural review conducted March 11, 2026.
