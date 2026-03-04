"""Shared fixtures for CrewContext tests."""
import os
import pytest

from crewcontext.models import generate_id
from crewcontext.store.postgres import PostgresStore


@pytest.fixture
def unique_process_id():
    """Each test gets a unique process ID for isolation."""
    return f"test-{generate_id()[:12]}"


@pytest.fixture
def pg_store():
    """PostgreSQL store — skips if DB is unavailable."""
    db_url = os.getenv(
        "CREWCONTEXT_DB_URL",
        "postgresql://crew:crew@localhost:5432/crewcontext",
    )
    store = PostgresStore(db_url, min_pool=1, max_pool=2)
    try:
        store.connect()
        store.init_schema()
    except Exception:
        pytest.skip("PostgreSQL not available")
    yield store
    store.close()
