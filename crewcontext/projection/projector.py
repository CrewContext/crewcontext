"""Projector — projects events from the source-of-truth store into Neo4j.

Best-effort: if Neo4j is down, events are still safe in PostgreSQL.
Failures are tracked with metrics and retry logic.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ..metrics import MetricsCollector, measure_time
from ..models import Entity, Event, Relation
from .neo4j import Neo4jStore

log = logging.getLogger(__name__)


class Neo4jProjector:
    """Projects events, entities, and relations into Neo4j.

    Features:
    - Retry logic with exponential backoff
    - Metrics collection for observability
    - Graceful degradation when Neo4j is unavailable

    Usage:
        projector = Neo4jProjector()
        projector.connect()       # can fail — caller decides policy
        projector.project_event(event)  # safe even if not connected
    """

    def __init__(
        self,
        neo4j_store: Optional[Neo4jStore] = None,
        metrics: Optional[MetricsCollector] = None,
        max_retries: int = 3,
        base_retry_delay: float = 0.1,
    ):
        self.store = neo4j_store or Neo4jStore()
        self.metrics = metrics or MetricsCollector(service_name="neo4j_projector")
        self._available = False
        self._max_retries = max_retries
        self._base_retry_delay = base_retry_delay
        self._consecutive_failures = 0
        self._circuit_breaker_open = False
        self._circuit_breaker_reset_time: Optional[float] = None

    @property
    def available(self) -> bool:
        return self._available

    @property
    def failure_rate(self) -> float:
        """Get current failure rate for monitoring."""
        return self.metrics.get_failure_rate("project", window_seconds=300)

    def connect(self) -> bool:
        """Attempt connection. Returns True if successful, False otherwise."""
        try:
            self.store.connect()
            self.store.init_schema()
            self._available = True
            self._consecutive_failures = 0
            self.metrics.record_success("connect")
            log.info("Neo4j connected: %s", self.store.uri)
            return True
        except Exception as e:
            log.warning("Neo4j not available — graph projections disabled")
            self._available = False
            self.metrics.record_failure("connect", "neo4j", e)
            return False

    def close(self) -> None:
        try:
            self.store.close()
        except Exception:
            pass
        self._available = False

    def _should_retry(self, attempt: int) -> bool:
        """Check if we should retry based on attempt count and circuit breaker."""
        if attempt >= self._max_retries:
            return False
        if self._circuit_breaker_open:
            if self._circuit_breaker_reset_time:
                if time.time() > self._circuit_breaker_reset_time:
                    self._circuit_breaker_open = False
                    self._circuit_breaker_reset_time = None
                    return True
            return False
        return True

    def _handle_failure(self, error: Exception, operation: str, identifier: str) -> None:
        """Handle a failed operation with retry logic and circuit breaker."""
        self._consecutive_failures += 1
        self.metrics.record_failure(operation, identifier, error)

        # Open circuit breaker after 5 consecutive failures
        if self._consecutive_failures >= 5:
            self._circuit_breaker_open = True
            self._circuit_breaker_reset_time = time.time() + 30  # Reset after 30s
            log.warning(
                "Circuit breaker opened for Neo4j projector after %d failures",
                self._consecutive_failures,
            )

    def _handle_success(self, operation: str) -> None:
        """Handle a successful operation."""
        self._consecutive_failures = 0
        self.metrics.record_success(operation)

        # Close circuit breaker on success
        if self._circuit_breaker_open:
            self._circuit_breaker_open = False
            self._circuit_breaker_reset_time = None
            log.info("Circuit breaker closed for Neo4j projector")

    # -- projection ---------------------------------------------------------

    def project_event(self, event: Event) -> bool:
        """Project a single event to Neo4j with retry logic.

        Returns True on success, False on failure (including after all retries).
        """
        if not self._available:
            return False

        operation = "project_event"
        identifier = event.id

        for attempt in range(self._max_retries):
            if not self._should_retry(attempt):
                break

            try:
                # Exponential backoff
                if attempt > 0:
                    delay = self._base_retry_delay * (2 ** (attempt - 1))
                    time.sleep(delay)

                with measure_time(self.metrics, operation):
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

                self._handle_success(operation)
                log.debug("Projected event %s to Neo4j", event.id[:8])
                return True

            except Exception as e:
                self._handle_failure(e, operation, identifier)
                if attempt == self._max_retries - 1:
                    log.exception(
                        "Failed to project event %s to Neo4j after %d retries",
                        event.id[:8], self._max_retries,
                    )

        return False

    def project_entity(self, entity: Entity) -> bool:
        """Project entity to Neo4j with retry logic."""
        if not self._available:
            return False

        operation = "project_entity"
        identifier = entity.id

        for attempt in range(self._max_retries):
            if not self._should_retry(attempt):
                break

            try:
                if attempt > 0:
                    delay = self._base_retry_delay * (2 ** (attempt - 1))
                    time.sleep(delay)

                with measure_time(self.metrics, operation):
                    self.store.create_entity_node(
                        entity_id=entity.id,
                        entity_type=entity.type,
                        attributes=entity.attributes,
                    )

                self._handle_success(operation)
                return True

            except Exception as e:
                self._handle_failure(e, operation, identifier)
                if attempt == self._max_retries - 1:
                    log.exception(
                        "Failed to project entity %s to Neo4j after %d retries",
                        entity.id[:8], self._max_retries,
                    )

        return False

    def project_relation(self, relation: Relation) -> bool:
        """Project relation to Neo4j with retry logic."""
        if not self._available:
            return False

        operation = "project_relation"
        identifier = relation.id

        for attempt in range(self._max_retries):
            if not self._should_retry(attempt):
                break

            try:
                if attempt > 0:
                    delay = self._base_retry_delay * (2 ** (attempt - 1))
                    time.sleep(delay)

                with measure_time(self.metrics, operation):
                    self.store.create_typed_relation(
                        from_entity_id=relation.from_entity_id,
                        to_entity_id=relation.to_entity_id,
                        rel_type=relation.type,
                        rel_id=relation.id,
                        attributes=relation.attributes,
                    )

                self._handle_success(operation)
                return True

            except Exception as e:
                self._handle_failure(e, operation, identifier)
                if attempt == self._max_retries - 1:
                    log.exception(
                        "Failed to project relation %s to Neo4j after %d retries",
                        relation.id[:8], self._max_retries,
                    )

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
