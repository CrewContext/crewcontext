# Changelog

## 0.2.0 (2026-03-11)

Major release adding enterprise features: stability, observability, and security.

### Stability (Phase 1)

**Idempotency**
- **Idempotency keys** — Prevent duplicate event emission with `idempotency_key` parameter
- **Deduplication API** — `get_event_by_idempotency_key()` for checking existing events
- **Database support** — New `idempotency_keys` table with unique constraints

**Schema Validation**
- **Pydantic integration** — `EventSchema` base class for event validation
- **Schema registry** — `register_event_schema()` for type-safe events
- **Strict mode** — Reject unknown fields with `extra="forbid"`
- **ValidationError** — Clear error messages for invalid events

**Retry Logic**
- **PostgreSQL retry** — 3 attempts with exponential backoff (2s, 4s, 8s)
- **Neo4j retry** — 3 attempts with backoff (100ms, 200ms, 400ms)
- **Circuit breaker** — Opens after 5 consecutive failures, resets after 30s
- **Configurable timeouts** — Connection timeout parameter

**Metrics**
- **MetricsCollector** — Counters, histograms, gauges
- **Failure tracking** — Last 100 failures with error details
- **Latency tracking** — `measure_time` context manager
- **Export API** — `get_metrics()` for monitoring integration

**Batch Limits**
- **Batch size validation** — 1000 event limit with clear error messages
- **OOM prevention** — Protects against memory exhaustion

### Observability (Phase 2)

**Structured Logging**
- **JSON logging** — `setup_logging(json_format=True)` for production
- **Text formatting** — Human-readable format for development
- **Structured context** — `extra={}` for custom fields
- **LogContext manager** — Automatic context injection

**Health Checks**
- **HealthChecker** — Kubernetes-style health API
- **Liveness probes** — `is_live()` for process health
- **Readiness probes** — `is_ready()` for traffic readiness
- **Custom checks** — `add_check()` for application-specific checks
- **Latency tracking** — Response time measurement

**Event Replay**
- **replay_events()** — Replay events with custom handler
- **rebuild_entity_state()** — Reconstruct entity from event history
- **export_events()** — Export as JSON or NDJSON for backup
- **as_of support** — Point-in-time replay

**Prometheus Export**
- **to_prometheus()** — Text exposition format
- **Counter metrics** — `crewcontext_emit_success`
- **Summary metrics** — `crewcontext_emit_latency_ms` with quantiles
- **FastAPI integration** — Ready-to-use `/metrics` endpoint

### Security (Phase 3)

**Access Control (RBAC)**
- **AccessPolicy** — Role-based access control
- **Permission enum** — READ, WRITE, DELETE, ADMIN
- **Role class** — Permissions + scope assignments
- **Built-in roles** — admin, writer, reader, auditor
- **Fine-grained rules** — `AccessRule` with priority and conditions
- **Scope isolation** — Agents restricted to assigned scopes
- **Audit logging** — All access decisions logged

**Encryption**
- **EncryptionManager** — Field-level encryption with Fernet (AES-128)
- **Key generation** — `generate_key()` for 32-byte keys
- **Password-based keys** — `key_from_password()` with PBKDF2
- **Field encryption** — `encrypt_fields()` for selective encryption
- **EncryptedStore** — Transparent encryption wrapper for stores
- **Decrypt tracking** — Count of decrypt operations

**Audit Logging**
- **Query audit** — Automatic logging of all queries
- **Access audit** — RBAC decision logging
- **Secrets audit** — Secret access tracking
- **Audit export** — `get_query_audit_log()` for compliance

**Secrets Management**
- **SecretsManager** — Unified secrets interface
- **Env provider** — Environment variables with prefix support
- **File provider** — Kubernetes/Docker Swarm secrets
- **JSON provider** — JSON file-based secrets
- **Vault provider** — HashiCorp Vault integration (optional)
- **Type-safe access** — `get_int()`, `get_bool()` helpers
- **Required secrets** — `require_secret()` for mandatory values

### API Changes

**New Classes**
- `EventSchema`, `SchemaRegistry`, `ValidationError` — Schema validation
- `MetricsCollector`, `measure_time` — Metrics
- `HealthChecker`, `HealthCheckResult`, `HealthStatus` — Health checks
- `AccessPolicy`, `Permission`, `Role`, `AccessRule` — Access control
- `EncryptionManager`, `EncryptedStore`, `FieldEncryption` — Encryption
- `SecretsManager`, `SecretProvider`, `EnvSecretProvider` — Secrets

**ProcessContext Additions**
- `replay_events()` — Replay event history
- `rebuild_entity_state()` — Rebuild entity from events
- `export_events()` — Export events for backup
- `check_access()` — Check agent permissions
- `get_query_audit_log()` — Get audit trail
- `get_metrics()` — Export metrics
- `access_policy` property — Access control policy
- `metrics` property — Metrics collector

**ProcessContext Changes**
- `emit()` — New `idempotency_key` parameter
- `__init__()` — New `access_policy` parameter

### Database Changes

**New Tables**
- `idempotency_keys` — Prevent duplicate event emission

**New Columns**
- `events.idempotency_key` — Idempotency key for events

**New Indexes**
- `idx_events_idempotency` — Fast idempotency key lookup

### Configuration

**New Environment Variables**
- `CREWCONTEXT_LOG_LEVEL` — Logging level (DEBUG, INFO, WARNING, ERROR)
- `CREWCONTEXT_JSON_LOGGING` — Enable JSON logging (true/false)
- `CREWCONTEXT_ENCRYPTION_KEY` — 32-byte encryption key
- `CREWCONTEXT_SECRETS_PROVIDER` — Secrets provider (env, file, json, vault)
- `CREWCONTEXT_SECRETS_PATH` — Path to secrets directory

### Testing

**New Test Files**
- `tests/test_observability.py` — 16 tests for Phase 2 features
- `tests/test_security.py` — 25 tests for Phase 3 features

**Test Coverage**
- 73 total tests (6 skipped, require PostgreSQL)
- 100% backward compatibility maintained

### Dependencies

**New**
- `pydantic>=2.0` — Schema validation
- `cryptography>=3.0` — Encryption (optional, for production)

**Updated**
- None — All existing dependencies unchanged

### Documentation

**New Files**
- `IMPROVEMENTS.md` — Complete v0.2.0 improvements guide
- `ARCHITECTURE_REVIEW.md` — Architectural analysis and recommendations

### Breaking Changes

**None** — All new features are optional additions. Existing code continues to work without modification.

### Migration

```bash
# Update database schema
crewcontext init-db

# Install new dependencies
pip install "crewcontext[security]"  # Includes cryptography

# Optional: Enable features
export CREWCONTEXT_JSON_LOGGING=true
export CREWCONTEXT_ENCRYPTION_KEY=$(python -c "import os; print(os.urandom(32).hex())")
```

### Contributors

Major architectural improvements based on comprehensive codebase review.

---

## 0.1.0 (2026-03-04)

Initial open-source release.

### Core
- **ProcessContext** — Main API for agent interaction (emit, query, timeline, subscribe)
- **Event sourcing** — Append-only event store with PostgreSQL
- **Causal DAG** — Track cause-and-effect chains across agent handoffs via `caused_by`
- **Temporal queries** — Point-in-time reconstruction with `as_of` filtering
- **Entity versioning** — Immutable snapshots with composite (id, version) keys
- **Typed relations** — Directed, attributed edges between entities

### Policy Router
- Priority-ordered deterministic rule evaluation
- Composable condition combinators: `all_of`, `any_of`, `none_of`, `data_field_gt`, `data_field_eq`, `data_field_ne`, `data_fields_differ`, `event_type_is`
- Recursion guard for routing decision events
- Pub/sub event subscriptions
- Runtime rule enable/disable

### Storage
- **PostgreSQL** backend with connection pooling (`psycopg_pool`)
- Atomic batch event writes
- Scope filtering, pagination, indexed queries
- Causal links table with parent/child queries

### Projection
- **Neo4j** optional graph projection
- Typed relationship labels (not generic `:R`)
- Bounded lineage queries
- Causal chain graph traversal
- Graceful degradation when Neo4j is unavailable

### CLI
- `crewcontext init-db` — Initialize database schema
- `crewcontext demo vendor-discrepancy` — Run built-in demo

### Testing
- 32 unit tests (models, router, combinators, pub/sub)
- 11 integration tests (Postgres store, temporal queries, causal links, entity versioning)
- Auto-skip when database is unavailable
- Test isolation via unique process IDs
