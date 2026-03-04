"""Integration tests for PostgreSQL store.

These tests require a running PostgreSQL instance.
They use unique process_ids for isolation — no cleanup needed.
"""
import pytest
from datetime import timedelta

from crewcontext.models import Entity, Event, Relation, generate_id, _now


class TestEventPersistence:
    def test_save_and_query(self, pg_store, unique_process_id):
        event = Event(
            id=generate_id(), type="test.event",
            process_id=unique_process_id, data={"key": "value"},
            agent_id="test-agent", entity_id="ent-1",
        )
        pg_store.save_event(event)
        results = pg_store.query_events(unique_process_id, entity_id="ent-1")
        assert len(results) >= 1
        assert results[0]["type"] == "test.event"

    def test_idempotent_save(self, pg_store, unique_process_id):
        eid = generate_id()
        event = Event(
            id=eid, type="test.event",
            process_id=unique_process_id, data={"x": 1},
            agent_id="test-agent",
        )
        pg_store.save_event(event)
        pg_store.save_event(event)  # duplicate — should be ignored
        results = pg_store.query_events(unique_process_id)
        matching = [r for r in results if r["id"] == eid]
        assert len(matching) == 1

    def test_batch_save(self, pg_store, unique_process_id):
        events = [
            Event(
                id=generate_id(), type=f"batch.{i}",
                process_id=unique_process_id, data={"i": i},
                agent_id="test-agent",
            )
            for i in range(5)
        ]
        pg_store.save_events(events)
        results = pg_store.query_events(unique_process_id)
        assert len(results) == 5

    def test_query_with_scope_filter(self, pg_store, unique_process_id):
        e1 = Event(
            id=generate_id(), type="scoped.event",
            process_id=unique_process_id, data={},
            agent_id="a1", scope="team-a",
        )
        e2 = Event(
            id=generate_id(), type="scoped.event",
            process_id=unique_process_id, data={},
            agent_id="a2", scope="team-b",
        )
        pg_store.save_event(e1)
        pg_store.save_event(e2)
        results = pg_store.query_events(unique_process_id, scope="team-a")
        assert all(r["scope"] == "team-a" for r in results)

    def test_query_pagination(self, pg_store, unique_process_id):
        for i in range(10):
            pg_store.save_event(Event(
                id=generate_id(), type="page.event",
                process_id=unique_process_id, data={"i": i},
                agent_id="a1",
            ))
        page1 = pg_store.query_events(unique_process_id, limit=3, offset=0)
        page2 = pg_store.query_events(unique_process_id, limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0]["id"] != page2[0]["id"]


class TestTemporalQueries:
    def test_as_of_filtering(self, pg_store, unique_process_id):
        now = _now()
        past = Event(
            id=generate_id(), type="test.past",
            process_id=unique_process_id, data={"v": 1},
            agent_id="a1", timestamp=now - timedelta(hours=1),
        )
        present = Event(
            id=generate_id(), type="test.present",
            process_id=unique_process_id, data={"v": 2},
            agent_id="a1", timestamp=now,
        )
        pg_store.save_event(past)
        pg_store.save_event(present)

        # Query 30 min ago — should only see past event
        results = pg_store.query_events(
            unique_process_id, as_of=now - timedelta(minutes=30)
        )
        types = [r["type"] for r in results]
        assert "test.past" in types
        assert "test.present" not in types

        # Query now+1min — should see both
        results = pg_store.query_events(
            unique_process_id, as_of=now + timedelta(minutes=1)
        )
        types = [r["type"] for r in results]
        assert "test.past" in types
        assert "test.present" in types


class TestEntitySnapshots:
    def test_save_and_get(self, pg_store):
        ent = Entity(
            id=f"ent-{generate_id()[:8]}", type="Invoice",
            attributes={"amount": 1000}, version=1,
        )
        pg_store.save_entity(ent)
        result = pg_store.get_entity(ent.id)
        assert result is not None
        assert result["type"] == "Invoice"

    def test_versioning(self, pg_store):
        eid = f"ent-{generate_id()[:8]}"
        v1 = Entity(id=eid, type="Invoice", attributes={"amount": 1000}, version=1)
        v2 = Entity(id=eid, type="Invoice", attributes={"amount": 1500}, version=2)
        pg_store.save_entity(v1)
        pg_store.save_entity(v2)
        latest = pg_store.get_entity(eid)
        assert latest["version"] == 2


class TestCausalLinks:
    def test_save_and_query_parents(self, pg_store, unique_process_id):
        parent = Event(
            id=generate_id(), type="cause",
            process_id=unique_process_id, data={}, agent_id="a1",
        )
        child = Event(
            id=generate_id(), type="effect",
            process_id=unique_process_id, data={}, agent_id="a1",
            parent_ids=(parent.id,),
        )
        pg_store.save_event(parent)
        pg_store.save_event(child)

        parents = pg_store.get_causal_parents(child.id)
        assert parent.id in parents

    def test_save_and_query_children(self, pg_store, unique_process_id):
        parent = Event(
            id=generate_id(), type="cause",
            process_id=unique_process_id, data={}, agent_id="a1",
        )
        child = Event(
            id=generate_id(), type="effect",
            process_id=unique_process_id, data={}, agent_id="a1",
            parent_ids=(parent.id,),
        )
        pg_store.save_event(parent)
        pg_store.save_event(child)

        children = pg_store.get_causal_children(parent.id)
        assert child.id in children


class TestRelations:
    def test_save_relation(self, pg_store):
        rel = Relation(
            id=generate_id(), type="BELONGS_TO",
            from_entity_id="inv-1", to_entity_id="vendor-1",
            attributes={"since": "2024-01"},
        )
        pg_store.save_relation(rel)
        # No exception = success (relation queries via Neo4j)
