"""Demo: Two ClawLite agents collaborating through CrewContext.

This example shows a realistic scenario where a *researcher* agent scrapes
and analyzes data, then a *writer* agent picks up the context and drafts a
summary — all coordinated through CrewContext's shared event log.

Requirements:
    pip install crewcontext clawlite

Run:
    # 1. Make sure PostgreSQL is running and init the schema
    crewcontext init-db

    # 2. Start ClawLite gateway
    clawlite start --host 127.0.0.1 --port 8787

    # 3. Run this script (or use the ClawLite chat API)
    python demo_two_agents.py
"""
from __future__ import annotations

import asyncio
import json

from crewcontext import ProcessContext, generate_id
from crewcontext_tools import (
    CrewContextEmitTool,
    CrewContextQueryTool,
    CrewContextSnapshotTool,
    _get_context,
)
from clawlite.tools import ToolContext


PROCESS_ID = f"research-{generate_id()[:8]}"
TOPIC_ENTITY = "topic-ai-safety"


async def simulate_researcher():
    """Simulate a ClawLite researcher agent using CrewContext tools."""

    print("=" * 60)
    print("  AGENT 1: Researcher")
    print("=" * 60)

    ctx = ToolContext(session_id="researcher-01", channel="cli", user_id="demo")
    emit = CrewContextEmitTool()
    snapshot = CrewContextSnapshotTool()

    # Step 1 — Record that research has started
    result = await emit.run({
        "process_id": PROCESS_ID,
        "event_type": "research.started",
        "data": {
            "topic": "AI Safety Frameworks",
            "sources": ["arxiv", "alignment-forum", "gov-reports"],
        },
        "entity_id": TOPIC_ENTITY,
    }, ctx)
    parsed = json.loads(result)
    print(f"\n  [emit] research.started -> event {parsed['result']['event_id'][:12]}...")

    # Step 2 — Found some key findings
    result = await emit.run({
        "process_id": PROCESS_ID,
        "event_type": "research.finding",
        "data": {
            "finding": "NIST AI RMF provides a structured approach to AI risk management",
            "source": "NIST AI 100-1",
            "confidence": 0.92,
        },
        "entity_id": TOPIC_ENTITY,
    }, ctx)
    parsed = json.loads(result)
    print(f"  [emit] research.finding  -> event {parsed['result']['event_id'][:12]}...")

    result = await emit.run({
        "process_id": PROCESS_ID,
        "event_type": "research.finding",
        "data": {
            "finding": "EU AI Act classifies systems by risk tier: unacceptable, high, limited, minimal",
            "source": "EU AI Act (2024)",
            "confidence": 0.95,
        },
        "entity_id": TOPIC_ENTITY,
    }, ctx)
    parsed = json.loads(result)
    print(f"  [emit] research.finding  -> event {parsed['result']['event_id'][:12]}...")

    # Step 3 — Save a snapshot of the research state
    result = await snapshot.run({
        "process_id": PROCESS_ID,
        "action": "save",
        "entity_id": TOPIC_ENTITY,
        "entity_type": "ResearchTopic",
        "attributes": {
            "topic": "AI Safety Frameworks",
            "status": "research_complete",
            "findings_count": 2,
            "sources_consulted": 3,
        },
        "version": 1,
    }, ctx)
    print(f"  [snapshot] saved v1 — research_complete")

    # Step 4 — Signal that research is done
    result = await emit.run({
        "process_id": PROCESS_ID,
        "event_type": "research.completed",
        "data": {
            "topic": "AI Safety Frameworks",
            "findings_count": 2,
            "ready_for": "writing",
        },
        "entity_id": TOPIC_ENTITY,
    }, ctx)
    parsed = json.loads(result)
    print(f"  [emit] research.completed -> event {parsed['result']['event_id'][:12]}...")
    print(f"\n  Researcher done. Handing off to writer.\n")


async def simulate_writer():
    """Simulate a ClawLite writer agent that picks up context from the researcher."""

    print("=" * 60)
    print("  AGENT 2: Writer")
    print("=" * 60)

    ctx = ToolContext(session_id="writer-01", channel="cli", user_id="demo")
    query = CrewContextQueryTool()
    emit = CrewContextEmitTool()
    snapshot = CrewContextSnapshotTool()

    # Step 1 — Read the entity snapshot to understand current state
    result = await snapshot.run({
        "process_id": PROCESS_ID,
        "action": "get",
        "entity_id": TOPIC_ENTITY,
    }, ctx)
    parsed = json.loads(result)
    entity = parsed["result"].get("entity", {})
    status = entity.get("attributes", {}).get("status", "unknown")
    print(f"\n  [snapshot] read entity — status: {status}")

    # Step 2 — Query the full timeline to get all research findings
    result = await query.run({
        "process_id": PROCESS_ID,
        "entity_id": TOPIC_ENTITY,
    }, ctx)
    parsed = json.loads(result)
    events = parsed["result"]["events"]
    print(f"  [query] timeline has {parsed['result']['count']} events")

    # Extract findings from the timeline
    findings = [
        e["data"] for e in events
        if e.get("type") == "research.finding"
    ]
    print(f"  [query] found {len(findings)} research findings:")
    for f in findings:
        print(f"    - {f.get('finding', '')[:70]}...")

    # Step 3 — Emit that writing has started
    await emit.run({
        "process_id": PROCESS_ID,
        "event_type": "writing.started",
        "data": {"based_on_findings": len(findings)},
        "entity_id": TOPIC_ENTITY,
    }, ctx)
    print(f"  [emit] writing.started")

    # Step 4 — Emit the draft
    await emit.run({
        "process_id": PROCESS_ID,
        "event_type": "writing.draft_completed",
        "data": {
            "title": "AI Safety Frameworks: NIST RMF and EU AI Act",
            "sections": ["introduction", "nist_rmf", "eu_ai_act", "comparison", "conclusion"],
            "word_count": 1200,
        },
        "entity_id": TOPIC_ENTITY,
    }, ctx)
    print(f"  [emit] writing.draft_completed")

    # Step 5 — Update entity snapshot
    await snapshot.run({
        "process_id": PROCESS_ID,
        "action": "save",
        "entity_id": TOPIC_ENTITY,
        "entity_type": "ResearchTopic",
        "attributes": {
            "topic": "AI Safety Frameworks",
            "status": "draft_complete",
            "findings_count": 2,
            "draft_word_count": 1200,
        },
        "version": 2,
    }, ctx)
    print(f"  [snapshot] saved v2 — draft_complete")

    # Step 6 — Show the full audit trail
    result = await query.run({
        "process_id": PROCESS_ID,
        "entity_id": TOPIC_ENTITY,
    }, ctx)
    parsed = json.loads(result)
    events = parsed["result"]["events"]

    print(f"\n{'=' * 60}")
    print(f"  FULL AUDIT TRAIL ({len(events)} events)")
    print(f"{'=' * 60}")
    for e in events:
        agent = e.get("agent_id", "?")
        etype = e.get("type", "?")
        ts = e.get("timestamp", "?")
        # Trim the clawlite: prefix for display
        agent_short = agent.replace("clawlite:", "")
        print(f"  {ts}  [{agent_short}]  {etype}")

    print(f"\n  Process ID: {PROCESS_ID}")
    print(f"  Every event is immutable, timestamped, and tied to its agent.")
    print(f"  Full causal chain and entity history available for audit.\n")


async def main():
    print(f"\nCrewContext + ClawLite Integration Demo")
    print(f"Process: {PROCESS_ID}\n")

    await simulate_researcher()
    await simulate_writer()

    # Clean up connections
    for ctx in list(_get_context.__wrapped__ if hasattr(_get_context, '__wrapped__') else []):
        pass  # contexts auto-close on process exit


if __name__ == "__main__":
    asyncio.run(main())
