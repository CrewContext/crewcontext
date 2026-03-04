# CrewContext

Context coordination layer for multi-agent business workflows.

## Problem

Multi-agent business workflows (for example: invoice processing, audit, reconciliation) fail because agents drop context across handoffs. Existing "memory" tools focus on personal chat history/preferences. CrewContext provides a scoped, temporal, provenance-rich, queryable shared state for agent crews working on a business process.

## Architecture

- **PostgreSQL**: Source of truth (append-only event store with temporal validity and provenance)
- **Neo4j**: Best-effort projection for lineage queries and graph-shaped views
- **Policy Router**: Deterministic routing with auditable decisions

## Quickstart

### 1. Start Infrastructure

```bash
docker compose up -d
```

### 2. Install Package

```bash
pip install -e .
```

### 3. Configure Environment

```bash
cp .env.example .env
```

### 4. Run Demo

```bash
crewcontext demo vendor-discrepancy
```

## API

### ProcessContext

```python
from crewcontext import ProcessContext

with ProcessContext(process_id="proc-123", agent_id="agent-1") as ctx:
    event = ctx.emit(
        "invoice.received",
        {"invoice_id": "inv-001", "amount": 1000},
        entity_id="inv-001"
    )
    events = ctx.query(entity_id="inv-001")
    timeline = ctx.timeline("inv-001")
```

## Development

### Run Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## License

MIT
