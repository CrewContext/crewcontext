"""Neo4j graph database backend.

Provides graph-shaped views of events, entities, and their relationships.
All operations are best-effort — failures are logged, never fatal.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class Neo4jStore:
    """Low-level Neo4j operations.

    Stores events as :Event nodes, entities as :Entity nodes,
    and uses TYPED relationship labels (not generic :R).
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.uri = uri or os.getenv(
            "CREWCONTEXT_NEO4J_URI", "bolt://localhost:7687"
        )
        self.user = user or os.getenv("CREWCONTEXT_NEO4J_USER", "neo4j")
        self.password = password or os.getenv(
            "CREWCONTEXT_NEO4J_PASSWORD", "crewcontext123"
        )
        self._driver = None

    # -- lifecycle ----------------------------------------------------------

    def connect(self) -> None:
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(
            self.uri, auth=(self.user, self.password)
        )
        # Verify connectivity immediately
        self._driver.verify_connectivity()
        log.info("Neo4j connected: %s", self.uri)

    def close(self) -> None:
        if self._driver:
            self._driver.close()
            self._driver = None
            log.info("Neo4j connection closed")

    @property
    def connected(self) -> bool:
        return self._driver is not None

    def _ensure_driver(self):
        if self._driver is None:
            raise RuntimeError("Neo4jStore is not connected — call connect() first")
        return self._driver

    # -- schema -------------------------------------------------------------

    def init_schema(self) -> None:
        driver = self._ensure_driver()
        with driver.session() as session:
            session.run(
                "CREATE CONSTRAINT IF NOT EXISTS "
                "FOR (e:Event) REQUIRE e.id IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT IF NOT EXISTS "
                "FOR (n:Entity) REQUIRE n.id IS UNIQUE"
            )
            session.run(
                "CREATE INDEX IF NOT EXISTS "
                "FOR (e:Event) ON (e.process_id)"
            )
            session.run(
                "CREATE INDEX IF NOT EXISTS "
                "FOR (e:Event) ON (e.type)"
            )
        log.info("Neo4j schema initialised")

    # -- write operations ---------------------------------------------------

    def run_cypher(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        driver = self._ensure_driver()
        with driver.session() as session:
            result = session.run(query, params or {})
            return [record.data() for record in result]

    def create_event_node(
        self,
        event_id: str,
        event_type: str,
        process_id: str,
        agent_id: str,
        scope: str,
        timestamp: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create an :Event node with scalar properties (not raw JSON blobs)."""
        props = {
            "id": event_id,
            "type": event_type,
            "process_id": process_id,
            "agent_id": agent_id,
            "scope": scope,
            "timestamp": timestamp,
        }
        # Flatten top-level data keys as prefixed properties for queryability
        if data:
            for k, v in data.items():
                if isinstance(v, (str, int, float, bool)):
                    props[f"d_{k}"] = v

        set_clause = ", ".join(f"e.{k} = ${k}" for k in props)
        q = f"MERGE (e:Event {{id: $id}}) SET {set_clause}"
        self.run_cypher(q, props)

    def create_entity_node(
        self,
        entity_id: str,
        entity_type: str,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        props = {"id": entity_id, "type": entity_type}
        if attributes:
            for k, v in attributes.items():
                if isinstance(v, (str, int, float, bool)):
                    props[f"a_{k}"] = v

        set_clause = ", ".join(f"n.{k} = ${k}" for k in props)
        q = f"MERGE (n:Entity {{id: $id}}) SET {set_clause}"
        self.run_cypher(q, props)

    def link_event_to_entity(self, event_id: str, entity_id: str) -> None:
        """Create :AFFECTS relationship from Event to Entity."""
        self.run_cypher(
            "MATCH (e:Event {id: $eid}) "
            "MERGE (n:Entity {id: $nid}) "
            "MERGE (e)-[:AFFECTS]->(n)",
            {"eid": event_id, "nid": entity_id},
        )

    def create_typed_relation(
        self,
        from_entity_id: str,
        to_entity_id: str,
        rel_type: str,
        rel_id: str,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create a TYPED relationship between entities.

        Uses APOC-free approach: parameterised relationship type via
        separate Cypher per type (Neo4j doesn't allow parameterised rel types).
        Sanitises rel_type to uppercase alphanumeric + underscore.
        """
        safe_type = "".join(
            c if c.isalnum() or c == "_" else "_"
            for c in rel_type.upper()
        )
        props = {"fid": from_entity_id, "tid": to_entity_id, "rid": rel_id}
        if attributes:
            for k, v in attributes.items():
                if isinstance(v, (str, int, float, bool)):
                    props[f"r_{k}"] = v

        prop_set = ""
        rel_props = {k: v for k, v in props.items() if k.startswith("r_")}
        if rel_props:
            assignments = ", ".join(f"r.{k} = ${k}" for k in rel_props)
            prop_set = f" SET r.id = $rid, {assignments}"
        else:
            prop_set = " SET r.id = $rid"

        q = (
            f"MATCH (a:Entity {{id: $fid}}) "
            f"MATCH (b:Entity {{id: $tid}}) "
            f"MERGE (a)-[r:{safe_type}]->(b)"
            f"{prop_set}"
        )
        self.run_cypher(q, props)

    def link_causal(self, parent_event_id: str, child_event_id: str) -> None:
        """Create :CAUSED relationship between events for DAG lineage."""
        self.run_cypher(
            "MATCH (p:Event {id: $pid}) "
            "MATCH (c:Event {id: $cid}) "
            "MERGE (p)-[:CAUSED]->(c)",
            {"pid": parent_event_id, "cid": child_event_id},
        )

    # -- read operations ----------------------------------------------------

    def get_lineage(
        self, entity_id: str, max_depth: int = 20
    ) -> List[Dict[str, Any]]:
        """Get event lineage for an entity with BOUNDED depth."""
        return self.run_cypher(
            "MATCH (e:Event)-[:AFFECTS]->(n:Entity {id: $id}) "
            "RETURN e.id AS id, e.type AS type, e.agent_id AS agent_id, "
            "       e.timestamp AS timestamp, e.process_id AS process_id "
            "ORDER BY e.timestamp ASC "
            "LIMIT $limit",
            {"id": entity_id, "limit": max_depth},
        )

    def get_causal_chain(
        self, event_id: str, max_depth: int = 10
    ) -> List[Dict[str, Any]]:
        """Walk the causal DAG backwards from an event."""
        return self.run_cypher(
            "MATCH path = (ancestor:Event)-[:CAUSED*0..$depth]->"
            "(target:Event {id: $id}) "
            "UNWIND nodes(path) AS n "
            "WITH DISTINCT n "
            "RETURN n.id AS id, n.type AS type, n.agent_id AS agent_id, "
            "       n.timestamp AS timestamp "
            "ORDER BY n.timestamp ASC",
            {"id": event_id, "depth": max_depth},
        )
