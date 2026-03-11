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
    ):
        self.process_id = process_id
        self.agent_id = agent_id
        self.scope = scope

        self._metrics = MetricsCollector(service_name=f"crewcontext.{process_id[:8]}")
        self._store = PostgresStore(db_url, metrics=self._metrics)
        self._projector = Neo4jProjector(metrics=self._metrics) if enable_neo4j else None
        self._router = PolicyRouter()
        self._schema_registry = SchemaRegistry()
        self._connected = False

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
        return self._store.query_events(
            self.process_id,
            entity_id=entity_id,
            event_type=event_type,
            scope=scope or self.scope,
            as_of=as_of,
            limit=limit,
            offset=offset,
        )

    def timeline(self, entity_id: str, as_of: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Get the full ordered event history for an entity."""
        return self._store.query_events(
            self.process_id,
            entity_id=entity_id,
            as_of=as_of,
        )

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
