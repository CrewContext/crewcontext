"""Abstract storage interface for CrewContext."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from ..models import Entity, Event, Relation


class Store(ABC):
    """Contract that every storage backend must implement.

    Design principles:
    - Events are append-only (no update, no delete).
    - Entities are versioned via snapshots.
    - Queries support temporal filtering (as_of) and scoping.
    - Pagination via limit/offset to prevent OOM.
    """

    # -- lifecycle ----------------------------------------------------------
    @abstractmethod
    def connect(self) -> None:
        """Open connection(s) to the backing store."""

    @abstractmethod
    def close(self) -> None:
        """Release all connections gracefully."""

    @abstractmethod
    def init_schema(self) -> None:
        """Create tables / indexes if they don't exist."""

    # -- events -------------------------------------------------------------
    @abstractmethod
    def save_event(self, event: Event) -> None:
        """Persist a single event (idempotent on event.id)."""

    @abstractmethod
    def save_events(self, events: Sequence[Event]) -> None:
        """Persist multiple events in a single atomic transaction."""

    @abstractmethod
    def query_events(
        self,
        process_id: str,
        *,
        entity_id: Optional[str] = None,
        event_type: Optional[str] = None,
        scope: Optional[str] = None,
        as_of: Optional[datetime] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query events with temporal, scope, and pagination support."""

    @abstractmethod
    def get_event_by_idempotency_key(
        self, process_id: str, idempotency_key: str
    ) -> Optional[Dict[str, Any]]:
        """Retrieve event by idempotency key (for deduplication)."""

    # -- entities -----------------------------------------------------------
    @abstractmethod
    def save_entity(self, entity: Entity) -> None:
        """Persist an entity snapshot (new version)."""

    @abstractmethod
    def get_entity(
        self, entity_id: str, *, as_of: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """Retrieve the entity state, optionally at a point in time."""

    # -- relations ----------------------------------------------------------
    @abstractmethod
    def save_relation(self, relation: Relation) -> None:
        """Persist a relation."""

    # -- causal links -------------------------------------------------------
    @abstractmethod
    def save_causal_links(
        self, event_id: str, parent_ids: Sequence[str]
    ) -> None:
        """Record parent→child causality edges."""

    @abstractmethod
    def get_causal_parents(self, event_id: str) -> List[str]:
        """Return the parent event IDs that caused this event."""

    @abstractmethod
    def get_causal_children(self, event_id: str) -> List[str]:
        """Return the child event IDs caused by this event."""
