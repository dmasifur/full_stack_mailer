# Full Stack Mailer

A bulk email campaign backend. Users connect a Microsoft work account over OAuth; the service
stores their tokens encrypted, imports recipient lists from CSV, validates the addresses, and
sends campaigns through the Microsoft Graph API — from the user's own mailbox or from a shared
mailbox they have rights to.

> **This repository is backend-only.** Despite the name, there is no frontend here. The API is
> designed to be driven by a separate client, or directly via the OpenAPI docs at `/docs`.

| | |
| --- | --- |
| System design and decisions | [docs/architecture.md](docs/architecture.md) |
| Deployment | [docs/deploy.md](docs/deploy.md) |

---

## Prerequisites

- **Python 3.14** (pinned in `backend/.python-version`)
- **[uv](https://docs.astral.sh/uv/)** for dependency management
- **PostgreSQL** — plus permission to `CREATE DATABASE` if you want to run the tests
- **Redis** — Celery broker and rate-limit storage
- **An Azure app registration** with these delegated Microsoft Graph scopes:
  `offline_access`, `openid`, `profile`, `email`, `User.Read`, `Mail.Send`, `Mail.Send.Shared`
  — and a redirect URI matching `MICROSOFT_REDIRECT_URI` exactly
- **A Cloudflare R2 bucket** — only if you plan to use uploaded HTML templates

## Setup

```bash
cd backend

uv sync                         # install dependencies into .venv
cp .env.example .env            # then fill in the secrets below
uv run alembic upgrade head     # create the schema
```

`.env.example` is a working template. Values are read verbatim, so keep integers literal and
avoid trailing comments or spaces around `=`.

Generate the two secrets the app owns:

```bash
# TOKEN_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"
```

`MICROSOFT_CLIENT_ID` and `MICROSOFT_CLIENT_SECRET` come from the Azure app registration. The
full configuration reference lives in
[docs/deploy.md](docs/deploy.md#configuration-reference).

## Running

Three processes, each in its own shell:

```bash
uv run uvicorn main:app --reload --port 8000
uv run celery -A app.workers.celery.celery_app worker --loglevel=info --concurrency=4
uv run celery -A app.workers.celery.celery_app beat --loglevel=info
```

Beat is not optional if you want scheduling to survive a Redis restart — see
[the reconciler decision](docs/architecture.md#5-the-reconciler-makes-the-database-the-source-of-truth).

Check it came up:

```bash
curl http://localhost:8000/health     # 200 when Postgres and Redis both answer
open http://localhost:8000/docs       # interactive OpenAPI docs
```

## Tests

```bash
cd backend
uv run pytest
```

152 tests, covering the state machine, tenant isolation, OAuth state binding, the send worker's
concurrency and failure paths, the scheduling reconciler, CSV import and its limits, and the
health endpoint. Graph is stubbed; no email is ever sent.

The suite needs a **real Postgres**, and manages its own database:

- The test database name is `DATABASE_URL`'s database plus a `_test` suffix. Override the whole
  URL with `TEST_DATABASE_URL` if you prefer.
- It **refuses to run** against any database whose name does not end in `_test`, so a
  misconfigured environment fails loudly instead of truncating real campaigns.
- It creates the database, migrates it to head, and drops it at the end of the session. The
  role therefore needs `CREATE DATABASE`.
- Every test starts from empty tables.

Running against a remote Postgres can produce spurious failures if the provider drops the
connection mid-run. A local server avoids this; CI uses a container for the same reason.

## Lint and types

```bash
uv run ruff check .
uv run ruff format .
uv run mypy
```

mypy runs in **strict** mode over `app/`, `main.py`, and `tests/`, with the pydantic plugin.
Two deliberate relaxations, both documented inline in `pyproject.toml`:

- `no_implicit_reexport` is off. It polices a module's import surface, which is a contract for
  a published library but not for an application — here its only real effect was to reject
  `monkeypatch.setattr(module.settings, ...)`, which is the correct way to write those tests.
- Tests are exempt from *signature* requirements only. Their bodies, assertions, and every call
  they make into `app/` are still fully checked.

Alembic revisions are excluded — they are generated, and their module names are hashes.
`warn_unused_ignores` is on, so a `# type: ignore` that stops being necessary becomes an error
rather than quietly rotting.

CI runs all of the above plus `uv build`, against Postgres and Redis service containers.

## Sending a campaign locally

1. **Connect a mailbox** — open `GET /auth/microsoft/login` in a browser.
2. **Register the sender address** — `POST /sender-addresses`. Skip this to send from the
   user's own mailbox; a campaign with no `from_address` uses `/me/sendMail`.
3. **Upload a template** *(optional)* — `POST /templates?name=Newsletter` with compiled HTML.
4. **Create the campaign** — `POST /campaigns` with `name`, `subject`, `template_body`, and
   optionally `template_id`, `from_address`, `cc_emails`.
5. **Upload recipients** — `POST /campaigns/{id}/recipients/upload` with a CSV:

   ```csv
   email,first_name,last_name
   ada@example.com,Ada,Lovelace
   grace@example.com,Grace,Hopper
   ```

   `email` is required; `first_name` and `last_name` are optional. Addresses are lowercased and
   trimmed, and re-uploading the same file will not duplicate rows.
6. **Wait for DNS validation.** The worker resolves each domain's MX record. Rows that fail are
   marked `invalid` and never sent to. Starting before this finishes returns `409` — poll
   `GET /campaigns/{id}/stats` until `awaiting_validation` reaches zero.
7. **Send** — `POST /campaigns/{id}/start`, or `POST /campaigns/{id}/schedule` with
   `{"scheduled_at": "2026-09-01T09:00:00+00:00"}` for later.
8. **Watch it** — `GET /campaigns/{id}/stats` for counts,
   `GET /campaigns/{id}/recipients?status=failed` for addresses that bounced and why.

## API reference

Authentication is an `HttpOnly` cookie named `access_token`, set by the OAuth callback. An
`Authorization: Bearer <token>` header is accepted as an alternative. Every route except
`/health` and the two OAuth routes requires it.

### Auth

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/health` | Public. `200` when Postgres and Redis respond, `503` otherwise. |
| `GET` | `/auth/microsoft/login` | Redirects to Microsoft. Sets a short-lived `oauth_state` cookie. Rate limited to 10/min. |
| `GET` | `/auth/microsoft/callback` | Exchanges the code, upserts the user, sets the session cookie. Requires the `oauth_state` cookie to match. |
| `GET` | `/auth/me` | The authenticated user. |
| `POST` | `/auth/logout` | Clears the cookie. |

### Sender addresses

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/sender-addresses` | `{label, email, is_default}`. `409` if already registered. |
| `GET` | `/sender-addresses` | Scoped to the caller. Default first. |
| `PATCH` | `/sender-addresses/{address_id}` | Change `label` or `is_default`. |
| `DELETE` | `/sender-addresses/{address_id}` | |

### Templates

> Templates are a **shared library** — every authenticated user can list and use every
> template; only the uploader can delete one. This is deliberate. See
> [the decision](docs/architecture.md#13-templates-are-shared-across-all-users).

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/templates?name=<name>` | Multipart `file` upload. `.html` only, 5 MB max. |
| `GET` | `/templates` | All templates, newest first. |
| `DELETE` | `/templates/{template_id}` | Uploader only. Also removes the R2 object. |

### Campaigns

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/campaigns` | Creates a `draft`. Accepts `template_id`, `from_address`, up to 20 `cc_emails`. |
| `GET` | `/campaigns` | Paginated: `?page=1&page_size=20` (max 100). |
| `GET` | `/campaigns/{id}` | |
| `PATCH` | `/campaigns/{id}` | Drafts only. |
| `DELETE` | `/campaigns/{id}` | Blocked while `running` or `scheduled`. Children cascade. |
| `GET` | `/campaigns/{id}/cc-recipients` | |
| `POST` | `/campaigns/{id}/cc-recipients` | **Replaces** the whole CC list. Drafts only. |
| `DELETE` | `/campaigns/{id}/cc-recipients/{cc_id}` | Drafts only. |
| `POST` | `/campaigns/{id}/recipients/upload` | Multipart CSV, capped at `MAX_UPLOAD_BYTES`. `400` malformed, `413` oversized. |
| `GET` | `/campaigns/{id}/recipients` | Paginated. `?status=failed` to filter. |
| `GET` | `/campaigns/{id}/stats` | Recipient counts per status. |
| `POST` | `/campaigns/{id}/start` | → `running`. `409` if recipients are missing or unvalidated. |
| `POST` | `/campaigns/{id}/schedule` | Body `{"scheduled_at": "<ISO-8601 with offset>"}`. Must be aware and future. |
| `POST` | `/campaigns/{id}/pause` | The worker stops before its next batch. |
| `POST` | `/campaigns/{id}/resume` | → `running`, clearing any stale schedule. |
| `POST` | `/campaigns/{id}/retry` | `failed` → `running`. Already-sent recipients are skipped. |

`start`, `schedule`, `resume`, and `retry` return `503` and leave the campaign untouched if the
task broker is unreachable, rather than committing a status with no task behind it.

Campaigns, recipients, CC lists, and sender addresses are scoped to the authenticated user;
another user's ids return `404`.

## Repository layout

```
docs/                      architecture.md, deploy.md
render.yaml                Render Blueprint — all three services
backend/
  main.py                  FastAPI app; router and middleware wiring
  Procfile                 web / worker / beat process definitions
  migrations/              Alembic revisions (one linear chain)
  app/
    api/                   Route handlers, one module per resource
    core/                  Settings, logging, rate limiter
    db/                    Engine, session factory, declarative base
    models/                SQLAlchemy models
    schemas/               Pydantic request/response models
    services/              Business logic — sending, state machine, CSV import,
                           token encryption, R2 storage
    workers/               Celery app and tasks
  tests/                   pytest suite (needs a real Postgres)
```
