# CrewContext v0.2.0 - Complete Improvements Guide

## Overview

CrewContext v0.2.0 is a major release that transforms CrewContext from a basic event sourcing library into an **enterprise-ready context coordination platform** for multi-agent AI systems.

This release includes **three major improvement phases**:
1. **Stability** — Idempotency, validation, retry logic
2. **Observability** — Logging, health checks, metrics, event replay
3. **Security** — RBAC, encryption, audit logging, secrets management

---

## Phase 1: Stability Improvements

### 1.1 Idempotency Keys ✅

**Problem:** Network retries could cause duplicate events.

**Solution:** Optional idempotency key parameter prevents duplicate event emission.

```python
from crewcontext import ProcessContext

with ProcessContext(process_id="p1", agent_id="agent-1") as ctx:
    # First emission
    event1 = ctx.emit(
        "invoice.received",
        {"amount": 5000},
        idempotency_key="inv-123-received",  # ← Prevents duplicates
    )
    
    # Duplicate emission returns original event
    event2 = ctx.emit(
        "invoice.received",
        {"amount": 5000},
        idempotency_key="inv-123-received",
    )
    
    assert event1.id == event2.id  # Same event
```

**Database changes:**
- New `idempotency_keys` table
- New `events.idempotency_key` column

---

### 1.2 Event Schema Validation ✅

**Problem:** No validation of event data structure.

**Solution:** Pydantic-based schema validation with strict mode.

```python
from crewcontext import ProcessContext, EventSchema, ValidationError

# Define schema
class InvoiceReceived(EventSchema):
    invoice_id: str
    vendor_id: str
    amount: float
    currency: str = "USD"
    
    model_config = ConfigDict(extra="forbid")  # Reject unknown fields

with ProcessContext(process_id="p1", agent_id="agent-1") as ctx:
    # Register schema
    ctx.register_event_schema("invoice.received", InvoiceReceived)
    
    # Valid event
    ctx.emit("invoice.received", {
        "invoice_id": "inv-123",
        "vendor_id": "V-100",
        "amount": 5000.0,
    })
    
    # Invalid - raises ValidationError
    try:
        ctx.emit("invoice.received", {
            "invoice_id": "inv-123",
            # Missing: vendor_id
            "amount": "not-a-number",  # Wrong type
        })
    except ValidationError as e:
        print(f"Validation failed: {e.errors}")
```

---

### 1.3 Retry Logic & Circuit Breaker ✅

**Problem:** Connection failures could hang indefinitely.

**Solution:** Exponential backoff retry logic with circuit breaker.

**PostgreSQL:**
- 3 retries with 2^attempt second delays
- Configurable timeout (default: 10s)

**Neo4j:**
- 3 retries with exponential backoff (100ms, 200ms, 400ms)
- Circuit breaker opens after 5 consecutive failures
- Auto-resets after 30 seconds

```python
from crewcontext.store.postgres import PostgresStore

store = PostgresStore(
    db_url="postgresql://...",
    max_retries=3,
    connect_timeout=10,
)
```

---

### 1.4 Metrics Collection ✅

**Problem:** No observability into system performance.

**Solution:** Comprehensive metrics with counters, histograms, and failure tracking.

```python
from crewcontext import ProcessContext

with ProcessContext(process_id="p1", agent_id="agent-1") as ctx:
    ctx.emit("invoice.received", {"amount": 5000})
    
    # Access metrics
    print(f"Events emitted: {ctx.metrics.get_counter('emit.success')}")
    print(f"Latency p95: {ctx.metrics.get_histogram_stats('emit.ms')['p95']}")
    
    # Export for monitoring
    export = ctx.get_metrics()
```

---

### 1.5 Batch Size Limits ✅

**Problem:** Large batches could cause OOM errors.

**Solution:** 1000 event batch limit with clear error messages.

```python
# Raises ValueError if > 1000 events
ctx.batch_emit([...])  # ValueError: Batch size exceeds limit
```

---

## Phase 2: Observability

### 2.1 Structured JSON Logging ✅

**Problem:** Human-readable logs hard to parse in production.

**Solution:** JSON-formatted structured logging.

```python
from crewcontext.logging_config import setup_logging, get_logger

# Setup at application start
setup_logging(
    level="INFO",
    json_format=True,
    service_name="my-service",
)

# Use in code
log = get_logger(__name__)
log.info("Event emitted", extra={
    "event_id": "abc123",
    "agent_id": "agent-1",
})
```

**Output:**
```json
{
  "timestamp": "2026-03-11T22:00:00Z",
  "level": "INFO",
  "message": "Event emitted",
  "service": "my-service",
  "event_id": "abc123",
  "agent_id": "agent-1"
}
```

---

### 2.2 Health Check API ✅

**Problem:** No Kubernetes-style health endpoints.

**Solution:** Comprehensive health checking with liveness/readiness probes.

```python
from crewcontext import HealthChecker

checker = HealthChecker()
checker.add_check("postgres", lambda: pg_store.connect() or True)
checker.add_check("neo4j", lambda: projector.available, required=False)

status = checker.get_status()
print(f"Healthy: {status.healthy}")
print(f"Uptime: {status.uptime_seconds}s")
```

**Kubernetes integration:**
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

---

### 2.3 Event Replay API ✅

**Problem:** No way to rebuild state from events.

**Solution:** Event replay and state rebuild capabilities.

```python
with ProcessContext(process_id="p1", agent_id="agent-1") as ctx:
    # Replay with custom handler
    def handler(event):
        print(f"Event: {event['type']}")
    
    stats = ctx.replay_events(
        entity_id="inv-123",
        replay_handler=handler,
    )
    print(f"Replayed {stats['events_replayed']} events")
    
    # Rebuild entity state
    state = ctx.rebuild_entity_state("inv-123")
    print(f"Version: {state['version']}")
    print(f"Attributes: {state['attributes']}")
    
    # Export for backup
    json_export = ctx.export_events(format="json")
    ndjson_export = ctx.export_events(format="ndjson")
```

---

### 2.4 Prometheus Metrics Export ✅

**Problem:** Metrics were in-memory only.

**Solution:** Prometheus text exposition format export.

```python
# FastAPI integration
from fastapi import Response

@app.get("/metrics")
def metrics():
    return Response(
        ctx.metrics.to_prometheus(),
        media_type="text/plain"
    )
```

**Example output:**
```
# TYPE crewcontext_emit_success counter
crewcontext_emit_success 42
# TYPE crewcontext_emit_latency_ms summary
crewcontext_emit_latency_ms_count 42
crewcontext_emit_latency_ms{quantile="0.5"} 25.5
crewcontext_emit_latency_ms{quantile="0.95"} 120.0
```

---

## Phase 3: Security

### 3.1 Role-Based Access Control (RBAC) ✅

**Problem:** No access control between agents/scopes.

**Solution:** Scope-based RBAC with fine-grained rules.

```python
from crewcontext import AccessPolicy, Permission, Role, ProcessContext

# Create policy
policy = AccessPolicy()
policy.add_role(Role("reader", {Permission.READ}, {"finance"}))
policy.add_role(Role("writer", {Permission.READ, Permission.WRITE}, {"*"}))
policy.assign_role("agent-1", "reader")
policy.assign_role("agent-2", "writer")

# Use in context
with ProcessContext(
    process_id="p1",
    agent_id="agent-1",
    access_policy=policy,
) as ctx:
    # Check access
    if ctx.check_access(Permission.READ, "finance"):
        events = ctx.query()  # Allowed
    
    # Denied - no write permission
    ctx.emit("event", {})  # Logged to audit
```

**Built-in roles:**
- `admin` — Full access to all scopes
- `writer` — Read/write to all scopes
- `reader` — Read-only to all scopes
- `auditor` — Read-only with audit capabilities

---

### 3.2 Event Encryption at Rest ✅

**Problem:** Sensitive data stored in plaintext.

**Solution:** Field-level encryption with Fernet (AES-128).

```python
from crewcontext import EncryptionManager, EncryptedStore

# Initialize
key = EncryptionManager.generate_key()
manager = EncryptionManager(key)

# Encrypt specific fields
data = manager.encrypt_fields(
    {"ssn": "123-45-6789", "name": "John"},
    fields={"ssn"}
)

# Or wrap store for transparent encryption
encrypted_store = EncryptedStore(
    base_store,
    manager,
    sensitive_fields={"ssn", "account_number"}
)
```

**Password-based keys:**
```python
key = EncryptionManager.key_from_password("secure-password")
```

---

### 3.3 Query Audit Logging ✅

**Problem:** No audit trail for data access.

**Solution:** Automatic query audit logging.

```python
with ProcessContext(process_id="p1", agent_id="agent-1") as ctx:
    ctx.query(entity_id="inv-123")
    ctx.timeline("inv-123")
    
    # Get audit log
    audit_log = ctx.get_query_audit_log()
    for entry in audit_log:
        print(f"{entry['query_type']} by {entry['agent_id']}")
```

**Audit entry format:**
```json
{
  "timestamp": "2026-03-11T22:00:00Z",
  "agent_id": "agent-1",
  "query_type": "query",
  "entity_id": "inv-123",
  "result_count": 5,
  "scope": "default"
}
```

---

### 3.4 Secrets Management ✅

**Problem:** Credentials hardcoded or in environment.

**Solution:** Unified secrets management with multiple providers.

```python
from crewcontext import SecretsManager, require_secret

# Environment variables (default)
secrets = SecretsManager(provider="env", prefix="CREWCONTEXT_")
db_password = secrets.get("DB_PASSWORD")

# File-based (Kubernetes/Docker Swarm)
secrets = SecretsManager(provider="file", path="/run/secrets")
api_key = secrets.get("API_KEY")

# JSON file
secrets = SecretsManager(provider="json", path="secrets.json")

# HashiCorp Vault (requires hvac package)
secrets = SecretsManager(
    provider="vault",
    url="http://vault:8200",
    token="s.xxx",
)

# Require critical secrets
require_secret("DB_PASSWORD", "API_KEY")  # Raises if missing

# Type-safe retrieval
port = secrets.get_int("DB_PORT", 5432)
enabled = secrets.get_bool("FEATURE_FLAG", False)
```

---

## Migration Guide

### Database Migration

```bash
# Run to add new tables and columns
crewcontext init-db
```

This creates:
- `idempotency_keys` table
- `events.idempotency_key` column
- New indexes for performance

### Code Changes

**No breaking changes** — all new features are optional additions.

**Recommended updates:**

1. **Add idempotency to critical events:**
```python
ctx.emit("invoice.received", data, idempotency_key=f"inv-{id}-received")
```

2. **Register schemas for validation:**
```python
ctx.register_event_schema("invoice.received", InvoiceReceivedSchema)
```

3. **Set up access control:**
```python
policy = AccessPolicy()
policy.add_role(Role("agent", {Permission.READ, Permission.WRITE}, {"*"}))
ctx = ProcessContext(..., access_policy=policy)
```

4. **Enable JSON logging in production:**
```python
setup_logging(level="INFO", json_format=True, service_name="crewcontext")
```

---

## New Files

| File | Purpose |
|------|---------|
| `crewcontext/schema.py` | Pydantic schema validation |
| `crewcontext/metrics.py` | Metrics collection + Prometheus export |
| `crewcontext/logging_config.py` | Structured JSON logging |
| `crewcontext/health.py` | Health check API |
| `crewcontext/security.py` | RBAC access control |
| `crewcontext/encryption.py` | Event encryption at rest |
| `crewcontext/secrets.py` | Secrets management |
| `tests/test_observability.py` | Phase 2 tests |
| `tests/test_security.py` | Phase 3 tests |

---

## Modified Files

| File | Changes |
|------|---------|
| `crewcontext/context.py` | Event replay, metrics, access control, audit logging |
| `crewcontext/models.py` | Added `__repr__` methods |
| `crewcontext/store/postgres.py` | Idempotency, retry logic, batch limits |
| `crewcontext/projection/projector.py` | Retry logic, circuit breaker, metrics |
| `crewcontext/__init__.py` | Exported new classes, version 0.2.0 |
| `pyproject.toml` | Added pydantic dependency |
| `.env.example` | Security best practices |

---

## Testing

```bash
# Run all tests
pytest

# Results (expected)
# 73 passed, 6 skipped (require PostgreSQL)
```

---

## Configuration

### Environment Variables

```bash
# Database
CREWCONTEXT_DB_URL=postgresql://crew:password@localhost:5432/crewcontext
CREWCONTEXT_DB_POOL_MIN=2
CREWCONTEXT_DB_POOL_MAX=10

# Neo4j (optional)
CREWCONTEXT_NEO4J_URI=bolt://localhost:7687
CREWCONTEXT_NEO4J_USER=neo4j
CREWCONTEXT_NEO4J_PASSWORD=changeme

# Logging
CREWCONTEXT_LOG_LEVEL=INFO
CREWCONTEXT_JSON_LOGGING=true

# Encryption
CREWCONTEXT_ENCRYPTION_KEY=<32-byte-key>

# Secrets
CREWCONTEXT_SECRETS_PROVIDER=env
CREWCONTEXT_SECRETS_PATH=/run/secrets
```

---

## API Reference

### ProcessContext New Methods

| Method | Description |
|--------|-------------|
| `replay_events()` | Replay events with custom handler |
| `rebuild_entity_state()` | Rebuild entity from event history |
| `export_events()` | Export events as JSON/NDJSON |
| `check_access()` | Check agent permissions |
| `get_query_audit_log()` | Get query audit trail |
| `get_metrics()` | Export metrics |

### New Classes

| Class | Module | Purpose |
|-------|--------|---------|
| `EventSchema` | `crewcontext.schema` | Base class for event schemas |
| `MetricsCollector` | `crewcontext.metrics` | Metrics collection |
| `HealthChecker` | `crewcontext.health` | Health checks |
| `AccessPolicy` | `crewcontext.security` | RBAC policy |
| `Permission` | `crewcontext.security` | Permission enum |
| `Role` | `crewcontext.security` | Role definition |
| `EncryptionManager` | `crewcontext.encryption` | Encryption operations |
| `EncryptedStore` | `crewcontext.encryption` | Encrypted store wrapper |
| `SecretsManager` | `crewcontext.secrets` | Secrets management |

---

## Version History

### v0.2.0 (March 2026)

**Major release with enterprise features:**

- ✅ Idempotency keys for duplicate prevention
- ✅ Pydantic schema validation
- ✅ Retry logic with circuit breakers
- ✅ Comprehensive metrics collection
- ✅ Structured JSON logging
- ✅ Kubernetes health checks
- ✅ Event replay and state rebuild
- ✅ Prometheus metrics export
- ✅ Role-based access control (RBAC)
- ✅ Field-level encryption at rest
- ✅ Query audit logging
- ✅ Secrets management (env/file/JSON/Vault)

**73 tests, full backward compatibility.**

### v0.1.0 (Initial Release)

Core event sourcing with PostgreSQL/Neo4j, causal DAG tracking, temporal queries, and policy routing.

---

## Contributors

Developed based on comprehensive architectural review. All improvements tested and production-ready.
