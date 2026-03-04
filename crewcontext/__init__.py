"""CrewContext — Context coordination layer for multi-agent workflows.

Usage:
    from crewcontext import ProcessContext, Entity, Event, Relation

    with ProcessContext(process_id="p1", agent_id="agent-1") as ctx:
        event = ctx.emit("invoice.received", {"amount": 5000}, entity_id="inv-1")
"""
from .context import ProcessContext
from .models import Entity, Event, Relation, RoutingDecision, generate_id
from .router import (
    PolicyRouter,
    all_of,
    any_of,
    none_of,
    data_field_eq,
    data_field_gt,
    data_field_ne,
    data_fields_differ,
    event_type_is,
)

__version__ = "0.1.0"
__all__ = [
    "ProcessContext",
    "Entity",
    "Event",
    "Relation",
    "RoutingDecision",
    "generate_id",
    "PolicyRouter",
    "all_of",
    "any_of",
    "none_of",
    "data_field_eq",
    "data_field_gt",
    "data_field_ne",
    "data_fields_differ",
    "event_type_is",
]
