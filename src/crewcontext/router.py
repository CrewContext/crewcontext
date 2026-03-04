"""Deterministic policy router with auditable decisions.

Rules are evaluated in strict priority order (highest first).
Routing decisions are first-class objects that can be persisted.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .models import Event, RoutingDecision

log = logging.getLogger(__name__)

Condition = Callable[[Event], bool]


# ---------------------------------------------------------------------------
# Condition combinators — build complex rules without lambda spaghetti
# ---------------------------------------------------------------------------

def all_of(*conditions: Condition) -> Condition:
    """Match only if ALL conditions are true."""
    def _check(event: Event) -> bool:
        return all(c(event) for c in conditions)
    _check.__name__ = f"all_of({len(conditions)})"
    return _check


def any_of(*conditions: Condition) -> Condition:
    """Match if ANY condition is true."""
    def _check(event: Event) -> bool:
        return any(c(event) for c in conditions)
    _check.__name__ = f"any_of({len(conditions)})"
    return _check


def none_of(*conditions: Condition) -> Condition:
    """Match only if NONE of the conditions are true."""
    def _check(event: Event) -> bool:
        return not any(c(event) for c in conditions)
    _check.__name__ = f"none_of({len(conditions)})"
    return _check


def event_type_is(*types: str) -> Condition:
    """Match events with the given type(s)."""
    type_set = frozenset(types)
    def _check(event: Event) -> bool:
        return event.type in type_set
    _check.__name__ = f"event_type_is({','.join(types)})"
    return _check


def data_field_gt(field_name: str, threshold: float) -> Condition:
    """Match when event.data[field_name] > threshold."""
    def _check(event: Event) -> bool:
        val = event.data.get(field_name)
        return val is not None and val > threshold
    _check.__name__ = f"data_field_gt({field_name},{threshold})"
    return _check


def data_field_eq(field_name: str, value: Any) -> Condition:
    """Match when event.data[field_name] == value."""
    def _check(event: Event) -> bool:
        return event.data.get(field_name) == value
    _check.__name__ = f"data_field_eq({field_name},{value!r})"
    return _check


def data_field_ne(field_name: str, value: Any) -> Condition:
    """Match when event.data[field_name] != value (and both exist)."""
    def _check(event: Event) -> bool:
        return field_name in event.data and event.data[field_name] != value
    _check.__name__ = f"data_field_ne({field_name},{value!r})"
    return _check


def data_fields_differ(field_a: str, field_b: str) -> Condition:
    """Match when two fields in event.data have different values."""
    def _check(event: Event) -> bool:
        a, b = event.data.get(field_a), event.data.get(field_b)
        return a is not None and b is not None and a != b
    _check.__name__ = f"data_fields_differ({field_a},{field_b})"
    return _check


# ---------------------------------------------------------------------------
# RoutingRule
# ---------------------------------------------------------------------------

@dataclass
class RoutingRule:
    name: str
    condition: Condition
    action: str
    priority: int = 0
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# PolicyRouter
# ---------------------------------------------------------------------------

class PolicyRouter:
    """Evaluates events against priority-ordered rules.

    Features:
    - Priority ordering (highest first, stable sort on insertion order).
    - Enable/disable rules at runtime.
    - Pub/sub subscriptions per event type.
    - Structured logging on every evaluation (no silent swallow).
    """

    # Event types that are never re-evaluated to prevent infinite recursion
    INTERNAL_EVENT_TYPES = frozenset({"routing.decision"})

    def __init__(self) -> None:
        self._rules: List[RoutingRule] = []
        self._subscriptions: Dict[str, List[Callable[[Event], None]]] = {}

    # -- rule management ----------------------------------------------------

    def add_rule(
        self,
        name: str,
        condition: Condition,
        action: str,
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        rule = RoutingRule(
            name=name,
            condition=condition,
            action=action,
            priority=priority,
            metadata=metadata or {},
        )
        self._rules.append(rule)
        self._rules.sort(key=lambda r: -r.priority)
        log.debug("Rule added: %s (priority=%d)", name, priority)

    def remove_rule(self, name: str) -> bool:
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        removed = len(self._rules) < before
        if removed:
            log.debug("Rule removed: %s", name)
        return removed

    def enable_rule(self, name: str) -> None:
        for r in self._rules:
            if r.name == name:
                r.enabled = True

    def disable_rule(self, name: str) -> None:
        for r in self._rules:
            if r.name == name:
                r.enabled = False

    def get_rules(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": r.name,
                "action": r.action,
                "priority": r.priority,
                "enabled": r.enabled,
            }
            for r in self._rules
        ]

    # -- evaluation ---------------------------------------------------------

    def evaluate(self, event: Event) -> Optional[RoutingDecision]:
        """Evaluate an event against all enabled rules.

        Returns the first matching RoutingDecision or None.
        Internal event types (routing.decision) are never evaluated
        to prevent infinite recursion.
        """
        if event.type in self.INTERNAL_EVENT_TYPES:
            return None

        for rule in self._rules:
            if not rule.enabled:
                continue
            try:
                if rule.condition(event):
                    decision = RoutingDecision(
                        event_id=event.id,
                        rule_name=rule.name,
                        action=rule.action,
                        priority=rule.priority,
                        metadata=rule.metadata,
                    )
                    log.info(
                        "Routing: event=%s matched rule=%s -> action=%s",
                        event.id[:8], rule.name, rule.action,
                    )
                    return decision
            except Exception:
                log.exception(
                    "Rule '%s' raised an error evaluating event %s",
                    rule.name, event.id[:8],
                )
                continue

        log.debug("No rule matched event %s (type=%s)", event.id[:8], event.type)
        return None

    # -- pub/sub ------------------------------------------------------------

    def subscribe(
        self, event_type: str, callback: Callable[[Event], None]
    ) -> None:
        self._subscriptions.setdefault(event_type, []).append(callback)

    def notify_subscribers(self, event: Event) -> List[str]:
        """Notify all subscribers for this event type.

        Returns list of callback names that were invoked.
        """
        notified: List[str] = []
        for callback in self._subscriptions.get(event.type, []):
            cb_name = getattr(callback, "__name__", "anonymous")
            try:
                callback(event)
                notified.append(cb_name)
            except Exception:
                log.exception(
                    "Subscriber '%s' raised an error for event %s",
                    cb_name, event.id[:8],
                )
        return notified
