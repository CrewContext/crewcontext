"""Projector — projects events from the source-of-truth store into Neo4j.

Best-effort: if Neo4j is down, events are still safe in PostgreSQL.
Failures are logged, never raised to callers.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..models import Entity, Event, Relation
from .neo4j import Neo4jStore

log = logging.getLogger(__name__)


class Neo4jProjector:
    """Projects events, entities, and relations into Neo4j.

    Usage:
        projector = Neo4jProjector()
        projector.connect()       # can fail — caller decides policy
        projector.project_event(event)  # safe even if not connected
    """

    def __init__(self, neo4j_store: Optional[Neo4jStore] = None):
        self.store = neo4j_store or Neo4jStore()
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def connect(self) -> bool:
        """Attempt connection. Returns True if successful, False otherwise."""
        try:
            self.store.connect()
            self.store.init_schema()
            self._available = True
            return True
        except Exception:
            log.warning("Neo4j not available — graph projections disabled")
            self._available = False
            return False

    def close(self) -> None:
        try:
            self.store.close()
        except Exception:
            pass
        self._available = False

    # -- projection ---------------------------------------------------------

    def project_event(self, event: Event) -> bool:
        """Project a single event to Neo4j. Returns True on success."""
        if not self._available:
            return False
        try:
            self.store.create_event_node(
                event_id=event.id,
                event_type=event.type,
                process_id=event.process_id,
                agent_id=event.agent_id,
                scope=event.scope,
                timestamp=event.timestamp.isoformat(),
                data=event.data,
            )
            if event.entity_id:
                self.store.link_event_to_entity(event.id, event.entity_id)
            # Project causal links
            for parent_id in event.parent_ids:
                self.store.link_causal(parent_id, event.id)
            return True
        except Exception:
            log.exception("Failed to project event %s to Neo4j", event.id[:8])
            return False

    def project_entity(self, entity: Entity) -> bool:
        if not self._available:
            return False
        try:
            self.store.create_entity_node(
                entity_id=entity.id,
                entity_type=entity.type,
                attributes=entity.attributes,
            )
            return True
        except Exception:
            log.exception("Failed to project entity %s to Neo4j", entity.id[:8])
            return False

    def project_relation(self, relation: Relation) -> bool:
        if not self._available:
            return False
        try:
            self.store.create_typed_relation(
                from_entity_id=relation.from_entity_id,
                to_entity_id=relation.to_entity_id,
                rel_type=relation.type,
                rel_id=relation.id,
                attributes=relation.attributes,
            )
            return True
        except Exception:
            log.exception("Failed to project relation %s to Neo4j", relation.id[:8])
            return False

    # -- queries (pass-through) ---------------------------------------------

    def get_lineage(
        self, entity_id: str, max_depth: int = 20
    ) -> List[Dict[str, Any]]:
        if not self._available:
            return []
        return self.store.get_lineage(entity_id, max_depth=max_depth)

    def get_causal_chain(
        self, event_id: str, max_depth: int = 10
    ) -> List[Dict[str, Any]]:
        if not self._available:
            return []
        return self.store.get_causal_chain(event_id, max_depth=max_depth)

    def run_cypher(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        if not self._available:
            return []
        return self.store.run_cypher(query, params)
