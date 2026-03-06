"""Quickstart: Register CrewContext tools in a ClawLite agent.

This is the minimal setup to give any ClawLite agent access to
CrewContext shared memory. Once registered, the agent can emit events,
query timelines, and manage entity snapshots through natural language.

Usage:
    1. Install both packages:
       pip install crewcontext clawlite

    2. Set up PostgreSQL and init the schema:
       export CREWCONTEXT_DB_URL="postgresql://user:pass@localhost:5432/crewcontext"
       crewcontext init-db

    3. Register the tools before starting ClawLite:

       # In your ClawLite startup script or plugin:
       from crewcontext_tools import register_crewcontext_tools
       register_crewcontext_tools(registry)

    4. Now your agent can use these tools via chat:

       User: "Log that we received invoice INV-42 for $5,000 from Acme Corp"
       Agent: [calls crewcontext_emit with event_type="invoice.received", ...]

       User: "What happened with invoice INV-42?"
       Agent: [calls crewcontext_query with entity_id="INV-42"]

       User: "Save the current state of this invoice"
       Agent: [calls crewcontext_snapshot with action="save", ...]
"""
from clawlite.tools import ToolRegistry
from crewcontext_tools import register_crewcontext_tools


def setup(registry: ToolRegistry) -> None:
    """Call this during ClawLite startup to add CrewContext tools."""
    register_crewcontext_tools(
        registry,
        db_url="postgresql://localhost:5432/crewcontext",
    )


# -- Example: verify tools are registered ----------------------------------

if __name__ == "__main__":
    # This won't fully work standalone (needs ClawLite config),
    # but shows the registration pattern.
    print("CrewContext + ClawLite Quickstart")
    print()
    print("To integrate, add this to your ClawLite startup:")
    print()
    print("    from crewcontext_tools import register_crewcontext_tools")
    print("    register_crewcontext_tools(registry)")
    print()
    print("Tools provided:")
    print("  - crewcontext_emit     : Record events into shared memory")
    print("  - crewcontext_query    : Query event history and timelines")
    print("  - crewcontext_snapshot : Save/read versioned entity state")
    print()
    print("All events are immutable, timestamped, and agent-attributed.")
    print("Full audit trail available for compliance and debugging.")
