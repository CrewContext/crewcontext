<p align="center">
  <img width="128" height="128" alt="crewcontext_logo_128" src="https://github.com/user-attachments/assets/db17d668-adca-401d-ab4e-901c05f60af4" />
</p>
<p align="center">
  <h1 align="center">CrewContext</h1>
  <p align="center"><strong>Enterprise-ready shared memory for AI agent systems.</strong></p>
  <p align="center">
    <a href="https://pypi.org/project/crewcontext/"><img src="https://img.shields.io/pypi/v/crewcontext.svg" alt="PyPI"></a>
    <a href="https://github.com/crewcontext/crewcontext/blob/main/LICENSE"><img src="https://img.shields.io/github/license/crewcontext/crewcontext.svg" alt="License"></a>
    <a href="https://github.com/crewcontext/crewcontext/actions"><img src="https://img.shields.io/github/actions/workflow/status/crewcontext/crewcontext/ci.yml" alt="CI"></a>
  </p>
</p>

**v0.2.0** — Now with enterprise security, observability, and stability features!

---

## The Problem

Multi-agent AI systems break at handoffs. Agent 1 processes an invoice. Agent 2 validates it. Agent 3 reconciles discrepancies. But Agent 3 has no idea what Agent 1 found. Context is lost. Decisions are invisible. Nothing is auditable.

Existing agent frameworks give you orchestration — **but not memory**. Chat history is personal. RAG is read-only. Neither gives you a shared, structured, temporal record of what happened, who did it, and why.

In regulated industries — finance, insurance, compliance — this isn't just inconvenient. It's a liability.

## What CrewContext Does

CrewContext is a **context coordination layer** that sits underneath your agent framework and provides:

- **Shared event store** — Every agent action is recorded. Nothing is lost at handoffs.
- **Causal DAG** — Every event tracks what caused it. You can answer "why did this happen?" by walking the chain backwards.
- **Temporal queries** — Reconstruct the exact state of any entity at any point in time. "What did we know at 2pm yesterday?"
- **Versioned entities** — Business objects (invoices, customers, claims) are snapshotted at each stage, never overwritten.
- **Policy router** — Deterministic, auditable routing rules with composable conditions. No black boxes.
- **Provenance tracking** — Every event records which agent, what scope, and when. Built for auditors.

## What's New in v0.2.0

### 🔒 Security
- **Role-Based Access Control (RBAC)** — Scope-based permissions for agents
- **Event Encryption** — Field-level encryption for sensitive data (AES-128)
- **Audit Logging** — Complete query and access trail for compliance
- **Secrets Management** — Support for env, file, JSON, and HashiCorp Vault

### 🔍 Observability
- **Structured Logging** — JSON-formatted logs for production
- **Health Checks** — Kubernetes-ready liveness/readiness probes
- **Event Replay** — Rebuild state from event history
- **Prometheus Metrics** — Native metrics export for monitoring

### 🛡️ Stability
- **Idempotency Keys** — Prevent duplicate event emission
- **Schema Validation** — Pydantic-based event validation
- **Retry Logic** — Exponential backoff with circuit breakers
- **Batch Limits** — Protect against memory exhaustion

See [IMPROVEMENTS.md](IMPROVEMENTS.md) for the complete guide.

## Architecture

```
                    ┌──────────────────────────────────┐
                    │        ProcessContext API        │
                    │  emit · query · timeline · causal│
                    └──────────┬───────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐   ┌─────▼──────┐  ┌──────▼──────┐
    │  PostgreSQL    │   │   Neo4j    │  │   Policy    │
    │  Event Store   │   │   Graph    │  │   Router    │
    │                │   │            │  │             │
    │  Append-only   │   │  Lineage   │  │  Rules      │
    │  Temporal      │   │  Causal    │  │  Pub/Sub    │
    │  Causal links  │   │  DAG       │  │  Routing    │
    │  Versioned     │   │  Typed     │  │  decisions  │
    │  entities      │   │  relations │  │             │
    └────────────────┘   └────────────┘  └─────────────┘
         (truth)          (optional)      (in-process)
```

**PostgreSQL** is the source of truth — append-only event log, versioned entity snapshots, causal link table. **Neo4j** is an optional projection for graph queries and lineage visualization. **Policy Router** evaluates events against composable rules in-process.

## Who It's For

CrewContext is for teams building multi-agent systems where **trust, auditability, and context preservation** matter:

- **Financial operations** — Payment processing, reconciliation, dispute resolution
- **KYC/AML compliance** — Auditable decision trails for regulators
- **Insurance claims** — Multi-stage pipelines where context loss means money lost
- **Supply chain** — Order-to-delivery orchestration across multiple agents
- **Any regulated workflow** where "the AI decided" isn't a good enough answer

## Framework-Agnostic

CrewContext is not a replacement for your agent framework. It's the **memory layer underneath it**. It works with:

- [CrewAI](https://github.com/joaomdmoura/crewAI)
- [LangGraph](https://github.com/langchain-ai/langgraph)
- [AutoGen](https://github.com/microsoft/autogen)
- [OpenAI Agents SDK](https://github.com/openai/openai-agents-python)
- Custom agent systems

## Getting Started

```bash
pip install crewcontext
docker compose up -d
crewcontext init-db
crewcontext demo vendor-discrepancy
```

Full API documentation and examples are available in the [docs](docs/) directory.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `CREWCONTEXT_DB_URL` | `postgresql://crew:crew@localhost:5432/crewcontext` | PostgreSQL connection |
| `CREWCONTEXT_NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt endpoint |
| `CREWCONTEXT_NEO4J_USER` | `neo4j` | Neo4j username |
| `CREWCONTEXT_NEO4J_PASSWORD` | `crewcontext123` | Neo4j password |

Neo4j is optional. Pass `enable_neo4j=False` for Postgres-only mode.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

[MIT](LICENSE)
