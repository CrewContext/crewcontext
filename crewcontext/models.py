"""Core data models for CrewContext.

Immutable, validated, timezone-aware. These are the atoms of the system.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, List, Optional, Tuple


def generate_id() -> str:
    """Generate a URL-safe UUID4 identifier."""
    return str(uuid.uuid4())


def _now() -> datetime:
    """Timezone-aware UTC now. Never naive."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Entity — a business object with temporal validity and versioning
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Entity:
    """A business object tracked across its lifecycle.

    Entities are versioned via snapshots — each mutation creates a new
    snapshot row rather than overwriting, preserving full history.
    """
    id: str
    type: str
    attributes: Dict[str, Any]
    scope: str = "default"
    version: int = 1
    valid_from: datetime = field(default_factory=_now)
    valid_to: Optional[datetime] = None
    created_at: datetime = field(default_factory=_now)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Entity.id cannot be empty")
        if not self.type:
            raise ValueError("Entity.type cannot be empty")

    def __repr__(self):
        return f"Entity(id={self.id!r}, type={self.type!r}, version={self.version})"


# ---------------------------------------------------------------------------
# Relation — a typed, directed edge between two entities
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Relation:
    """A typed, directed relationship between two entities.

    Examples: invoice BELONGS_TO vendor, payment SETTLES invoice.
    """
    id: str
    type: str
    from_entity_id: str
    to_entity_id: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    scope: str = "default"
    valid_from: datetime = field(default_factory=_now)
    valid_to: Optional[datetime] = None
    provenance: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.type:
            raise ValueError("Relation.type cannot be empty")
        if self.from_entity_id == self.to_entity_id:
            raise ValueError("Self-referencing relations are not allowed")

    def __repr__(self):
        return f"Relation(id={self.id!r}, type={self.type!r}, from={self.from_entity_id!r}, to={self.to_entity_id!r})"


# ---------------------------------------------------------------------------
# Event — an immutable fact about the process
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Event:
    """An immutable fact emitted by an agent during a process.

    Events are the source of truth. They are append-only — once written,
    never modified or deleted.

    Causality is tracked via `parent_ids`: every event can declare which
    prior events caused it, forming a Directed Acyclic Graph (DAG).
    """
    id: str
    type: str
    process_id: str
    data: Dict[str, Any]
    agent_id: str
    entity_id: Optional[str] = None
    relation_id: Optional[str] = None
    scope: str = "default"
    timestamp: datetime = field(default_factory=_now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_ids: Tuple[str, ...] = ()

    def __post_init__(self):
        if not self.type:
            raise ValueError("Event.type cannot be empty")
        if not self.process_id:
            raise ValueError("Event.process_id cannot be empty")
        if not self.agent_id:
            raise ValueError("Event.agent_id cannot be empty")

    def __repr__(self):
        return f"Event(id={self.id!r}, type={self.type!r}, entity={self.entity_id!r})"


# ---------------------------------------------------------------------------
# RoutingDecision — serializable record of a routing evaluation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RoutingDecision:
    """The outcome of evaluating an event against routing rules.

    Stored as a first-class event so decisions are auditable.
    """
    event_id: str
    rule_name: str
    action: str
    priority: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "rule_name": self.rule_name,
            "action": self.action,
            "priority": self.priority,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }

    def __repr__(self):
        return f"RoutingDecision(event={self.event_id[:8]}..., rule={self.rule_name!r}, action={self.action!r})"
