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
from .schema import EventSchema, SchemaRegistry, ValidationError
from .metrics import MetricsCollector
from .health import HealthChecker, HealthCheckResult, HealthStatus
from .security import AccessPolicy, Permission, Role, AccessDecision
from .encryption import EncryptionManager, EncryptedStore
from .secrets import SecretsManager, secret, require_secret

__version__ = "0.2.0"
__all__ = [
    # Core API
    "ProcessContext",
    # Models
    "Entity",
    "Event",
    "Relation",
    "RoutingDecision",
    "generate_id",
    # Router
    "PolicyRouter",
    "all_of",
    "any_of",
    "none_of",
    "data_field_eq",
    "data_field_gt",
    "data_field_ne",
    "data_fields_differ",
    "event_type_is",
    # Schema validation
    "EventSchema",
    "SchemaRegistry",
    "ValidationError",
    # Observability (Phase 2)
    "MetricsCollector",
    "HealthChecker",
    "HealthCheckResult",
    "HealthStatus",
    # Security (Phase 3)
    "AccessPolicy",
    "Permission",
    "Role",
    "AccessDecision",
    "EncryptionManager",
    "EncryptedStore",
    "SecretsManager",
    "secret",
    "require_secret",
]
