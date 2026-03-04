# Examples

Real-world patterns for using CrewContext in production.

## Multi-Agent Invoice Processing

The classic use case: an invoice arrives, passes through multiple agents, and each agent has full context of what happened before.

```python
from crewcontext import ProcessContext, Entity, Relation, generate_id
from crewcontext import data_field_gt, data_fields_differ

process_id = f"invoice-{generate_id()[:8]}"
invoice_id = "INV-2024-001"

# ── Agent 1: Receiver ──────────────────────────────

with ProcessContext(process_id=process_id, agent_id="receiver") as ctx:
    # Set up routing rules
    ctx.router.add_rule(
        "high-value",
        data_field_gt("amount", 10000),
        "route-to-senior-auditor",
        priority=10,
    )
    ctx.router.add_rule(
        "vendor-mismatch",
        data_fields_differ("vendor_id", "expected_vendor_id"),
        "flag-for-reconciliation",
        priority=5,
    )

    e1 = ctx.emit(
        "invoice.received",
        {
            "amount": 25000,
            "currency": "KES",
            "vendor_id": "V-100",
            "expected_vendor_id": "V-200",
        },
        entity_id=invoice_id,
    )

    ctx.save_entity(Entity(
        id=invoice_id, type="Invoice", version=1,
        attributes={"amount": 25000, "status": "received"},
    ))

# ── Agent 2: Validator ─────────────────────────────

with ProcessContext(process_id=process_id, agent_id="validator") as ctx:
    # Full context from Agent 1 is available
    history = ctx.timeline(invoice_id)
    # history contains: invoice.received + routing.decision

    e2 = ctx.emit(
        "invoice.validated",
        {"status": "discrepancy_found", "type": "vendor_mismatch"},
        entity_id=invoice_id,
        caused_by=[e1],
    )

    ctx.save_entity(Entity(
        id=invoice_id, type="Invoice", version=2,
        attributes={"amount": 25000, "status": "discrepancy_found"},
    ))

# ── Agent 3: Reconciler ────────────────────────────

with ProcessContext(process_id=process_id, agent_id="reconciler") as ctx:
    history = ctx.timeline(invoice_id)
    # history contains all 3 prior events

    e3 = ctx.emit(
        "invoice.reconciled",
        {"resolution": "vendor_corrected", "corrected_vendor": "V-200"},
        entity_id=invoice_id,
        caused_by=[e2],
    )

    ctx.save_entity(Entity(
        id=invoice_id, type="Invoice", version=3,
        attributes={"amount": 25000, "status": "reconciled"},
    ))

    # Audit: walk the causal chain backwards
    parents = ctx.causal_parents(e3.id)  # → [e2.id]
    grandparents = ctx.causal_parents(e2.id)  # → [e1.id]
```

## KYC Compliance Pipeline

Every decision must be traceable. CrewContext makes the audit trail automatic.

```python
from crewcontext import ProcessContext, Entity, generate_id
from crewcontext import all_of, data_field_eq, event_type_is

customer_id = "CUST-9001"
process_id = f"kyc-{generate_id()[:8]}"

# ── Agent: ID Verifier ─────────────────────────────

with ProcessContext(process_id=process_id, agent_id="id-verifier") as ctx:
    e1 = ctx.emit(
        "kyc.id_verified",
        {"document_type": "passport", "match_score": 0.97, "result": "pass"},
        entity_id=customer_id,
    )

# ── Agent: Sanctions Checker ───────────────────────

with ProcessContext(process_id=process_id, agent_id="sanctions-checker") as ctx:
    e2 = ctx.emit(
        "kyc.sanctions_checked",
        {"lists_checked": ["OFAC", "EU", "UN"], "hits": 0, "result": "clear"},
        entity_id=customer_id,
        caused_by=[e1],
    )

# ── Agent: PEP Screener ───────────────────────────

with ProcessContext(process_id=process_id, agent_id="pep-screener") as ctx:
    e3 = ctx.emit(
        "kyc.pep_screened",
        {"pep_match": False, "result": "clear"},
        entity_id=customer_id,
        caused_by=[e2],
    )

# ── Agent: Decision Maker ──────────────────────────

with ProcessContext(process_id=process_id, agent_id="decision-maker") as ctx:
    ctx.router.add_rule(
        "auto-approve",
        all_of(
            event_type_is("kyc.decision"),
            data_field_eq("recommendation", "approve"),
        ),
        "auto-approve-account",
        priority=10,
    )

    # Full audit trail is available
    timeline = ctx.timeline(customer_id)
    # timeline: id_verified → sanctions_checked → pep_screened

    e4 = ctx.emit(
        "kyc.decision",
        {"recommendation": "approve", "risk_score": 0.12},
        entity_id=customer_id,
        caused_by=[e3],
    )

    ctx.save_entity(Entity(
        id=customer_id, type="Customer", version=1,
        attributes={"kyc_status": "approved", "risk_score": 0.12},
        provenance={"process": process_id, "agent": "decision-maker"},
    ))

    # Regulator asks: "Show me why this customer was approved."
    # Walk backwards from the decision:
    chain = []
    current = e4.id
    while True:
        parents = ctx.causal_parents(current)
        if not parents:
            break
        chain.extend(parents)
        current = parents[0]
    # chain: [e3.id, e2.id, e1.id] — complete decision trail
```

## Integration with CrewAI

CrewContext works alongside CrewAI — use CrewAI for orchestration, CrewContext for memory.

```python
from crewai import Agent, Task, Crew
from crewcontext import ProcessContext, generate_id

process_id = f"crew-{generate_id()[:8]}"

def researcher_work(task_description: str) -> str:
    with ProcessContext(process_id=process_id, agent_id="researcher") as ctx:
        result = "Found 3 relevant papers on multi-agent coordination"
        ctx.emit(
            "research.completed",
            {"query": task_description, "result": result, "papers_found": 3},
            entity_id="research-task-1",
        )
        return result

def writer_work(research_output: str) -> str:
    with ProcessContext(process_id=process_id, agent_id="writer") as ctx:
        # Writer sees everything the researcher did
        context = ctx.timeline("research-task-1")
        result = f"Draft based on {len(context)} research events"
        ctx.emit(
            "draft.completed",
            {"word_count": 1500, "status": "ready_for_review"},
            entity_id="research-task-1",
        )
        return result
```

## Integration with LangGraph

Use CrewContext as a persistent state layer across LangGraph nodes.

```python
from crewcontext import ProcessContext, generate_id

process_id = f"graph-{generate_id()[:8]}"

def intake_node(state: dict) -> dict:
    with ProcessContext(process_id=process_id, agent_id="intake") as ctx:
        event = ctx.emit(
            "request.received",
            {"customer_id": state["customer_id"], "request_type": state["type"]},
            entity_id=state["customer_id"],
        )
        state["intake_event_id"] = event.id
    return state

def processing_node(state: dict) -> dict:
    with ProcessContext(process_id=process_id, agent_id="processor") as ctx:
        # Full context from intake is available
        history = ctx.timeline(state["customer_id"])
        ctx.emit(
            "request.processed",
            {"result": "completed", "prior_events": len(history)},
            entity_id=state["customer_id"],
        )
    return state
```

## Temporal Reconstruction

Answering "what did we know at the time?" — critical for audits and investigations.

```python
from datetime import datetime, timezone, timedelta
from crewcontext import ProcessContext

with ProcessContext(process_id="audit-target", agent_id="auditor") as ctx:
    # What was the state of the invoice at 2pm on March 1st?
    point_in_time = datetime(2024, 3, 1, 14, 0, tzinfo=timezone.utc)

    entity_then = ctx.get_entity("INV-001", as_of=point_in_time)
    events_then = ctx.query(entity_id="INV-001", as_of=point_in_time)

    # Compare with current state
    entity_now = ctx.get_entity("INV-001")
    events_now = ctx.timeline("INV-001")

    # Diff: what changed between then and now?
    new_events = [e for e in events_now if e not in events_then]
```

## Batch Operations

Emit multiple events atomically — all succeed or all fail.

```python
from crewcontext import ProcessContext

with ProcessContext(process_id="batch-demo", agent_id="bulk-loader") as ctx:
    line_items = [
        {"event_type": "line.item", "data": {"sku": "A1", "qty": 10, "price": 500}, "entity_id": "order-1"},
        {"event_type": "line.item", "data": {"sku": "B2", "qty": 5, "price": 1200}, "entity_id": "order-1"},
        {"event_type": "line.item", "data": {"sku": "C3", "qty": 1, "price": 8000}, "entity_id": "order-1"},
    ]
    events = ctx.batch_emit(line_items)
    # All 3 events are committed in a single transaction
```

## Event Subscriptions

React to events in real-time within a process context.

```python
from crewcontext import ProcessContext

notifications = []

with ProcessContext(process_id="sub-demo", agent_id="agent-1") as ctx:
    # Subscribe before emitting
    ctx.subscribe("payment.failed", lambda e: notifications.append({
        "alert": f"Payment {e.data['payment_id']} failed",
        "amount": e.data["amount"],
    }))

    ctx.emit("payment.failed", {
        "payment_id": "PAY-001",
        "amount": 50000,
        "reason": "insufficient_funds",
    })

    # notifications now contains the alert
```

## Postgres-Only Mode

For simpler deployments or environments where Neo4j isn't available.

```python
from crewcontext import ProcessContext

# Everything works — events, entities, causal DAG, temporal queries, routing
# Only Neo4j-specific features (lineage, cypher, causal_chain) return empty lists
with ProcessContext(
    process_id="simple",
    agent_id="agent-1",
    enable_neo4j=False,
) as ctx:
    ctx.emit("task.done", {"result": "success"})
    timeline = ctx.timeline("entity-1")  # works
    parents = ctx.causal_parents("event-id")  # works (uses Postgres)
    lineage = ctx.lineage("entity-1")  # returns [] (Neo4j disabled)
```
