<p align="center">
  <h1 align="center">CrewContext</h1>
  <p align="center">Auditable shared memory for AI agent systems.</p>
</p>

<p align="center">
  <a href="https://github.com/crewcontext/crewcontext/actions"><img src="https://img.shields.io/github/actions/workflow/status/crewcontext/crewcontext/ci.yml?branch=main&style=flat-square" alt="CI"></a>
  <a href="https://pypi.org/project/crewcontext/"><img src="https://img.shields.io/pypi/v/crewcontext?style=flat-square" alt="PyPI"></a>
  <a href="https://pypi.org/project/crewcontext/"><img src="https://img.shields.io/pypi/pyversions/crewcontext?style=flat-square" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/crewcontext/crewcontext?style=flat-square" alt="License"></a>
</p>

---

Multi-agent systems fail at handoffs. Agent 1 processes an invoice. Agent 2 validates it. Agent 3 reconciles discrepancies. But Agent 3 doesn't know what Agent 1 found — context is lost, decisions are invisible, and nothing is auditable.

**CrewContext** fixes this. It gives your agent crews a shared, temporal, causal, auditable memory that persists across every handoff.

```python
from crewcontext import ProcessContext, data_field_gt

# Agent 1: Receives invoice
with ProcessContext(process_id="proc-1", agent_id="receiver") as ctx:
    ctx.router.add_rule("high-value", data_field_gt("amount", 1000), "escalate")
    e1 = ctx.emit("invoice.received", {"amount": 15000, "vendor": "Acme"}, entity_id="inv-1")

# Agent 2: Picks up FULL context — zero information loss
with ProcessContext(process_id="proc-1", agent_id="validator") as ctx:
    history = ctx.timeline("inv-1")        # sees everything Agent 1 did
    e2 = ctx.emit("invoice.validated", {"status": "ok"}, entity_id="inv-1", caused_by=[e1])

# Later: "Why was this invoice approved?"
with ProcessContext(process_id="proc-1", agent_id="auditor") as ctx:
    chain = ctx.causal_parents(e2.id)      # traces back to e1
    timeline = ctx.timeline("inv-1")       # full ordered history
    state = ctx.get_entity("inv-1")        # current entity state
```

## Why CrewContext?

| Problem | How CrewContext Solves It |
|---------|--------------------------|
| Agents lose context at handoffs | Shared event store persists everything |
| Can't explain why a decision was made | Causal DAG tracks parent→child event chains |
| No audit trail for regulators | Append-only events with provenance (who, when, what scope) |
| Can't reconstruct past state | Temporal queries: "what was true at 2pm yesterday?" |
| Routing logic is ad-hoc | Deterministic policy router with composable rules |
| Agent memory is just chat history | Structured entities with versioned snapshots |

## Architecture

```
                    ┌──────────────────────────────────┐
                    │        ProcessContext API         │
                    │  emit · query · timeline · causal │
                    └──────────┬───────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐  ┌─────▼──────┐  ┌──────▼──────┐
    │  PostgreSQL     │  │   Neo4j    │  │   Policy    │
    │  Event Store    │  │   Graph    │  │   Router    │
    │                 │  │            │  │             │
    │ • Append-only   │  │ • Lineage  │  │ • Rules     │
    │ • Temporal      │  │ • Causal   │  │ • Pub/Sub   │
    │ • Causal links  │  │   DAG      │  │ • Routing   │
    │ • Versioned     │  │ • Typed    │  │   decisions │
    │   entities      │  │   rels     │  │             │
    └────────────────┘  └────────────┘  └─────────────┘
         (truth)          (optional)      (in-process)
```

- **PostgreSQL** is the source of truth. Append-only event log, versioned entity snapshots, causal link table.
- **Neo4j** is an optional best-effort projection for graph queries and lineage visualization.
- **Policy Router** evaluates events against priority-ordered rules with composable conditions.

## Installation

```bash
pip install crewcontext
```

## Quickstart

### 1. Start infrastructure

```bash
docker compose up -d
```

### 2. Initialize the database

```bash
crewcontext init-db
```

### 3. Run the demo

```bash
crewcontext demo vendor-discrepancy
```

### 4. Use in your code

```python
from crewcontext import ProcessContext

with ProcessContext(process_id="my-process", agent_id="agent-1") as ctx:
    event = ctx.emit("order.created", {"amount": 5000}, entity_id="order-1")
```

## API Reference

### ProcessContext

The main interface agents interact with.

```python
ProcessContext(
    process_id: str,        # Unique process identifier
    agent_id: str,          # Which agent is operating
    scope: str = "default", # Isolation domain
    db_url: str = None,     # PostgreSQL connection (env: CREWCONTEXT_DB_URL)
    enable_neo4j: bool = True,  # Set False for Postgres-only mode
)
```

#### Emitting Events

```python
# Simple event
event = ctx.emit("invoice.received", {"amount": 5000}, entity_id="inv-1")

# With causal parent (builds the DAG)
child = ctx.emit("invoice.validated", {"ok": True}, entity_id="inv-1", caused_by=[event])

# Atomic batch emit
events = ctx.batch_emit([
    {"event_type": "line.item", "data": {"sku": "A1", "qty": 10}, "entity_id": "inv-1"},
    {"event_type": "line.item", "data": {"sku": "B2", "qty": 5}, "entity_id": "inv-1"},
])
```

#### Querying Events

```python
# Full timeline for an entity
timeline = ctx.timeline("inv-1")

# Filtered query
events = ctx.query(event_type="invoice.received", scope="team-a", limit=50)

# Temporal query — "what happened before 2pm?"
from datetime import datetime, timezone
events = ctx.query(as_of=datetime(2024, 3, 1, 14, 0, tzinfo=timezone.utc))
```

#### Causal DAG

```python
# What caused this event?
parents = ctx.causal_parents(event.id)

# What did this event cause?
children = ctx.causal_children(event.id)

# Full causal chain via Neo4j
chain = ctx.causal_chain(event.id, max_depth=10)
```

#### Entity Snapshots

```python
from crewcontext import Entity

# Save versioned state
ctx.save_entity(Entity(
    id="inv-1", type="Invoice", version=1,
    attributes={"amount": 5000, "status": "received"},
    provenance={"agent": "receiver"},
))

# Update (new version, not overwrite)
ctx.save_entity(Entity(
    id="inv-1", type="Invoice", version=2,
    attributes={"amount": 5000, "status": "validated"},
    provenance={"agent": "validator"},
))

# Get latest state
entity = ctx.get_entity("inv-1")

# Get state at a point in time
entity = ctx.get_entity("inv-1", as_of=some_datetime)
```

#### Relations

```python
from crewcontext import Relation, generate_id

ctx.save_relation(Relation(
    id=generate_id(), type="BELONGS_TO",
    from_entity_id="inv-1", to_entity_id="vendor-42",
    attributes={"since": "2024-01"},
))
```

### Policy Router

Deterministic, priority-ordered routing with composable conditions.

```python
from crewcontext import (
    data_field_gt, data_field_eq, data_fields_differ,
    event_type_is, all_of, any_of, none_of,
)

ctx.router.add_rule(
    name="high-value-invoice",
    condition=all_of(
        data_field_gt("amount", 10000),
        event_type_is("invoice.received"),
    ),
    action="route-to-senior-auditor",
    priority=10,
    metadata={"sla_hours": 4},
)

ctx.router.add_rule(
    name="vendor-mismatch",
    condition=data_fields_differ("vendor_id", "expected_vendor_id"),
    action="flag-for-reconciliation",
    priority=5,
)

# Rules can be managed at runtime
ctx.router.disable_rule("vendor-mismatch")
ctx.router.enable_rule("vendor-mismatch")
ctx.router.remove_rule("vendor-mismatch")

# Subscribe to events
ctx.subscribe("invoice.received", lambda event: print(f"New invoice: {event.data}"))
```

#### Condition Combinators

| Combinator | Description |
|-----------|-------------|
| `data_field_gt(field, threshold)` | `event.data[field] > threshold` |
| `data_field_eq(field, value)` | `event.data[field] == value` |
| `data_field_ne(field, value)` | `event.data[field] != value` |
| `data_fields_differ(field_a, field_b)` | `event.data[a] != event.data[b]` |
| `event_type_is(*types)` | `event.type in types` |
| `all_of(*conditions)` | All conditions must match |
| `any_of(*conditions)` | At least one must match |
| `none_of(*conditions)` | None must match |

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `CREWCONTEXT_DB_URL` | `postgresql://crew:crew@localhost:5432/crewcontext` | PostgreSQL connection |
| `CREWCONTEXT_NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt endpoint |
| `CREWCONTEXT_NEO4J_USER` | `neo4j` | Neo4j username |
| `CREWCONTEXT_NEO4J_PASSWORD` | `crewcontext123` | Neo4j password |

### Postgres-only mode (no Neo4j)

```python
ctx = ProcessContext(process_id="p1", agent_id="a1", enable_neo4j=False)
```

## Works With

CrewContext is **framework-agnostic**. It works alongside any agent framework:

- [CrewAI](https://github.com/joaomdmoura/crewAI)
- [LangGraph](https://github.com/langchain-ai/langgraph)
- [AutoGen](https://github.com/microsoft/autogen)
- [OpenAI Agents SDK](https://github.com/openai/openai-agents-python)
- Custom agent systems

## Development

```bash
git clone https://github.com/crewcontext/crewcontext.git
cd crewcontext
docker compose up -d
pip install -e ".[dev]"
pytest -v
```

## License

[MIT](LICENSE)
