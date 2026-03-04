# Contributing to CrewContext

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/crewcontext/crewcontext.git
cd crewcontext
docker compose up -d        # Start Postgres + Neo4j
pip install -e ".[dev]"     # Install with dev dependencies
pytest -v                   # Run tests
```

## Making Changes

1. Fork the repo and create a branch from `main`.
2. Write your code. Add tests for new functionality.
3. Run the test suite: `pytest -v`
4. Commit with a clear message describing the change.
5. Open a pull request.

## Code Style

- Python 3.10+ with type hints.
- Use `logging` instead of `print` in library code.
- No bare `except:` — always catch specific exceptions.
- Keep functions focused and small.
- Write docstrings for public APIs.

## Tests

- **Unit tests** (no external services): `tests/test_models.py`, `tests/test_router.py`
- **Integration tests** (require Postgres): `tests/test_postgres_store.py`
- Integration tests auto-skip if the database is unavailable.
- Use unique `process_id` values per test for isolation.

## Reporting Issues

- Use [GitHub Issues](https://github.com/crewcontext/crewcontext/issues).
- Include: what you expected, what happened, steps to reproduce.
- For bugs, include your Python version and OS.

## Pull Request Guidelines

- One logical change per PR.
- Add/update tests for your changes.
- Keep the PR description concise — explain *why*, not just *what*.
- All CI checks must pass before merge.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
