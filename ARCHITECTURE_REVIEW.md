# CrewContext Architecture Review

**Version:** 0.1.0  
**Date:** March 11, 2026  
**Reviewer:** AI Code Analyst

---

## Executive Summary

CrewContext v0.1.0 is a **solid foundation** for auditable multi-agent context management. The architecture demonstrates strong understanding of event sourcing principles, causal tracking, and separation of concerns. However, several architectural gaps prevent enterprise readiness.

### Overall Assessment

| Category | Rating | Notes |
|----------|--------|-------|
| Core Architecture | ✅ Excellent | Clean event sourcing, proper immutability |
| Data Models | ✅ Excellent | Immutable, validated, timezone-aware |
| Storage Layer | ✅ Very Good | Connection pooling, atomic writes |
| API Design | ✅ Very Good | Intuitive ProcessContext interface |
| Error Handling | ⚠️ Needs Work | Silent failures in projector |
| Observability | ❌ Missing | No logging configuration, metrics, or tracing |
| Security | ❌ Missing | No auth, encryption, or access control |
| Testing | ✅ Good | 44 tests, good coverage of core logic |
| Documentation | ⚠️ Basic | API reference needed |

---

## 1. Architectural Strengths

### 1.1 Event Sourcing Implementation ✅

```python
# Events are append-only, immutable facts
@dataclass(frozen=True)
class Event:
    id: str
    type: str
    process_id: str
    data: Dict[str, Any]
    agent_id: str
    parent_ids: Tuple[str, ...] = ()  # Causal DAG
```

**What's great:**
- Immutable dataclasses (`frozen=True`)
- Timezone-aware timestamps (never naive)
- Causal DAG via `parent_ids` tuple
- Proper validation in `__post_init__`

### 1.2 Separation of Concerns ✅

```
ProcessContext (API) → Store (PostgreSQL) → Truth
                   → Projector (Neo4j) → Graph View
                   → Router (Policy) → Decisions
```

**What's great:**
- Abstract `Store` base class enables backend swaps
- Neo4j is optional, degrades gracefully
- Router is in-process, no external dependencies

### 1.3 Connection Pooling ✅

```python
self._pool = ConnectionPool(
    self.db_url,
    min_size=self._min_pool,
    max_size=self._max_pool,
)
```

**What's great:**
- Uses `psycopg_pool` for production readiness
- Configurable pool sizes
- Proper cleanup on `close()`

### 1.4 Causal DAG Tracking ✅

```python
# Parent → Child relationships stored explicitly
INSERT INTO causal_links (parent_event_id, child_event_id)
VALUES (%s, %s)
```

**What's great:**
- Explicit DAG edges, not inferred
- Bidirectional queries (parents/children)
- Neo4j projection for graph traversal

---

## 2. Critical Issues (Must Fix Before v0.2.0)

### 2.1 Silent Failures in Neo4j Projector 🚨

**File:** `crewcontext/projection/projector.py`

```python
def project_event(self, event: Event) -> bool:
    if not self._available:
        return False
    try:
        self.store.create_event_node(...)
        return True
    except Exception:
        log.exception("Failed to project event %s to Neo4j", event.id[:8])
        return False  # ← Silent failure!
```

**Problem:**
- Events are lost in Neo4j with no alerting
- No retry mechanism
- No dead-letter queue for failed projections
- System appears healthy while graph is stale

**Impact:** High — Graph queries return incomplete data

**Fix:**
```python
class ProjectionMetrics:
    def __init__(self):
        self.failed_projections: list[FailedProjection] = []
        self.last_success: datetime | None = None
    
    def record_failure(self, event: Event, error: Exception):
        self.failed_projections.append(
            FailedProjection(event, error, datetime.now(timezone.utc))
        )
        # Alert if > N failures or > M minutes since last success

def project_event(self, event: Event, retry: int = 3) -> bool:
    for attempt in range(retry):
        try:
            self.store.create_event_node(...)
            self.metrics.record_success()
            return True
        except Exception as e:
            self.metrics.record_failure(event, e)
            if attempt == retry - 1:
                raise  # Or send to dead-letter queue
```

---

### 2.2 No Idempotency Protection 🚨

**File:** `crewcontext/context.py`

```python
def emit(self, event_type: str, data: Dict[str, Any], ...) -> Event:
    event = Event(...)
    self._store.save_event(event)  # ← What if called twice?
```

**Problem:**
- Network retries can cause duplicate events
- No idempotency key support
- `ON CONFLICT (id) DO NOTHING` only helps if same UUID generated (impossible)

**Impact:** High — Duplicate events break event sourcing guarantees

**Fix:**
```python
def emit(
    self,
    event_type: str,
    data: Dict[str, Any],
    idempotency_key: Optional[str] = None,  # ← New parameter
    ...
) -> Event:
    # Check if already processed
    existing = self._store.get_by_idempotency_key(
        self.process_id, idempotency_key
    )
    if existing:
        return existing  # Return original event
    
    event = Event(...)
    self._store.save_event(event, idempotency_key=idempotency_key)
```

**Schema change:**
```sql
CREATE TABLE IF NOT EXISTS idempotency_keys (
    process_id  TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    event_id    TEXT NOT NULL REFERENCES events(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (process_id, idempotency_key)
);
```

---

### 2.3 No Event Schema Validation 🚨

**File:** `crewcontext/context.py`

```python
e1 = ctx.emit("invoice.received", {"amount": 5000}, entity_id="inv-1")
# ← What if "amount" is string? Missing required fields?
```

**Problem:**
- Event `data` is `Dict[str, Any]` — no validation
- Schema drift goes undetected
- Downstream consumers break silently

**Impact:** High — Data quality issues, broken integrations

**Fix:**
```python
from pydantic import BaseModel, Field

class InvoiceReceivedEvent(BaseModel):
    invoice_id: str
    vendor_id: str
    amount: float = Field(gt=0)
    currency: str
    
    class Config:
        extra = "forbid"  # Reject unknown fields

# Register schemas
ctx.register_event_schema("invoice.received", InvoiceReceivedEvent)

# Validate on emit
def emit(self, event_type: str, data: Dict[str, Any], ...):
    schema = self._event_schemas.get(event_type)
    if schema:
        validated = schema(**data)  # Raises ValidationError
        data = validated.dict()
    ...
```

---

### 2.4 Missing Observability 🚨

**Current logging:**
```python
log.info("PostgresStore connected (pool %d–%d)", self._min_pool, self._max_pool)
log.debug("Emitted: %s (type=%s, entity=%s)", event.id[:8], event_type, entity_id)
```

**Problems:**
- No structured logging (JSON format)
- No log levels configuration
- No metrics (events/sec, latency, error rates)
- No distributed tracing (OpenTelemetry)
- No health check endpoint

**Fix:**
```python
# Add metrics collector
class MetricsCollector:
    def __init__(self):
        self.counters: Dict[str, int] = defaultdict(int)
        self.histograms: Dict[str, list[float]] = defaultdict(list)
    
    def increment(self, name: str, tags: Dict[str, str] = None):
        key = f"{name}{tags or ''}"
        self.counters[key] += 1
    
    def histogram(self, name: str, value: float):
        self.histograms[name].append(value)
        # Export to Prometheus, Datadog, etc.

# Add to ProcessContext
def emit(self, ...):
    start = time.perf_counter()
    try:
        event = Event(...)
        self._store.save_event(event)
        self.metrics.increment("events.emitted", {"type": event_type})
    except Exception as e:
        self.metrics.increment("events.failed", {"type": event_type})
        raise
    finally:
        self.metrics.histogram("emit.latency_ms", (time.perf_counter() - start) * 1000)
```

---

### 2.5 No Access Control / Security 🔒

**Problem:**
- Any agent can access any `process_id`
- No authentication for database connections
- No encryption for sensitive event data
- No audit log for who accessed what

**Impact:** Critical for enterprise/regulated deployments

**Fix:**
```python
class AccessControl:
    def __init__(self, policy: AccessPolicy):
        self.policy = policy
    
    def can_emit(self, agent_id: str, event_type: str, scope: str) -> bool:
        return self.policy.check(agent_id, "emit", event_type, scope)
    
    def can_query(self, agent_id: str, process_id: str) -> bool:
        return self.policy.check(agent_id, "query", process_id)

# Add encryption for sensitive fields
from cryptography.fernet import Fernet

class EncryptedStore(Store):
    def __init__(self, inner_store: Store, encryption_key: bytes):
        self._inner = inner_store
        self._cipher = Fernet(encryption_key)
    
    def save_event(self, event: Event) -> None:
        if event.metadata.get("sensitive"):
            event.data = self._encrypt(event.data)
        self._inner.save_event(event)
```

---

## 3. Moderate Issues (Should Fix)

### 3.1 Connection Error Handling

**File:** `crewcontext/store/postgres.py`

```python
def connect(self) -> None:
    if self._pool is not None:
        return
    self._pool = ConnectionPool(self.db_url, ...)  # ← Can hang indefinitely
```

**Problem:**
- No connection timeout
- No retry logic
- No circuit breaker

**Fix:**
```python
def connect(self) -> None:
    if self._pool is not None:
        return
    
    for attempt in range(3):
        try:
            self._pool = ConnectionPool(
                self.db_url,
                min_size=self._min_pool,
                max_size=self._max_pool,
                kwargs={"row_factory": dict_row},
                open=True,
                timeout=10,  # seconds
            )
            return
        except psycopg.OperationalError as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)  # Exponential backoff
```

---

### 3.2 Hardcoded Database Credentials

**File:** `docker-compose.yml`

```yaml
environment:
  POSTGRES_USER: crew
  POSTGRES_PASSWORD: crew  # ← Default password in example
```

**Problem:**
- Default credentials in examples get copy-pasted to production
- No secrets management guidance

**Fix:**
```yaml
environment:
  POSTGRES_USER: ${CREWCONTEXT_DB_USER:-crew}
  POSTGRES_PASSWORD: ${CREWCONTEXT_DB_PASSWORD:?Error: Set DB_PASSWORD}
```

Add to `.env.example`:
```bash
CREWCONTEXT_DB_USER=crew
CREWCONTEXT_DB_PASSWORD=changeme_in_production
CREWCONTEXT_DB_URL=postgresql://crew:changeme_in_production@localhost:5432/crewcontext
```

---

### 3.3 Neo4j Relationship Type Sanitization

**File:** `crewcontext/projection/neo4j.py`

```python
safe_type = "".join(
    c if c.isalnum() or c == "_" else "_"
    for c in rel_type.upper()
)
```

**Problem:**
- Silent data corruption: `"BELONGS_TO@2024"` → `"BELONGS_TO_2024"`
- No validation warning

**Fix:**
```python
def _sanitize_rel_type(self, rel_type: str) -> str:
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in rel_type.upper())
    if safe != rel_type.upper():
        log.warning(
            "Relation type sanitized: %s → %s",
            rel_type, safe
        )
    if not safe[0].isalpha():
        raise ValueError(
            f"Relationship type must start with letter: {rel_type}"
        )
    return safe
```

---

### 3.4 No Event Replay / State Rebuild

**Missing feature:** Cannot rebuild entity state from events

**Use case:**
- Debugging: "What was the state at 2pm?"
- Migration: "Rebuild all entities with new schema"
- Testing: "Replay production events in staging"

**Implementation:**
```python
class ProcessContext:
    def rebuild_entity(self, entity_id: str, as_of: datetime = None) -> Entity:
        """Rebuild entity state by replaying events."""
        events = self.timeline(entity_id, as_of=as_of)
        
        state = {}
        for event in events:
            state = self._apply_event(state, event)
        
        return Entity(
            id=entity_id,
            type=state.get("type", "Unknown"),
            attributes=state,
            version=len(events),
        )
    
    def _apply_event(self, state: dict, event: dict) -> dict:
        """Apply event to state (event sourcing reducer)."""
        if event["type"] == "invoice.received":
            state["amount"] = event["data"]["amount"]
            state["vendor_id"] = event["data"]["vendor_id"]
        elif event["type"] == "invoice.validated":
            state["validation_status"] = event["data"]["validation_status"]
        # ... etc
        return state
```

---

### 3.5 Limited Query Capabilities

**Current:**
```python
ctx.query(entity_id="inv-1", event_type="invoice.*", limit=100)
```

**Missing:**
- Full-text search in event data
- Aggregations (COUNT, SUM, AVG)
- Pattern matching ("find invoices where amount > 1000 AND vendor mismatch")

**Fix:**
```python
def search_events(
    self,
    query: str,  # Full-text search
    aggregations: Optional[List[str]] = None,  # ["COUNT", "SUM(amount)"]
    group_by: Optional[str] = None,
) -> Union[List[Dict], Dict[str, Any]]:
    ...

# Usage
results = ctx.search_events(
    query="vendor_mismatch",
    aggregations=["COUNT", "SUM(amount)"],
    group_by="validation_status"
)
```

---

## 4. Minor Issues (Nice to Fix)

### 4.1 Inconsistent Error Messages

```python
# models.py
raise ValueError("Entity.id cannot be empty")
raise ValueError("Entity.type cannot be empty")

# But in context.py, no validation on process_id before passing to store
```

**Fix:** Add validation at API boundary, not just in models

---

### 4.2 No Context Timeout

```python
with ProcessContext(...) as ctx:
    # What if this hangs?
    ctx.emit(...)
```

**Fix:**
```python
with ProcessContext(..., timeout=30) as ctx:  # seconds
    ...
```

---

### 4.3 Missing `__repr__` Methods

```python
@dataclass(frozen=True)
class Event:
    ...
    # No __repr__ — hard to debug in logs
```

**Fix:**
```python
def __repr__(self):
    return f"Event(id={self.id[:8]}, type={self.type}, entity={self.entity_id})"
```

---

### 4.4 No Batch Size Limits

```python
def save_events(self, events: Sequence[Event]) -> None:
    # What if events has 1M items?
```

**Fix:**
```python
MAX_BATCH_SIZE = 1000

def save_events(self, events: Sequence[Event]) -> None:
    if len(events) > MAX_BATCH_SIZE:
        raise ValueError(f"Batch size exceeds limit: {len(events)} > {MAX_BATCH_SIZE}")
```

---

## 5. Testing Gaps

### Missing Test Coverage

| Area | Status | Priority |
|------|--------|----------|
| Unit tests (models, router) | ✅ 100% | - |
| Integration tests (Postgres) | ✅ Good | - |
| Neo4j projector tests | ❌ Missing | High |
| Concurrent access tests | ❌ Missing | High |
| Error handling tests | ⚠️ Partial | Medium |
| Performance/benchmark tests | ❌ Missing | Medium |
| Security tests | ❌ Missing | High |

### Recommended New Tests

```python
# test_concurrent_access.py
def test_concurrent_emits_same_entity(pg_store, unique_process_id):
    """Multiple agents emitting events for same entity concurrently."""
    ...

# test_projector.py
def test_projector_retry_on_failure():
    """Projector retries on transient Neo4j errors."""
    ...

def test_projector_dead_letter_queue():
    """Failed projections go to dead-letter queue."""
    ...

# test_idempotency.py
def test_idempotency_key_prevents_duplicates():
    """Same idempotency key returns original event."""
    ...

# test_security.py
def test_scope_isolation():
    """Agent in scope A cannot query events from scope B."""
    ...
```

---

## 6. Documentation Gaps

### Missing Documentation

1. **API Reference** — Auto-generated from docstrings (Sphinx/mkdocs)
2. **Architecture Decision Records (ADRs)** — Why PostgreSQL + Neo4j?
3. **Deployment Guide** — Production checklist, scaling recommendations
4. **Troubleshooting Guide** — Common errors and fixes
5. **Migration Guide** — Upgrading between versions

---

## 7. Recommended v0.2.0 Roadmap

### Phase 1: Stability (Weeks 1-2)

- [ ] **Idempotency keys** — Prevent duplicate events
- [ ] **Event schema validation** — Pydantic integration
- [ ] **Connection error handling** — Retry logic, timeouts
- [ ] **Projector failure handling** — Dead-letter queue, alerts

### Phase 2: Observability (Weeks 3-4)

- [ ] **Structured logging** — JSON format, configurable levels
- [ ] **Metrics collection** — Events/sec, latency, error rates
- [ ] **Health check endpoint** — `/health` for Kubernetes
- [ ] **Event replay API** — Rebuild state from events

### Phase 3: Security (Weeks 5-6)

- [ ] **Scope-based access control** — RBAC for agents
- [ ] **Event encryption** — Encrypt sensitive data at rest
- [ ] **Audit logging** — Who accessed what, when
- [ ] **Secrets management** — Move credentials out of code

### Phase 4: Integrations (Weeks 7-8)

- [ ] **CrewAI adapter** — Drop-in Task/Agent decorators
- [ ] **REST API** — HTTP interface for non-Python agents
- [ ] **Webhook emitter** — Push events to external systems
- [ ] **CLI improvements** — Export, import, replay commands

---

## 8. Code Quality Metrics

| Metric | Value | Target |
|--------|-------|--------|
| Lines of Code | ~2,500 | - |
| Test Coverage | ~75% (estimated) | >90% |
| Cyclomatic Complexity | Low-Medium | Low |
| Type Annotations | ✅ 100% | - |
| Docstrings | ⚠️ Partial | 100% public API |

---

## 9. Conclusion

CrewContext v0.1.0 is a **strong foundation** with excellent core architecture. The event sourcing model, causal DAG tracking, and separation of concerns are all well-implemented.

**Critical priorities for v0.2.0:**
1. Fix silent failures in Neo4j projector
2. Add idempotency protection
3. Implement event schema validation
4. Add observability (metrics, structured logging)
5. Implement access control

**Enterprise readiness blockers:**
- No security/access control
- No audit trail for queries
- No encryption for sensitive data
- No SLA/uptime guarantees

With these improvements, CrewContext can become the **de facto standard** for auditable multi-agent systems in regulated industries.

---

## Appendix: Quick Wins

These changes provide high value with minimal effort:

1. **Add `__repr__` to all models** — Better debugging
2. **Add batch size limits** — Prevent OOM
3. **Add connection timeouts** — Prevent hangs
4. **Add validation warnings** — Catch issues early
5. **Update `.env.example`** — Security best practices
6. **Add troubleshooting section to README** — Reduce support burden
