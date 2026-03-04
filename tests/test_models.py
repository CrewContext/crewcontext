"""Unit tests for core data models."""
import pytest
from datetime import timezone

from crewcontext.models import Entity, Event, Relation, RoutingDecision, generate_id


class TestGenerateId:
    def test_returns_string(self):
        assert isinstance(generate_id(), str)

    def test_unique(self):
        ids = {generate_id() for _ in range(100)}
        assert len(ids) == 100


class TestEvent:
    def test_create_minimal(self):
        e = Event(
            id="e1", type="test.event", process_id="p1",
            data={"key": "val"}, agent_id="agent-1",
        )
        assert e.type == "test.event"
        assert e.timestamp.tzinfo is not None  # timezone-aware

    def test_immutable(self):
        e = Event(
            id="e1", type="test.event", process_id="p1",
            data={}, agent_id="agent-1",
        )
        with pytest.raises(AttributeError):
            e.type = "changed"

    def test_parent_ids_default_empty(self):
        e = Event(
            id="e1", type="test.event", process_id="p1",
            data={}, agent_id="agent-1",
        )
        assert e.parent_ids == ()

    def test_parent_ids_tuple(self):
        e = Event(
            id="e1", type="test.event", process_id="p1",
            data={}, agent_id="agent-1", parent_ids=("p1", "p2"),
        )
        assert e.parent_ids == ("p1", "p2")

    def test_validation_empty_type(self):
        with pytest.raises(ValueError, match="Event.type"):
            Event(id="e1", type="", process_id="p1", data={}, agent_id="a1")

    def test_validation_empty_process_id(self):
        with pytest.raises(ValueError, match="process_id"):
            Event(id="e1", type="t", process_id="", data={}, agent_id="a1")

    def test_validation_empty_agent_id(self):
        with pytest.raises(ValueError, match="agent_id"):
            Event(id="e1", type="t", process_id="p1", data={}, agent_id="")


class TestEntity:
    def test_create(self):
        ent = Entity(id="inv-1", type="Invoice", attributes={"amount": 1000})
        assert ent.version == 1
        assert ent.valid_to is None

    def test_immutable(self):
        ent = Entity(id="inv-1", type="Invoice", attributes={})
        with pytest.raises(AttributeError):
            ent.type = "changed"

    def test_validation_empty_id(self):
        with pytest.raises(ValueError, match="Entity.id"):
            Entity(id="", type="Invoice", attributes={})


class TestRelation:
    def test_create(self):
        r = Relation(
            id="r1", type="BELONGS_TO",
            from_entity_id="inv-1", to_entity_id="vendor-1",
        )
        assert r.type == "BELONGS_TO"

    def test_no_self_reference(self):
        with pytest.raises(ValueError, match="Self-referencing"):
            Relation(
                id="r1", type="LOOP",
                from_entity_id="x", to_entity_id="x",
            )


class TestRoutingDecision:
    def test_to_dict(self):
        d = RoutingDecision(
            event_id="e1", rule_name="high-value",
            action="escalate", priority=10,
        )
        out = d.to_dict()
        assert out["rule_name"] == "high-value"
        assert out["action"] == "escalate"
        assert "timestamp" in out
