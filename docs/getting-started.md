# Getting Started

This guide takes you from zero to a running multi-agent workflow in under 5 minutes.

## Prerequisites

- **Python 3.10+**
- **Docker** (for PostgreSQL and Neo4j)
- **pip** or any Python package manager

## Installation

```bash
pip install crewcontext
```

Or install from source:

```bash
git clone https://github.com/crewcontext/crewcontext.git
cd crewcontext
pip install -e .
```

## Start Infrastructure

CrewContext uses PostgreSQL as its source of truth and Neo4j (optional) for graph lineage queries.

```bash
docker compose up -d
```

This starts:
- **PostgreSQL 16** on port `5432` (user: `crew`, password: `crew`, database: `crewcontext`)
- **Neo4j 5** on ports `7474` (browser) and `7687` (bolt)

Verify both are healthy:

```bash
docker compose ps
```

Wait until both show `(healthy)` before proceeding.

## Initialize the Database

Create the schema (events, entities, relations, causal links tables):

```bash
crewcontext init-db
```

## Run the Demo

CrewContext ships with a built-in demo that simulates a 3-agent invoice processing pipeline:

```bash
crewcontext demo vendor-discrepancy
```

You should see output showing:
- Agent 1 (receiver) emitting an invoice event
- A routing decision auto-escalating the high-value invoice
- Agent 2 (validator) picking up full context and finding a vendor mismatch
- Agent 3 (reconciler) resolving the discrepancy
- A summary with the full timeline, causal chain, and entity version history

## Your First Workflow

Here's the simplest possible multi-agent workflow:

```python
from crewcontext import ProcessContext

# Agent 1 does work and records it
with ProcessContext(process_id="my-first-process", agent_id="agent-1") as ctx:
    event = ctx.emit(
        "task.started",
        {"description": "Reviewing document", "priority": "high"},
        entity_id="doc-001",
    )

# Agent 2 picks up full context — zero information loss
with ProcessContext(process_id="my-first-process", agent_id="agent-2") as ctx:
    history = ctx.timeline("doc-001")
    print(f"Agent 2 sees {len(history)} prior events")

    review = ctx.emit(
        "task.completed",
        {"result": "approved", "notes": "All checks passed"},
        entity_id="doc-001",
        caused_by=[event],  # builds the causal chain
    )
```

That's it. Agent 2 has full visibility into what Agent 1 did, the causal relationship is recorded, and everything is auditable.

## Postgres-Only Mode

If you don't need graph queries, skip Neo4j entirely:

```bash
# Only start Postgres
docker compose up -d postgres
```

```python
ctx = ProcessContext(
    process_id="my-process",
    agent_id="agent-1",
    enable_neo4j=False,  # no Neo4j connection attempted
)
```

All core functionality — events, entities, causal DAG, temporal queries, routing — works with Postgres alone. Neo4j adds lineage visualization and graph traversal on top.

## Configuration

CrewContext reads configuration from environment variables. Create a `.env` file or set them directly:

```bash
# PostgreSQL (required)
CREWCONTEXT_DB_URL=postgresql://crew:crew@localhost:5432/crewcontext

# Neo4j (optional)
CREWCONTEXT_NEO4J_URI=bolt://localhost:7687
CREWCONTEXT_NEO4J_USER=neo4j
CREWCONTEXT_NEO4J_PASSWORD=crewcontext123
```

Or pass `db_url` directly:

```python
ctx = ProcessContext(
    process_id="p1",
    agent_id="a1",
    db_url="postgresql://user:pass@myhost:5432/mydb",
)
```

## Next Steps

- [Core Concepts](concepts.md) — Understand event sourcing, causal DAGs, and temporal queries
- [API Reference](api-reference.md) — Full documentation of every class and method
- [Examples](examples.md) — Real-world patterns for finance, compliance, and more
