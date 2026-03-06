# CrewContext – Shared Memory for Agent Teams

> Give your ClawLite agent auditable, shared memory across multi-agent workflows.

## tools

- crewcontext_emit
- crewcontext_query
- crewcontext_snapshot

## instructions

You have access to CrewContext, a shared memory layer that records every action
as an immutable, auditable event. Use it to coordinate with other agents.

**When to emit events:**
- After completing a task or subtask
- When you discover new information other agents need
- When you make a decision that affects the workflow

**When to query:**
- Before starting work, check what other agents have already done
- To understand the full history of an entity (use entity_id)
- To find specific event types across the workflow

**When to use snapshots:**
- Save the current state of an object you're working on
- Read the latest state of an object another agent modified

Always use a consistent `process_id` across agents in the same workflow.
Use descriptive dotted `event_type` names like `research.completed` or `report.drafted`.
