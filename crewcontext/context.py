"""ProcessContext — the main API agents interact with.

This is the public interface. Agents emit events, query history,
build entity snapshots, and trace causal chains through this class.

Usage:
    with ProcessContext(process_id="proc-1", agent_id="agent-a") as ctx:
        e1 = ctx.emit("invoice.received", {"amount": 5000}, entity_id="inv-1")
        e2 = ctx.emit("invoice.validated", {"ok": True}, entity_id="inv-1", caused_by=[e1])
        history = ctx.timeline("inv-1")
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Type

from .models import Entity, Event, Relation, RoutingDecision, generate_id
from .projection.projector import Neo4jProjector
from .router import PolicyRouter
from .schema import EventSchema, SchemaRegistry, ValidationError
from .store.postgres import PostgresStore
from .metrics import MetricsCollector, measure_time
from .security import AccessPolicy, Permission, AccessDecision

log = logging.getLogger(__name__)


class ProcessContext:
    """Scoped, temporal, causal context for a business process.

    Features:
    - **emit()**: Record events with optional causal parents.
    - **query()**: Retrieve events with temporal/scope/type filtering.
    - **timeline()**: Ordered event history for an entity.
    - **snapshot()**: Save/retrieve versioned entity state.
    - **causal_chain()**: Walk the causal DAG.
    - **subscribe()**: React to event types in real-time.
    - **batch_emit()**: Atomic multi-event writes.
    """

    def __init__(
        self,
        process_id: str,
        agent_id: str,
        scope: str = "default",
        db_url: Optional[str] = None,
        enable_neo4j: bool = True,
        access_policy: Optional[AccessPolicy] = None,
    ):
        self.process_id = process_id
        self.agent_id = agent_id
        self.scope = scope

        self._metrics = MetricsCollector(service_name=f"crewcontext.{process_id[:8]}")
        self._access_policy = access_policy or AccessPolicy(enable_audit=True)
        self._store = PostgresStore(db_url, metrics=self._metrics)
        self._projector = Neo4jProjector(metrics=self._metrics) if enable_neo4j else None
        self._router = PolicyRouter()
        self._schema_registry = SchemaRegistry()
        self._connected = False
        self._query_audit_log: List[Dict[str, Any]] = []

    # -- context manager ----------------------------------------------------

    def __enter__(self) -> ProcessContext:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def connect(self) -> None:
        self._store.connect()
        self._store.init_schema()
        self._connected = True
        if self._projector:
            self._projector.connect()  # best-effort, logs on failure
        log.info(
            "ProcessContext ready: process=%s agent=%s scope=%s",
            self.process_id, self.agent_id, self.scope,
        )

    def close(self) -> None:
        self._store.close()
        if self._projector:
            self._projector.close()
        self._connected = False

    # -- router access ------------------------------------------------------

    @property
    def router(self) -> PolicyRouter:
        return self._router

    # -- metrics ------------------------------------------------------------

    @property
    def metrics(self) -> MetricsCollector:
        """Access metrics for monitoring and debugging."""
        return self._metrics

    def get_metrics(self) -> dict:
        """Export all metrics for external monitoring systems."""
        return self._metrics.export()

    # -- access control -----------------------------------------------------

    @property
    def access_policy(self) -> AccessPolicy:
        """Access the access control policy."""
        return self._access_policy

    def check_access(
        self,
        permission: Permission,
        scope: Optional[str] = None,
    ) -> bool:
        """Check if current agent has permission to access scope.

        Args:
            permission: Permission to check.
            scope: Scope to check (defaults to context scope).

        Returns:
            True if access is allowed.
        """
        return self._access_policy.can_access(
            self.agent_id,
            scope or self.scope,
            permission,
        )

    def _audit_query(
        self,
        query_type: str,
        entity_id: Optional[str] = None,
        event_type: Optional[str] = None,
        result_count: int = 0,
    ) -> None:
        """Log a query for audit purposes."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": self.agent_id,
            "process_id": self.process_id,
            "query_type": query_type,
            "entity_id": entity_id,
            "event_type": event_type,
            "result_count": result_count,
            "scope": self.scope,
        }
        self._query_audit_log.append(entry)

        # Keep only last 500 queries
        if len(self._query_audit_log) > 500:
            self._query_audit_log = self._query_audit_log[-500:]

        log.debug(
            "Query audit: %s by %s (results: %d)",
            query_type, self.agent_id, result_count,
        )

    def get_query_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent query audit log entries."""
        return self._query_audit_log[-limit:]

    # -- event replay -------------------------------------------------------

    def replay_events(
        self,
        entity_id: Optional[str] = None,
        event_type: Optional[str] = None,
        as_of: Optional[datetime] = None,
        replay_handler: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Replay events to rebuild state or for debugging.

        Args:
            entity_id: Optional entity to replay events for.
            event_type: Optional event type filter.
            as_of: Optional point-in-time to replay up to.
            replay_handler: Optional callback for each event.

        Returns:
            Dictionary with replay statistics.

        Usage:
            # Replay all events for an entity
            stats = ctx.replay_events(entity_id="inv-123")
            print(f"Replayed {stats['events_replayed']} events")

            # Replay with custom handler
            def my_handler(event):
                print(f"Event: {event['type']}")
            ctx.replay_events(replay_handler=my_handler)
        """
        events = self.query(
            entity_id=entity_id,
            event_type=event_type,
            as_of=as_of,
            limit=10000,
        )

        replayed = 0
        errors = 0

        for event in events:
            try:
                if replay_handler:
                    replay_handler(event)
                replayed += 1
            except Exception:
                errors += 1
                log.exception("Error replaying event %s", event.get("id", "unknown"))

        return {
            "events_replayed": replayed,
            "errors": errors,
            "entity_id": entity_id,
            "event_type": event_type,
            "as_of": as_of.isoformat() if as_of else None,
        }

    def rebuild_entity_state(self, entity_id: str, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        """Rebuild entity state by replaying its events.

        Args:
            entity_id: Entity to rebuild state for.
            as_of: Optional point-in-time to rebuild state at.

        Returns:
            Rebuilt entity state with metadata.

        Usage:
            state = ctx.rebuild_entity_state("inv-123")
            print(f"Entity type: {state['type']}")
            print(f"Attributes: {state['attributes']}")
        """
        events = self.timeline(entity_id, as_of=as_of)

        if not events:
            return {
                "entity_id": entity_id,
                "type": None,
                "attributes": {},
                "version": 0,
                "events_replayed": 0,
            }

        # Build state by applying events in order
        state: Dict[str, Any] = {}
        entity_type: Optional[str] = None

        for event in events:
            entity_type = event.get("type")
            event_data = event.get("data", {})

            # Apply event to state (simple merge - can be customized)
            if event["type"].endswith(".received"):
                # Initial event - set all fields
                state.update(event_data)
            elif event["type"].endswith(".updated"):
                # Update event - merge fields
                state.update(event_data)
            elif event["type"].endswith(".validated"):
                # Validation event - add validation fields
                state["validation"] = event_data
            elif event["type"].endswith(".completed"):
                # Completion event - mark as done
                state["status"] = "completed"
                state.update(event_data)
            else:
                # Default: merge data
                state.update(event_data)

        return {
            "entity_id": entity_id,
            "type": entity_type,
            "attributes": state,
            "version": len(events),
            "events_replayed": len(events),
            "as_of": as_of.isoformat() if as_of else None,
        }

    def export_events(
        self,
        entity_id: Optional[str] = None,
        event_type: Optional[str] = None,
        format: str = "json",
    ) -> str:
        """Export events for backup or migration.

        Args:
            entity_id: Optional entity filter.
            event_type: Optional type filter.
            format: Output format ("json" or "ndjson").

        Returns:
            Serialized events as string.
        """
        import json

        events = self.query(entity_id=entity_id, event_type=event_type, limit=10000)

        if format == "ndjson":
            # Newline-delimited JSON (one JSON object per line)
            return "\n".join(json.dumps(e) for e in events)
        else:
            # Standard JSON array
            return json.dumps(events, indent=2, default=str)

    # -- schema management --------------------------------------------------

    def register_event_schema(
        self, event_type: str, schema: Type[EventSchema], strict: bool = None
    ) -> None:
        """Register a Pydantic schema for an event type.

        Args:
            event_type: Dotted event name (e.g. "invoice.received").
            schema: Pydantic model class for validation.
            strict: If True, reject unknown fields.
        """
        self._schema_registry.register(event_type, schema, strict)

    def set_schema_strict_mode(self, strict: bool) -> None:
        """Set global strict mode for schema validation."""
        self._schema_registry.set_strict_mode(strict)

    # -- emit events --------------------------------------------------------

    def emit(
        self,
        event_type: str,
        data: Dict[str, Any],
        entity_id: Optional[str] = None,
        relation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        caused_by: Optional[Sequence[Event]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Event:
        """Emit an event into the process context.

        Args:
            event_type: Dotted event name (e.g. "invoice.received").
            data: Event payload.
            entity_id: Optional entity this event affects.
            relation_id: Optional relation this event affects.
            metadata: Arbitrary metadata.
            caused_by: Parent events that caused this one (builds the DAG).
            idempotency_key: Optional key to prevent duplicate events.

        Returns:
            The persisted Event object.
        """
        with measure_time(self._metrics, "emit", {"type": event_type}):
            # Check for existing event with same idempotency key
            if idempotency_key:
                existing = self._store.get_event_by_idempotency_key(
                    self.process_id, idempotency_key
                )
                if existing:
                    log.debug(
                        "Idempotency key already used: %s (returning existing event %s)",
                        idempotency_key, existing["id"][:8],
                    )
                    self._metrics.increment("emit.idempotent", {"type": event_type})
                    # Reconstruct Event from existing record
                    return Event(
                        id=existing["id"],
                        type=existing["type"],
                        process_id=existing["process_id"],
                        data=existing["data"],
                        agent_id=existing["agent_id"],
                        entity_id=existing["entity_id"],
                        relation_id=existing["relation_id"],
                        scope=existing["scope"],
                        timestamp=existing["timestamp"],
                        metadata=existing["metadata"],
                    )

            # Validate data against registered schema
            validated_data = self._schema_registry.validate(event_type, data)

            parent_ids = tuple(e.id for e in caused_by) if caused_by else ()

            event = Event(
                id=generate_id(),
                type=event_type,
                process_id=self.process_id,
                data=validated_data,
                agent_id=self.agent_id,
                entity_id=entity_id,
                relation_id=relation_id,
                scope=self.scope,
                metadata=metadata or {},
                parent_ids=parent_ids,
            )

            # 1. Persist to source of truth
            self._store.save_event(event, idempotency_key=idempotency_key)

            # 2. Project to graph (best-effort)
            if self._projector:
                self._projector.project_event(event)

            # 3. Notify subscribers
            self._router.notify_subscribers(event)

            # 4. Evaluate routing rules
            decision = self._router.evaluate(event)
            if decision:
                self._persist_routing_decision(decision, parent_event=event)

            log.debug("Emitted: %s (type=%s, entity=%s)", event.id[:8], event_type, entity_id)
            self._metrics.increment("emit.success", {"type": event_type})
            return event

    def batch_emit(
        self, events_spec: List[Dict[str, Any]]
    ) -> List[Event]:
        """Atomically emit multiple events in a single transaction.

        Each spec is a dict with keys: event_type, data, and optionally
        entity_id, relation_id, metadata.
        """
        events = []
        for spec in events_spec:
            event = Event(
                id=generate_id(),
                type=spec["event_type"],
                process_id=self.process_id,
                data=spec["data"],
                agent_id=self.agent_id,
                entity_id=spec.get("entity_id"),
                relation_id=spec.get("relation_id"),
                scope=self.scope,
                metadata=spec.get("metadata", {}),
            )
            events.append(event)

        self._store.save_events(events)

        # Best-effort graph projection
        if self._projector:
            for ev in events:
                self._projector.project_event(ev)

        return events

    def _persist_routing_decision(
        self, decision: RoutingDecision, parent_event: Event
    ) -> None:
        """Save a routing decision as a child event (no re-evaluation)."""
        decision_event = Event(
            id=generate_id(),
            type="routing.decision",
            process_id=self.process_id,
            data=decision.to_dict(),
            agent_id="system.router",
            entity_id=parent_event.entity_id,
            scope=self.scope,
            parent_ids=(parent_event.id,),
        )
        self._store.save_event(decision_event)
        if self._projector:
            self._projector.project_event(decision_event)

    # -- query events -------------------------------------------------------

    def query(
        self,
        entity_id: Optional[str] = None,
        event_type: Optional[str] = None,
        scope: Optional[str] = None,
        as_of: Optional[datetime] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query events in this process with optional filters."""
        result = self._store.query_events(
            self.process_id,
            entity_id=entity_id,
            event_type=event_type,
            scope=scope or self.scope,
            as_of=as_of,
            limit=limit,
            offset=offset,
        )
        self._audit_query("query", entity_id, event_type, len(result))
        return result

    def timeline(self, entity_id: str, as_of: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Get the full ordered event history for an entity."""
        result = self._store.query_events(
            self.process_id,
            entity_id=entity_id,
            as_of=as_of,
        )
        self._audit_query("timeline", entity_id, None, len(result))
        return result

    # -- entity snapshots ---------------------------------------------------

    def save_entity(self, entity: Entity) -> None:
        """Save a versioned entity snapshot."""
        self._store.save_entity(entity)
        if self._projector:
            self._projector.project_entity(entity)

    def get_entity(
        self, entity_id: str, as_of: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """Retrieve the latest entity state (or state at a point in time)."""
        return self._store.get_entity(entity_id, as_of=as_of)

    # -- relations ----------------------------------------------------------

    def save_relation(self, relation: Relation) -> None:
        """Persist a typed relation between entities."""
        self._store.save_relation(relation)
        if self._projector:
            self._projector.project_relation(relation)

    # -- causal DAG ---------------------------------------------------------

    def causal_parents(self, event_id: str) -> List[str]:
        """Get the events that caused this event."""
        return self._store.get_causal_parents(event_id)

    def causal_children(self, event_id: str) -> List[str]:
        """Get the events caused by this event."""
        return self._store.get_causal_children(event_id)

    def causal_chain(self, event_id: str, max_depth: int = 10) -> List[Dict[str, Any]]:
        """Walk the full causal DAG via Neo4j (if available)."""
        if self._projector:
            return self._projector.get_causal_chain(event_id, max_depth=max_depth)
        return []

    # -- graph queries ------------------------------------------------------

    def lineage(self, entity_id: str, max_depth: int = 20) -> List[Dict[str, Any]]:
        """Get Neo4j lineage for an entity (if available)."""
        if self._projector:
            return self._projector.get_lineage(entity_id, max_depth=max_depth)
        return []

    def cypher(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Execute a raw Cypher query against Neo4j."""
        if self._projector:
            return self._projector.run_cypher(query, params)
        return []

    # -- pub/sub convenience ------------------------------------------------

    def subscribe(self, event_type: str, callback: Callable[[Event], None]) -> None:
        """Subscribe to events of a given type."""
        self._router.subscribe(event_type, callback)
