# Full Stack Mailer — backend

The FastAPI + Celery service. Setup, API reference, and tests are in the
[root README](../README.md).

| | |
| --- | --- |
| System design and decisions | [../docs/architecture.md](../docs/architecture.md) |
| Deployment | [../docs/deploy.md](../docs/deploy.md) |

```bash
uv sync                         # install dependencies
uv run alembic upgrade head     # migrate
uv run uvicorn main:app --reload
uv run celery -A app.workers.celery.celery_app worker --loglevel=info
uv run celery -A app.workers.celery.celery_app beat --loglevel=info

uv run ruff check . && uv run mypy && uv run pytest
```
