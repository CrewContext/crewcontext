# API Reference

## ProcessContext

The main interface agents interact with. Create one per agent per process.

### Constructor

```python
ProcessContext(
    process_id: str,
    agent_id: str,
    scope: str = "default",
    db_url: str | None = None,
    enable_neo4j: bool = True,
)
```

| Parameter | Description |
|-----------|-------------|
| `process_id` | Unique identifier for the business process. All agents in the same process share this ID. |
| `agent_id` | Identifier for the current agent. Recorded as provenance on every event. |
| `scope` | Isolation domain. Events in different scopes are filtered separately. |
| `db_url` | PostgreSQL connection string. Falls back to `CREWCONTEXT_DB_URL` env var, then default. |
| `enable_neo4j` | Set `False` to skip Neo4j entirely. All core functionality works without it. |

### Context Manager

```python
with ProcessContext(process_id="p1", agent_id="a1") as ctx:
    # ctx is connected and schema is initialized
    ...
# connections are closed automatically
```

You can also manage the lifecycle manually:

```python
ctx = ProcessContext(process_id="p1", agent_id="a1")
ctx.connect()
# ... use ctx ...
ctx.close()
```

---

### Methods

#### `emit(event_type, data, ...)`

Record an event.

```python
event = ctx.emit(
    event_type: str,
    data: dict,
    entity_id: str | None = None,
    relation_id: str | None = None,
    metadata: dict | None = None,
    caused_by: list[Event] | None = None,
)
```

| Parameter | Description |
|-----------|-------------|
| `event_type` | Dotted name like `"invoice.received"` or `"payment.failed"`. |
| `data` | Event payload. Any JSON-serializable dict. |
| `entity_id` | The business entity this event affects. |
| `relation_id` | The relation this event affects. |
| `metadata` | Arbitrary metadata (tags, labels, debug info). |
| `caused_by` | List of parent `Event` objects. Builds the causal DAG. |

**Returns**: The persisted `Event` object.

**Side effects**:
- Event is saved to PostgreSQL.
- Event is projected to Neo4j (if available).
- Subscribers for this event type are notified.
- Routing rules are evaluated. If a rule matches, a `routing.decision` event is emitted automatically.

---

#### `batch_emit(events_spec)`

Atomically emit multiple events in a single database transaction.

```python
events = ctx.batch_emit([
    {"event_type": "line.item", "data": {"sku": "A1", "qty": 10}, "entity_id": "inv-1"},
    {"event_type": "line.item", "data": {"sku": "B2", "qty": 5}, "entity_id": "inv-1"},
])
```

Each spec dict accepts: `event_type` (required), `data` (required), `entity_id`, `relation_id`, `metadata`.

**Returns**: List of persisted `Event` objects.

---

#### `query(entity_id, event_type, scope, as_of, limit, offset)`

Query events in this process.

```python
events = ctx.query(
    entity_id: str | None = None,
    event_type: str | None = None,
    scope: str | None = None,
    as_of: datetime | None = None,
    limit: int = 1000,
    offset: int = 0,
)
```

**Returns**: List of event dicts ordered by timestamp ascending.

All parameters are optional filters. Combine them freely:

```python
# All events for an entity
ctx.query(entity_id="inv-1")

# Only routing decisions
ctx.query(event_type="routing.decision")

# Events before a specific time
ctx.query(as_of=datetime(2024, 3, 1, 14, 0, tzinfo=timezone.utc))

# Paginated
ctx.query(limit=20, offset=40)
```

---

#### `timeline(entity_id, as_of)`

Shorthand for querying the full ordered event history of an entity.

```python
events = ctx.timeline(entity_id: str, as_of: datetime | None = None)
```

**Returns**: List of event dicts ordered by timestamp ascending.

---

#### `save_entity(entity)`

Save a versioned entity snapshot.

```python
ctx.save_entity(Entity(
    id="inv-1",
    type="Invoice",
    version=1,
    attributes={"amount": 5000, "status": "received"},
    provenance={"agent": "receiver"},
))
```

Each version is a new row. Previous versions are preserved.

---

#### `get_entity(entity_id, as_of)`

Retrieve the latest entity state, or the state at a point in time.

```python
entity = ctx.get_entity(entity_id: str, as_of: datetime | None = None)
```

**Returns**: Entity dict or `None`.

---

#### `save_relation(relation)`

Persist a typed relation between entities.

```python
ctx.save_relation(Relation(
    id=generate_id(),
    type="BELONGS_TO",
    from_entity_id="inv-1",
    to_entity_id="vendor-42",
))
```

---

#### `causal_parents(event_id)`

Get the IDs of events that caused this event.

```python
parent_ids = ctx.causal_parents(event_id: str)
```

**Returns**: List of event ID strings.

---

#### `causal_children(event_id)`

Get the IDs of events caused by this event.

```python
child_ids = ctx.causal_children(event_id: str)
```

**Returns**: List of event ID strings.

---

#### `causal_chain(event_id, max_depth)`

Walk the full causal DAG via Neo4j. Requires Neo4j to be enabled and available.

```python
chain = ctx.causal_chain(event_id: str, max_depth: int = 10)
```

**Returns**: List of event dicts in causal order. Empty list if Neo4j is unavailable.

---

#### `lineage(entity_id, max_depth)`

Get the Neo4j event lineage for an entity.

```python
lineage = ctx.lineage(entity_id: str, max_depth: int = 20)
```

**Returns**: List of event dicts. Empty list if Neo4j is unavailable.

---

#### `cypher(query, params)`

Execute a raw Cypher query against Neo4j.

```python
results = ctx.cypher(
    "MATCH (e:Event)-[:AFFECTS]->(n:Entity {id: $id}) RETURN e.type",
    {"id": "inv-1"},
)
```

**Returns**: List of record dicts. Empty list if Neo4j is unavailable.

---

#### `subscribe(event_type, callback)`

Subscribe to events of a given type. The callback is invoked synchronously when a matching event is emitted.

```python
ctx.subscribe("invoice.received", lambda event: print(f"New invoice: {event.data}"))
```

---

#### `router`

Access the `PolicyRouter` instance for this context. See [PolicyRouter](#policyrouter) below.

---

## Data Models

All models are **frozen dataclasses** — immutable after creation.

### Event

```python
Event(
    id: str,                          # Unique identifier
    type: str,                        # Event type (e.g. "invoice.received")
    process_id: str,                  # Which process
    data: dict,                       # Payload
    agent_id: str,                    # Which agent emitted it
    entity_id: str | None = None,     # Affected entity
    relation_id: str | None = None,   # Affected relation
    scope: str = "default",           # Isolation domain
    timestamp: datetime = <utc_now>,  # Timezone-aware UTC
    metadata: dict = {},              # Arbitrary metadata
    parent_ids: tuple[str] = (),      # Causal parents
)
```

### Entity

```python
Entity(
    id: str,                          # Entity identifier
    type: str,                        # Entity type (e.g. "Invoice")
    attributes: dict,                 # Current state
    scope: str = "default",
    version: int = 1,                 # Snapshot version number
    valid_from: datetime = <utc_now>,
    valid_to: datetime | None = None,
    created_at: datetime = <utc_now>,
    provenance: dict = {},            # Who created this snapshot
)
```

### Relation

```python
Relation(
    id: str,
    type: str,                        # Relationship type (e.g. "BELONGS_TO")
    from_entity_id: str,              # Source entity
    to_entity_id: str,                # Target entity
    attributes: dict = {},
    scope: str = "default",
    valid_from: datetime = <utc_now>,
    valid_to: datetime | None = None,
    provenance: dict = {},
)
```

Validation: self-referencing relations (`from_entity_id == to_entity_id`) raise `ValueError`.

### RoutingDecision

```python
RoutingDecision(
    event_id: str,                    # The event that was evaluated
    rule_name: str,                   # Which rule matched
    action: str,                      # The routing action
    priority: int,                    # Rule priority
    metadata: dict = {},
    timestamp: datetime = <utc_now>,
)
```

Call `.to_dict()` to serialize.

### `generate_id()`

Generate a UUID4 string identifier.

---

## PolicyRouter

Deterministic, priority-ordered rule evaluation engine.

### `add_rule(name, condition, action, priority, metadata)`

Register a routing rule. Higher priority rules are evaluated first.

```python
ctx.router.add_rule(
    name="high-value",
    condition=data_field_gt("amount", 10000),
    action="route-to-senior",
    priority=10,
    metadata={"sla_hours": 4},
)
```

### `remove_rule(name)`

Remove a rule by name. Returns `True` if found, `False` if not.

### `enable_rule(name)` / `disable_rule(name)`

Toggle a rule without removing it. Disabled rules are skipped during evaluation.

### `get_rules()`

List all registered rules with their name, action, priority, and enabled status.

### `evaluate(event)`

Evaluate an event against all enabled rules in priority order. Returns a `RoutingDecision` on the first match, or `None`.

Events of type `routing.decision` are never evaluated (recursion guard).

---

## Condition Combinators

Build routing conditions from composable primitives. Import from the top-level package.

```python
from crewcontext import data_field_gt, all_of, event_type_is
```

| Function | Description |
|----------|-------------|
| `data_field_gt(field, threshold)` | `event.data[field] > threshold` |
| `data_field_eq(field, value)` | `event.data[field] == value` |
| `data_field_ne(field, value)` | `event.data[field] != value` |
| `data_fields_differ(field_a, field_b)` | `event.data[field_a] != event.data[field_b]` |
| `event_type_is(*types)` | `event.type in {types}` |
| `all_of(*conditions)` | All conditions must be true |
| `any_of(*conditions)` | At least one must be true |
| `none_of(*conditions)` | None must be true |

Combine them:

```python
condition = all_of(
    data_field_gt("amount", 10000),
    event_type_is("invoice.received", "invoice.updated"),
    none_of(data_field_eq("status", "cancelled")),
)
```

You can also use plain lambdas:

```python
ctx.router.add_rule(
    name="custom",
    condition=lambda e: e.data.get("region") in ("KE", "NG", "ZA"),
    action="route-to-africa-team",
)
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CREWCONTEXT_DB_URL` | `postgresql://crew:crew@localhost:5432/crewcontext` | PostgreSQL connection string |
| `CREWCONTEXT_NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt protocol URI |
| `CREWCONTEXT_NEO4J_USER` | `neo4j` | Neo4j username |
| `CREWCONTEXT_NEO4J_PASSWORD` | `crewcontext123` | Neo4j password |
