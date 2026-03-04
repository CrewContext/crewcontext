"""PostgreSQL storage backend for CrewContext.

Uses psycopg 3 with connection pooling.  All writes are parameterised
(no string interpolation) to prevent SQL injection.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..models import Entity, Event, Relation
from .base import Store

log = logging.getLogger(__name__)

_DEFAULT_DB_URL = "postgresql://crew:crew@localhost:5432/crewcontext"

# ---- Schema DDL -----------------------------------------------------------

_SCHEMA_SQL = """
-- Events: append-only log, source of truth
CREATE TABLE IF NOT EXISTS events (
    id          TEXT        PRIMARY KEY,
    type        TEXT        NOT NULL,
    process_id  TEXT        NOT NULL,
    entity_id   TEXT,
    relation_id TEXT,
    data        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    agent_id    TEXT        NOT NULL,
    scope       TEXT        NOT NULL DEFAULT 'default',
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata    JSONB       NOT NULL DEFAULT '{}'::jsonb
);

-- Entities: versioned snapshots (one row per version)
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT        NOT NULL,
    type        TEXT        NOT NULL,
    version     INTEGER     NOT NULL DEFAULT 1,
    attributes  JSONB       NOT NULL DEFAULT '{}'::jsonb,
    scope       TEXT        NOT NULL DEFAULT 'default',
    valid_from  TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to    TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    provenance  JSONB       NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (id, version)
);

-- Relations
CREATE TABLE IF NOT EXISTS relations (
    id              TEXT        PRIMARY KEY,
    type            TEXT        NOT NULL,
    from_entity_id  TEXT        NOT NULL,
    to_entity_id    TEXT        NOT NULL,
    attributes      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    scope           TEXT        NOT NULL DEFAULT 'default',
    valid_from      TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to        TIMESTAMPTZ,
    provenance      JSONB       NOT NULL DEFAULT '{}'::jsonb
);

-- Causal links: DAG edges  (parent caused child)
CREATE TABLE IF NOT EXISTS causal_links (
    parent_event_id TEXT NOT NULL REFERENCES events(id),
    child_event_id  TEXT NOT NULL REFERENCES events(id),
    PRIMARY KEY (parent_event_id, child_event_id)
);

-- Indexes for the queries we actually run
CREATE INDEX IF NOT EXISTS idx_events_process   ON events (process_id);
CREATE INDEX IF NOT EXISTS idx_events_entity    ON events (entity_id)   WHERE entity_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_type      ON events (type);
CREATE INDEX IF NOT EXISTS idx_events_scope     ON events (scope);
CREATE INDEX IF NOT EXISTS idx_events_ts        ON events (timestamp);
CREATE INDEX IF NOT EXISTS idx_entities_id      ON entities (id, valid_from DESC);
CREATE INDEX IF NOT EXISTS idx_relations_from   ON relations (from_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_to     ON relations (to_entity_id);
CREATE INDEX IF NOT EXISTS idx_causal_parent    ON causal_links (parent_event_id);
CREATE INDEX IF NOT EXISTS idx_causal_child     ON causal_links (child_event_id);
"""


class PostgresStore(Store):
    """Production-grade PostgreSQL backend with connection pooling."""

    def __init__(
        self,
        db_url: Optional[str] = None,
        min_pool: int = 2,
        max_pool: int = 10,
    ):
        self.db_url = db_url or os.getenv(
            "CREWCONTEXT_DB_URL", _DEFAULT_DB_URL
        )
        self._min_pool = min_pool
        self._max_pool = max_pool
        self._pool: Optional[ConnectionPool] = None

    # -- lifecycle ----------------------------------------------------------

    def connect(self) -> None:
        if self._pool is not None:
            return
        self._pool = ConnectionPool(
            self.db_url,
            min_size=self._min_pool,
            max_size=self._max_pool,
            kwargs={"row_factory": dict_row},
        )
        log.info("PostgresStore connected (pool %d–%d)", self._min_pool, self._max_pool)

    def close(self) -> None:
        if self._pool:
            self._pool.close()
            self._pool = None
            log.info("PostgresStore connection pool closed")

    def _ensure_pool(self) -> ConnectionPool:
        if self._pool is None:
            self.connect()
        assert self._pool is not None
        return self._pool

    def init_schema(self) -> None:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            conn.execute(_SCHEMA_SQL)
            conn.commit()
        log.info("Schema initialised")

    # -- events -------------------------------------------------------------

    def save_event(self, event: Event) -> None:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO events
                        (id, type, process_id, entity_id, relation_id,
                         data, agent_id, scope, timestamp, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        event.id, event.type, event.process_id,
                        event.entity_id, event.relation_id,
                        json.dumps(event.data), event.agent_id,
                        event.scope, event.timestamp,
                        json.dumps(event.metadata),
                    ),
                )
                if event.parent_ids:
                    self._insert_causal_links(cur, event.id, event.parent_ids)
            conn.commit()

    def save_events(self, events: Sequence[Event]) -> None:
        """Atomic batch insert — all or nothing."""
        if not events:
            return
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                for ev in events:
                    cur.execute(
                        """
                        INSERT INTO events
                            (id, type, process_id, entity_id, relation_id,
                             data, agent_id, scope, timestamp, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            ev.id, ev.type, ev.process_id,
                            ev.entity_id, ev.relation_id,
                            json.dumps(ev.data), ev.agent_id,
                            ev.scope, ev.timestamp,
                            json.dumps(ev.metadata),
                        ),
                    )
                    if ev.parent_ids:
                        self._insert_causal_links(cur, ev.id, ev.parent_ids)
            conn.commit()

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
        conditions = ["process_id = %s"]
        params: list[Any] = [process_id]

        if entity_id is not None:
            conditions.append("entity_id = %s")
            params.append(entity_id)
        if event_type is not None:
            conditions.append("type = %s")
            params.append(event_type)
        if scope is not None:
            conditions.append("scope = %s")
            params.append(scope)
        if as_of is not None:
            conditions.append("timestamp <= %s")
            params.append(as_of)

        where = " AND ".join(conditions)
        sql = (
            f"SELECT id, type, process_id, entity_id, relation_id, "
            f"data, agent_id, scope, timestamp, metadata "
            f"FROM events WHERE {where} "
            f"ORDER BY timestamp ASC "
            f"LIMIT %s OFFSET %s"
        )
        params.extend([limit, offset])

        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return rows

    # -- entities -----------------------------------------------------------

    def save_entity(self, entity: Entity) -> None:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO entities
                    (id, type, version, attributes, scope,
                     valid_from, valid_to, created_at, provenance)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id, version) DO NOTHING
                """,
                (
                    entity.id, entity.type, entity.version,
                    json.dumps(entity.attributes), entity.scope,
                    entity.valid_from, entity.valid_to,
                    entity.created_at, json.dumps(entity.provenance),
                ),
            )
            conn.commit()

    def get_entity(
        self, entity_id: str, *, as_of: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        pool = self._ensure_pool()
        if as_of is not None:
            sql = """
                SELECT id, type, version, attributes, scope,
                       valid_from, valid_to, created_at, provenance
                FROM entities
                WHERE id = %s AND valid_from <= %s
                      AND (valid_to IS NULL OR valid_to > %s)
                ORDER BY version DESC LIMIT 1
            """
            params = (entity_id, as_of, as_of)
        else:
            sql = """
                SELECT id, type, version, attributes, scope,
                       valid_from, valid_to, created_at, provenance
                FROM entities
                WHERE id = %s
                ORDER BY version DESC LIMIT 1
            """
            params = (entity_id,)

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
        return row

    # -- relations ----------------------------------------------------------

    def save_relation(self, relation: Relation) -> None:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO relations
                    (id, type, from_entity_id, to_entity_id,
                     attributes, scope, valid_from, valid_to, provenance)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    relation.id, relation.type,
                    relation.from_entity_id, relation.to_entity_id,
                    json.dumps(relation.attributes), relation.scope,
                    relation.valid_from, relation.valid_to,
                    json.dumps(relation.provenance),
                ),
            )
            conn.commit()

    # -- causal links -------------------------------------------------------

    @staticmethod
    def _insert_causal_links(
        cur: psycopg.Cursor, child_id: str, parent_ids: Sequence[str]
    ) -> None:
        for pid in parent_ids:
            cur.execute(
                """
                INSERT INTO causal_links (parent_event_id, child_event_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (pid, child_id),
            )

    def save_causal_links(
        self, event_id: str, parent_ids: Sequence[str]
    ) -> None:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                self._insert_causal_links(cur, event_id, parent_ids)
            conn.commit()

    def get_causal_parents(self, event_id: str) -> List[str]:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT parent_event_id FROM causal_links "
                    "WHERE child_event_id = %s",
                    (event_id,),
                )
                return [row["parent_event_id"] for row in cur.fetchall()]

    def get_causal_children(self, event_id: str) -> List[str]:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT child_event_id FROM causal_links "
                    "WHERE parent_event_id = %s",
                    (event_id,),
                )
                return [row["child_event_id"] for row in cur.fetchall()]
