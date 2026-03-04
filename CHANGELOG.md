# Changelog

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
