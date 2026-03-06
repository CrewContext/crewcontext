"""ClawLite tools for CrewContext integration.

Registers CrewContext as a tool inside ClawLite so any ClawLite agent can
emit events, query timelines, save entity snapshots, and inspect causal
chains through the shared CrewContext memory layer.

Usage:
    from clawlite.tools import ToolRegistry
    from crewcontext_tools import register_crewcontext_tools

    registry = ToolRegistry(cfg)
    register_crewcontext_tools(registry, db_url="postgresql://...")
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from clawlite.tools import Tool, ToolContext, ToolRegistry
from crewcontext import ProcessContext, Entity, Relation, generate_id

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared connection pool — one ProcessContext per (process_id, agent_id)
# ---------------------------------------------------------------------------

_contexts: Dict[str, ProcessContext] = {}


def _get_context(
    process_id: str,
    agent_id: str,
    db_url: Optional[str] = None,
) -> ProcessContext:
    """Return an open ProcessContext, reusing existing connections."""
    key = f"{process_id}::{agent_id}"
    if key not in _contexts:
        ctx = ProcessContext(
            process_id=process_id,
            agent_id=agent_id,
            db_url=db_url,
            enable_neo4j=False,  # keep it lightweight for tool use
        )
        ctx.connect()
        _contexts[key] = ctx
    return _contexts[key]


def _ok(tool_name: str, result: Any) -> str:
    return json.dumps({"ok": True, "tool": tool_name, "result": result})


def _error(tool_name: str, code: str, message: str) -> str:
    return json.dumps({"ok": False, "tool": tool_name, "error": {"code": code, "message": message}})


# ---------------------------------------------------------------------------
# Tool: crewcontext_emit
# ---------------------------------------------------------------------------

class CrewContextEmitTool(Tool):
    """Emit an event into CrewContext shared memory."""

    name = "crewcontext_emit"
    description = (
        "Emit a structured event into CrewContext shared memory. "
        "Use this to record actions, decisions, or observations that "
        "other agents in the crew need to see."
    )

    def args_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "process_id": {
                    "type": "string",
                    "description": "The shared process/workflow ID all agents collaborate on.",
                },
                "event_type": {
                    "type": "string",
                    "description": "Dotted event name, e.g. 'task.completed' or 'data.scraped'.",
                },
                "data": {
                    "type": "object",
                    "description": "Event payload — any JSON-serializable dict.",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Optional entity this event relates to.",
                },
            },
            "required": ["process_id", "event_type", "data"],
        }

    async def run(self, args: dict, ctx: ToolContext) -> str:
        process_id = args.get("process_id", "")
        event_type = args.get("event_type", "")
        data = args.get("data", {})
        entity_id = args.get("entity_id")

        if not process_id or not event_type:
            return _error(self.name, "missing_args", "process_id and event_type are required")

        try:
            agent_id = f"clawlite:{ctx.session_id}"
            pctx = _get_context(process_id, agent_id)
            event = pctx.emit(event_type, data, entity_id=entity_id)
            return _ok(self.name, {
                "event_id": event.id,
                "type": event.type,
                "process_id": event.process_id,
                "agent_id": event.agent_id,
                "entity_id": event.entity_id,
                "timestamp": event.timestamp.isoformat(),
            })
        except Exception as exc:
            log.exception("crewcontext_emit failed")
            return _error(self.name, "emit_failed", str(exc))


# ---------------------------------------------------------------------------
# Tool: crewcontext_query
# ---------------------------------------------------------------------------

class CrewContextQueryTool(Tool):
    """Query events from CrewContext shared memory."""

    name = "crewcontext_query"
    description = (
        "Query the shared CrewContext event log. Retrieve what other agents "
        "have done, filter by entity or event type, and get full timelines."
    )

    def args_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "process_id": {
                    "type": "string",
                    "description": "The shared process/workflow ID.",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Filter events for a specific entity.",
                },
                "event_type": {
                    "type": "string",
                    "description": "Filter by event type, e.g. 'task.completed'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max events to return (default 50).",
                },
            },
            "required": ["process_id"],
        }

    async def run(self, args: dict, ctx: ToolContext) -> str:
        process_id = args.get("process_id", "")
        if not process_id:
            return _error(self.name, "missing_args", "process_id is required")

        try:
            agent_id = f"clawlite:{ctx.session_id}"
            pctx = _get_context(process_id, agent_id)

            entity_id = args.get("entity_id")
            event_type = args.get("event_type")
            limit = args.get("limit", 50)

            if entity_id and not event_type:
                events = pctx.timeline(entity_id)[:limit]
            else:
                events = pctx.query(
                    entity_id=entity_id,
                    event_type=event_type,
                    limit=limit,
                )

            return _ok(self.name, {
                "count": len(events),
                "events": events,
            })
        except Exception as exc:
            log.exception("crewcontext_query failed")
            return _error(self.name, "query_failed", str(exc))


# ---------------------------------------------------------------------------
# Tool: crewcontext_snapshot
# ---------------------------------------------------------------------------

class CrewContextSnapshotTool(Tool):
    """Save or retrieve entity snapshots in CrewContext."""

    name = "crewcontext_snapshot"
    description = (
        "Save or retrieve a versioned entity snapshot. Use 'save' to record "
        "the current state of a business object, or 'get' to read it."
    )

    def args_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "process_id": {
                    "type": "string",
                    "description": "The shared process/workflow ID.",
                },
                "action": {
                    "type": "string",
                    "enum": ["save", "get"],
                    "description": "'save' to write a snapshot, 'get' to read one.",
                },
                "entity_id": {
                    "type": "string",
                    "description": "The entity identifier.",
                },
                "entity_type": {
                    "type": "string",
                    "description": "Entity type (required for 'save'), e.g. 'Task', 'Document'.",
                },
                "attributes": {
                    "type": "object",
                    "description": "Entity attributes (required for 'save').",
                },
                "version": {
                    "type": "integer",
                    "description": "Entity version (default 1).",
                },
            },
            "required": ["process_id", "action", "entity_id"],
        }

    async def run(self, args: dict, ctx: ToolContext) -> str:
        process_id = args.get("process_id", "")
        action = args.get("action", "")
        entity_id = args.get("entity_id", "")

        if not process_id or not action or not entity_id:
            return _error(self.name, "missing_args", "process_id, action, and entity_id are required")

        try:
            agent_id = f"clawlite:{ctx.session_id}"
            pctx = _get_context(process_id, agent_id)

            if action == "save":
                entity_type = args.get("entity_type", "Unknown")
                attributes = args.get("attributes", {})
                version = args.get("version", 1)

                entity = Entity(
                    id=entity_id,
                    type=entity_type,
                    attributes=attributes,
                    version=version,
                    provenance={"agent": agent_id, "source": "clawlite"},
                )
                pctx.save_entity(entity)
                return _ok(self.name, {
                    "action": "saved",
                    "entity_id": entity_id,
                    "version": version,
                })

            elif action == "get":
                entity = pctx.get_entity(entity_id)
                if entity:
                    return _ok(self.name, {"action": "retrieved", "entity": entity})
                else:
                    return _ok(self.name, {"action": "not_found", "entity_id": entity_id})

            else:
                return _error(self.name, "invalid_action", f"Unknown action '{action}', use 'save' or 'get'")

        except Exception as exc:
            log.exception("crewcontext_snapshot failed")
            return _error(self.name, "snapshot_failed", str(exc))


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def register_crewcontext_tools(
    registry: ToolRegistry,
    db_url: Optional[str] = None,
) -> None:
    """Register all CrewContext tools with a ClawLite ToolRegistry.

    Args:
        registry: The ClawLite tool registry to register into.
        db_url: Optional PostgreSQL connection string. If not provided,
                CrewContext will use the CREWCONTEXT_DB_URL env var.
    """
    # Store db_url so _get_context can pick it up
    if db_url:
        import os
        os.environ.setdefault("CREWCONTEXT_DB_URL", db_url)

    registry.register(CrewContextEmitTool())
    registry.register(CrewContextQueryTool())
    registry.register(CrewContextSnapshotTool())

    log.info("Registered CrewContext tools: crewcontext_emit, crewcontext_query, crewcontext_snapshot")
