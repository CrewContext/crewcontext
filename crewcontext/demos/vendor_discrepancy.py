"""Vendor discrepancy demo — showcases the full CrewContext pipeline.

Scenario: An invoice arrives with a vendor mismatch. Three agents handle
it in sequence — receiver, validator, reconciler. CrewContext preserves
full context, causal chains, and routing decisions across handoffs.
"""
from crewcontext.context import ProcessContext
from crewcontext.models import Entity, Relation, generate_id
from crewcontext.router import all_of, data_field_gt, data_fields_differ


def run_demo():
    process_id = f"demo-{generate_id()[:8]}"
    invoice_id = f"inv-{generate_id()[:8]}"

    print(f"{'=' * 60}")
    print(f"  CrewContext Demo: Vendor Discrepancy Resolution")
    print(f"  Process: {process_id}")
    print(f"  Invoice: {invoice_id}")
    print(f"{'=' * 60}\n")

    # ── Agent 1: Invoice Receiver ─────────────────────────────

    print("[Agent: invoice-receiver]")
    with ProcessContext(
        process_id=process_id,
        agent_id="agent-invoice-receiver",
        enable_neo4j=True,
    ) as ctx:

        # Set up routing rules
        ctx.router.add_rule(
            name="high-value-review",
            condition=data_field_gt("amount", 1000),
            action="route-to-senior-auditor",
            priority=10,
            metadata={"sla_hours": 4},
        )
        ctx.router.add_rule(
            name="vendor-mismatch",
            condition=data_fields_differ("vendor_id", "expected_vendor_id"),
            action="flag-for-reconciliation",
            priority=5,
            metadata={"requires_manual_review": True},
        )

        # Emit: invoice received
        e1 = ctx.emit(
            "invoice.received",
            {
                "invoice_id": invoice_id,
                "vendor_id": "V-1001",
                "expected_vendor_id": "V-1002",
                "amount": 15000,
                "currency": "USD",
            },
            entity_id=invoice_id,
        )
        print(f"  Emitted: invoice.received (amount=15000 USD)")
        print(f"  Event ID: {e1.id[:12]}...")

        # Save entity snapshot
        ctx.save_entity(Entity(
            id=invoice_id, type="Invoice",
            attributes={
                "amount": 15000, "currency": "USD",
                "vendor_id": "V-1001", "status": "received",
            },
            provenance={"agent": "agent-invoice-receiver"},
        ))
        print(f"  Entity snapshot saved: {invoice_id} v1")

        # Check routing decisions
        decisions = ctx.query(event_type="routing.decision")
        for d in decisions:
            data = d.get("data", {})
            print(f"  Routing: {data.get('rule_name')} -> {data.get('action')}")

    # ── Agent 2: Validator ────────────────────────────────────

    print(f"\n[Agent: invoice-validator]")
    with ProcessContext(
        process_id=process_id,
        agent_id="agent-invoice-validator",
        enable_neo4j=True,
    ) as ctx:

        # Query what happened before (context handoff!)
        history = ctx.timeline(invoice_id)
        print(f"  Context received: {len(history)} prior events")

        # Emit: validation result (caused by e1)
        e2 = ctx.emit(
            "invoice.validated",
            {
                "invoice_id": invoice_id,
                "validation_status": "discrepancy_found",
                "discrepancy_type": "vendor_mismatch",
                "vendor_on_invoice": "V-1001",
                "vendor_expected": "V-1002",
            },
            entity_id=invoice_id,
            caused_by=[e1],
        )
        print(f"  Emitted: invoice.validated (discrepancy_found)")
        print(f"  Causal parent: {e1.id[:12]}...")

        # Update entity snapshot
        ctx.save_entity(Entity(
            id=invoice_id, type="Invoice", version=2,
            attributes={
                "amount": 15000, "currency": "USD",
                "vendor_id": "V-1001", "status": "discrepancy_found",
            },
            provenance={"agent": "agent-invoice-validator"},
        ))
        print(f"  Entity snapshot saved: {invoice_id} v2")

    # ── Agent 3: Reconciler ───────────────────────────────────

    print(f"\n[Agent: reconciler]")
    with ProcessContext(
        process_id=process_id,
        agent_id="agent-reconciler",
        enable_neo4j=True,
    ) as ctx:

        # Full context available
        history = ctx.timeline(invoice_id)
        print(f"  Context received: {len(history)} prior events")

        # Emit: reconciliation
        e3 = ctx.emit(
            "reconciliation.completed",
            {
                "invoice_id": invoice_id,
                "resolution": "vendor_corrected",
                "original_vendor": "V-1001",
                "corrected_vendor": "V-1002",
            },
            entity_id=invoice_id,
            caused_by=[e2],
        )
        print(f"  Emitted: reconciliation.completed")

        # Save relation
        ctx.save_relation(Relation(
            id=generate_id(), type="RECONCILED_BY",
            from_entity_id=invoice_id, to_entity_id="agent-reconciler",
        ))

        # Final entity snapshot
        ctx.save_entity(Entity(
            id=invoice_id, type="Invoice", version=3,
            attributes={
                "amount": 15000, "currency": "USD",
                "vendor_id": "V-1002", "status": "reconciled",
            },
            provenance={"agent": "agent-reconciler"},
        ))
        print(f"  Entity snapshot saved: {invoice_id} v3 (reconciled)")

        # ── Summary ──────────────────────────────────────────

        print(f"\n{'=' * 60}")
        print(f"  SUMMARY")
        print(f"{'=' * 60}")

        full_timeline = ctx.timeline(invoice_id)
        print(f"\n  Timeline ({len(full_timeline)} events):")
        for evt in full_timeline:
            agent = evt.get("agent_id", "?")
            etype = evt.get("type", "?")
            ts = evt.get("timestamp", "?")
            print(f"    {ts}  [{agent}]  {etype}")

        # Causal chain
        parents = ctx.causal_parents(e3.id)
        print(f"\n  Causal parents of reconciliation: {len(parents)}")
        children = ctx.causal_children(e1.id)
        print(f"  Causal children of initial receipt: {len(children)}")

        # Entity state
        entity = ctx.get_entity(invoice_id)
        if entity:
            print(f"\n  Final entity state:")
            print(f"    Version: {entity.get('version')}")
            print(f"    Status:  {entity.get('attributes', {}).get('status', 'unknown') if isinstance(entity.get('attributes'), dict) else 'see attributes'}")

        # Neo4j lineage
        lineage = ctx.lineage(invoice_id)
        if lineage:
            print(f"\n  Neo4j Lineage ({len(lineage)} events):")
            for rec in lineage:
                print(f"    {rec.get('type')} by {rec.get('agent_id')}")
        else:
            print(f"\n  (Neo4j lineage not available)")

    print(f"\n{'=' * 60}")
    print(f"  Demo completed successfully!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    run_demo()
