"""Unit tests for the PolicyRouter."""
import pytest

from crewcontext.models import Event, generate_id
from crewcontext.router import (
    PolicyRouter,
    all_of,
    any_of,
    none_of,
    data_field_gt,
    data_field_eq,
    data_fields_differ,
    event_type_is,
)


def _make_event(**overrides):
    """Helper to create test events with minimal boilerplate."""
    defaults = dict(
        id=generate_id(), type="test.event", process_id="test",
        data={}, agent_id="test-agent",
    )
    defaults.update(overrides)
    return Event(**defaults)


@pytest.fixture
def router():
    return PolicyRouter()


class TestRuleManagement:
    def test_add_rule(self, router):
        router.add_rule("r1", lambda e: True, "act1", priority=5)
        rules = router.get_rules()
        assert len(rules) == 1
        assert rules[0]["name"] == "r1"
        assert rules[0]["enabled"] is True

    def test_remove_rule(self, router):
        router.add_rule("r1", lambda e: True, "act1")
        assert router.remove_rule("r1") is True
        assert len(router.get_rules()) == 0

    def test_remove_nonexistent(self, router):
        assert router.remove_rule("nope") is False

    def test_disable_enable(self, router):
        router.add_rule("r1", lambda e: True, "act1")
        router.disable_rule("r1")
        assert router.get_rules()[0]["enabled"] is False
        router.enable_rule("r1")
        assert router.get_rules()[0]["enabled"] is True


class TestEvaluation:
    def test_matching_rule(self, router):
        router.add_rule(
            "high-value",
            data_field_gt("amount", 1000),
            "route-to-senior",
            priority=10,
        )
        event = _make_event(data={"amount": 1500})
        decision = router.evaluate(event)
        assert decision is not None
        assert decision.rule_name == "high-value"
        assert decision.action == "route-to-senior"

    def test_no_match(self, router):
        router.add_rule(
            "high-value",
            data_field_gt("amount", 1000),
            "route-to-senior",
        )
        event = _make_event(data={"amount": 500})
        assert router.evaluate(event) is None

    def test_priority_ordering(self, router):
        router.add_rule("low", lambda e: True, "low-action", priority=1)
        router.add_rule("high", lambda e: True, "high-action", priority=10)
        event = _make_event()
        decision = router.evaluate(event)
        assert decision.rule_name == "high"

    def test_disabled_rule_skipped(self, router):
        router.add_rule("r1", lambda e: True, "act1", priority=10)
        router.disable_rule("r1")
        event = _make_event()
        assert router.evaluate(event) is None

    def test_internal_events_skipped(self, router):
        """routing.decision events must never be re-evaluated."""
        router.add_rule("catch-all", lambda e: True, "act1")
        event = _make_event(type="routing.decision")
        assert router.evaluate(event) is None

    def test_broken_condition_logged_not_fatal(self, router):
        def explode(e):
            raise RuntimeError("boom")
        router.add_rule("broken", explode, "act1", priority=10)
        router.add_rule("fallback", lambda e: True, "fallback-act", priority=1)
        event = _make_event()
        decision = router.evaluate(event)
        assert decision.rule_name == "fallback"


class TestConditionCombinators:
    def test_all_of(self):
        cond = all_of(
            data_field_gt("amount", 1000),
            event_type_is("invoice.received"),
        )
        assert cond(_make_event(type="invoice.received", data={"amount": 2000}))
        assert not cond(_make_event(type="invoice.received", data={"amount": 500}))

    def test_any_of(self):
        cond = any_of(
            data_field_eq("status", "urgent"),
            data_field_gt("amount", 10000),
        )
        assert cond(_make_event(data={"status": "urgent", "amount": 100}))
        assert cond(_make_event(data={"amount": 20000}))
        assert not cond(_make_event(data={"status": "normal", "amount": 100}))

    def test_none_of(self):
        cond = none_of(
            data_field_eq("status", "cancelled"),
            data_field_eq("status", "rejected"),
        )
        assert cond(_make_event(data={"status": "approved"}))
        assert not cond(_make_event(data={"status": "cancelled"}))

    def test_data_fields_differ(self):
        cond = data_fields_differ("vendor_id", "expected_vendor_id")
        assert cond(_make_event(data={"vendor_id": "V1", "expected_vendor_id": "V2"}))
        assert not cond(_make_event(data={"vendor_id": "V1", "expected_vendor_id": "V1"}))


class TestPubSub:
    def test_subscribe_and_notify(self, router):
        received = []
        router.subscribe("test.event", lambda e: received.append(e))
        event = _make_event()
        notified = router.notify_subscribers(event)
        assert len(received) == 1
        assert received[0].id == event.id
        assert len(notified) == 1

    def test_no_cross_type_notification(self, router):
        received = []
        router.subscribe("other.type", lambda e: received.append(e))
        event = _make_event(type="test.event")
        router.notify_subscribers(event)
        assert len(received) == 0

    def test_broken_subscriber_doesnt_block_others(self, router):
        received = []
        def explode(e):
            raise RuntimeError("boom")
        router.subscribe("test.event", explode)
        router.subscribe("test.event", lambda e: received.append(e))
        event = _make_event()
        router.notify_subscribers(event)
        assert len(received) == 1
