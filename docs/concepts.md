# Core Concepts

CrewContext is built on a small number of powerful ideas. Understanding these will help you get the most out of the system.

## Events — The Source of Truth

Everything in CrewContext starts with events. An event is an **immutable fact** — something that happened during a process.

```
"invoice.received" — Agent receiver recorded invoice INV-001 at 14:02:03 UTC
```

Events are append-only. Once written, they are never modified or deleted. This gives you a tamper-proof record of everything that happened, in order.

Every event carries:
- **type** — What happened (`invoice.received`, `payment.failed`, `claim.approved`)
- **data** — The payload (amounts, statuses, identifiers)
- **agent_id** — Which agent emitted it
- **process_id** — Which process it belongs to
- **entity_id** — Which business object it affects (optional)
- **scope** — Isolation domain (team, department, tenant)
- **timestamp** — When it happened (timezone-aware UTC)
- **parent_ids** — Which events caused this one (the causal chain)

## Processes and Scopes

A **process** is a unit of work — an invoice being processed, a claim being resolved, a KYC check being performed. All events within a process share a `process_id`.

A **scope** isolates events between teams, departments, or tenants. Events in scope `"team-a"` are invisible to queries scoped to `"team-b"`. This lets multiple teams share the same infrastructure without data leaking across boundaries.

## The Causal DAG

Most systems only track *when* things happened (timeline). CrewContext also tracks *why* things happened (causality).

When you emit an event, you can declare which prior events caused it:

```
invoice.received (e1)
    └──▶ invoice.validated (e2, caused by e1)
              └──▶ reconciliation.completed (e3, caused by e2)
```

This forms a **Directed Acyclic Graph (DAG)** — a tree of cause and effect. You can walk it in either direction:

- **Forward**: "What happened because of this event?" (causal children)
- **Backward**: "Why did this event happen?" (causal parents)

This is critical for auditing. When a regulator asks "why was this payment approved?", you don't grep through logs — you walk the causal chain and show them the exact sequence of decisions.

## Temporal Queries

CrewContext is temporally aware. Every event has a timestamp, and every entity has a validity window (`valid_from` / `valid_to`).

This lets you ask **point-in-time questions**:

- "What events had occurred by 2pm yesterday?" — Query with `as_of`
- "What was the state of this invoice at the time of approval?" — Entity snapshot at a point in time
- "Show me everything that happened between Monday and Wednesday" — Time-range queries

Temporal awareness is what separates an audit trail from a log file. Logs tell you what happened. Temporal queries tell you **what was known at any given moment** — which is what regulators, auditors, and investigators actually need.

## Entity Versioning

An **entity** is a business object — an invoice, a customer, a claim, a payment. Entities change over time as agents process them.

CrewContext handles this with **versioned snapshots**. Instead of overwriting an entity when it changes, you save a new version:

```
Invoice INV-001:
  v1: { status: "received", amount: 15000 }     — saved by agent-receiver
  v2: { status: "discrepancy_found", amount: 15000 } — saved by agent-validator
  v3: { status: "reconciled", amount: 15000 }    — saved by agent-reconciler
```

Every version is preserved. You can retrieve the latest state, or the state at any point in time. Nothing is lost.

This is different from a traditional database where `UPDATE` destroys the previous state. In CrewContext, history is the product.

## Relations

A **relation** is a typed, directed link between two entities:

```
Invoice INV-001 ──BELONGS_TO──▶ Vendor V-42
Payment PAY-007 ──SETTLES──▶ Invoice INV-001
```

Relations carry their own attributes, temporal validity, and provenance. When projected to Neo4j, they become proper graph relationships with typed labels — not generic edges.

## Policy Router

The **policy router** evaluates events against priority-ordered rules to make deterministic routing decisions.

Rules are built from composable conditions:
- `data_field_gt("amount", 10000)` — Amount exceeds threshold
- `event_type_is("invoice.received")` — Event is a specific type
- `data_fields_differ("vendor_id", "expected_vendor_id")` — Two fields don't match
- `all_of(...)`, `any_of(...)`, `none_of(...)` — Boolean combinators

When a rule matches, the router emits a **routing decision** as a first-class event. The decision is stored in the same event log as everything else — fully auditable. No side channels, no invisible logic.

The router also includes a **recursion guard**: routing decision events are never re-evaluated, preventing infinite loops.

## Provenance

Every event, entity, and relation tracks **who** created it and **when**. This is provenance — the chain of custody for data.

In a multi-agent system, provenance answers questions like:
- Which agent made this decision?
- When was this entity last updated?
- Was this event created by a human-initiated agent or an automated one?

Provenance is not optional metadata. It's a core property of every object in CrewContext.

## Dual-Store Architecture

CrewContext uses two stores:

**PostgreSQL (required)** — The source of truth. All events, entities, relations, and causal links are stored here. It's append-only, indexed, and supports temporal queries natively.

**Neo4j (optional)** — A best-effort graph projection. Events and entities are projected into Neo4j as nodes and relationships, enabling graph traversal queries like lineage and causal chain visualization. If Neo4j is down, nothing is lost — PostgreSQL still has everything.

This separation means you get the reliability of a relational database with the query power of a graph database, without coupling your system's correctness to either one.

## Next Steps

- [Getting Started](getting-started.md) — Set up and run your first workflow
- [API Reference](api-reference.md) — Full documentation of every class and method
- [Examples](examples.md) — Real-world patterns and integrations
