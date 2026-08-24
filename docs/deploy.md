# Deployment

Target platform: **Render**, via the Blueprint at [`../render.yaml`](../render.yaml).

- Local setup → [../README.md](../README.md)
- System design → [architecture.md](architecture.md)

---

## Process model

Three processes share one Postgres database and one Redis instance:

| Process | Command | Responsibility |
| --- | --- | --- |
| **web** | `uvicorn main:app` | The HTTP API. Owns all state changes. |
| **worker** | `celery ... worker` | Sends campaigns, validates recipient domains. |
| **beat** | `celery ... beat` | Ticks every 60s to run the reconciler. |

`app/Procfile` carries the flags production needs:

```
web:    uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips="*"
worker: celery -A server.workers.celery.celery_app worker --loglevel=info --concurrency=4
beat:   celery -A server.workers.celery.celery_app beat --loglevel=info
```

> **Run exactly one beat process.** Two means duplicate reconciler ticks, and a campaign
> dispatched twice.

---

## The app lives in a subdirectory

Buildpacks look for `pyproject.toml`, `uv.lock`, `.python-version`, and `Procfile` at the **app
root**. All four are in `app/`, so detection fails unless the platform is pointed at the
subdirectory. Every service in `render.yaml` sets `rootDir: app` for this reason.

Render's native Python runtime defaults to 3.14 and supports `uv`, so no Dockerfile is needed —
and no `requirements.txt`, which would conflict with `uv.lock`.

**This is also why the frontend sits at `app/frontend/`.** Render prunes the clone to the
service's root directory — [files outside it are not available at build time or at
runtime](https://render.com/docs/monorepo-support#setting-a-root-directory). The web service is
what builds the SPA, so the SPA has to be inside the directory the web service can see. A
`frontend/` at the repository root would fail the build with `cd: ../frontend: No such file or
directory`, and frontend-only commits would not trigger a redeploy at all.

`node` and `npm` ship with every native runtime, Python included, so nothing extra is needed to
run `npm ci` from a Python service's build command. `NODE_ENV` is set only at runtime and only
for Node services, so the build does install `devDependencies` — which is where `vite` and
`tsc` live.

The web service pins `NODE_VERSION`, because Render's default moves on its own schedule and CI
would otherwise be validating a different major than the one that builds the deploy. It is set
on the service rather than in a `.node-version` file: the env var takes precedence, and it
leaves no question about which directory counts as the repo root once `rootDir` is set. Change
it and `.github/workflows/ci.yml` together.

The Python package inside `app/` is `server/` — named for the process it runs, since `app/` now
holds the client too. That is why the worker commands read `-A server.workers.celery.celery_app`.

Deploying elsewhere? Same principle. On Heroku that means
[`heroku-buildpack-monorepo`](https://github.com/lstoll/heroku-buildpack-monorepo) with
`APP_BASE=app`; Heroku's Python buildpack also ships 3.14 and `uv`.

---

## First deploy

### 1. Apply the Blueprint

**Render Dashboard → New → Blueprint**, pointing at this repository. It creates three services
(`mailer-api`, `mailer-worker`, `mailer-beat`), a Postgres instance (`mailer-db`), and a shared
environment group (`mailer-config`).

`DATABASE_URL` is wired automatically from `mailer-db` to all three services.

### 2. Fill in the secrets

Every `sync: false` variable in the `mailer-config` group must be set by hand. Six of them are
required, and **the services will not boot without them**: `REDIS_URL`, `MICROSOFT_CLIENT_ID`,
`MICROSOFT_CLIENT_SECRET`, `MICROSOFT_REDIRECT_URI`, `TOKEN_ENCRYPTION_KEY`, and `SECRET_KEY`.
(`DATABASE_URL` is the seventh, and the Blueprint wires it for you.)

`MICROSOFT_TENANT_ID` is **not** among them — the Blueprint sets it to `common`. It is
interpolated straight into the Graph URLs, so leaving it blank would produce
`login.microsoftonline.com//oauth2/...` rather than falling back to a default.

Generate the two the app owns:

```bash
# TOKEN_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"
```

Take `MICROSOFT_CLIENT_ID` and `MICROSOFT_CLIENT_SECRET` from the Azure app registration.

### 3. Set `REDIS_URL`

Redis is deliberately **not** in the Blueprint — this project uses Upstash, which is external
to Render. Set `REDIS_URL` on the environment group using the `rediss://` (TLS) URL.

Get this right before the first deploy finishes. `/health` is the health check path and it
returns `503` while Redis is unreachable, so a wrong URL does not show up as degraded rate
limiting — it shows up as a deploy that never goes live.

Upstash presents a publicly-trusted certificate, so leave `REDIS_SSL_CERT_REQS` at its
`required` default. See [Redis TLS](#redis-tls) below.

### 4. Wire the OAuth redirect

This is circular, so it comes after the first apply: you need the web service's hostname before
you can set the redirect URI, and Azure must be told the same value.

1. Copy the web service's `https://<name>.onrender.com` hostname.
2. Set `MICROSOFT_REDIRECT_URI` to `https://<name>.onrender.com/auth/microsoft/callback`.
3. Register that **exact** URI in the Azure app registration. A mismatch fails the exchange.
4. Set `ALLOWED_ORIGINS_RAW` to the origins that will call the API, comma-separated.

The Azure app registration needs these delegated Microsoft Graph scopes:

```
offline_access  openid  profile  email  User.Read  Mail.Send  Mail.Send.Shared
```

### 5. Migrations

`render.yaml` runs them via `preDeployCommand`, after the build and before traffic shifts:

```
uv run alembic upgrade head
```

That requires a paid instance type. On the free tier, remove the line and run it from the
Render shell instead.

---

## Configuration reference

All settings are read from the environment (see `server/core/config.py`). Names are
case-sensitive.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `APP_NAME` | no | `Full Stack Mailer` | OpenAPI title. |
| `APP_ENV` | no | `development` | Anything other than `development` is treated as production. |
| `DATABASE_URL` | **yes** | — | Wired from `mailer-db` by the Blueprint. |
| `REDIS_URL` | **yes** | — | Upstash `rediss://` URL. |
| `MICROSOFT_CLIENT_ID` | **yes** | — | Azure app registration. |
| `MICROSOFT_CLIENT_SECRET` | **yes** | — | Azure app registration. |
| `MICROSOFT_TENANT_ID` | no | `common` | `common` for multi-tenant, or a tenant GUID. |
| `MICROSOFT_REDIRECT_URI` | **yes** | — | Must match Azure exactly. |
| `TOKEN_ENCRYPTION_KEY` | **yes** | — | Fernet key encrypting stored Graph tokens at rest. |
| `SECRET_KEY` | **yes** | — | Signs session tokens and the OAuth `state`. |
| `ACCESS_TOKEN_TTL_SECONDS` | no | `28800` (8h) | Session lifetime; also drives the cookie `max_age`. |
| `ALLOWED_ORIGINS_RAW` | no | `http://localhost:3000` | Comma-separated CORS origins. `*` is rejected at startup. |
| `FRONTEND_URL` | no | `""` | Post-login redirect target. `/app` for the bundled frontend. Empty → the callback returns JSON. |
| `MAX_UPLOAD_BYTES` | no | `10485760` | CSV upload cap. Exceeding it returns `413`. |
| `REDIS_SSL_CERT_REQS` | no | `required` | `required`, `optional`, or `none`. |
| `R2_ENDPOINT_URL` | no | `""` | `https://<account_id>.r2.cloudflarestorage.com` |
| `R2_ACCESS_KEY_ID` | no | `""` | R2 credential. |
| `R2_SECRET_ACCESS_KEY` | no | `""` | R2 credential. |
| `R2_BUCKET_NAME` | no | `mailer-templates` | Bucket holding template HTML and inline images. |
| `R2_PUBLIC_BASE_URL` | for images | `""` | Public read URL for the bucket, no trailing slash. Required to upload inline campaign images. |

---

## Cloudflare R2: making images public

Template HTML is fetched by the API, which holds credentials. Inline campaign images are not:
they are fetched by **the recipient's mail client**, which has no session and cannot sign a
request. The bucket therefore needs a public read URL, and `R2_PUBLIC_BASE_URL` must point at it.

1. In the Cloudflare dashboard, open the bucket → **Settings** → **Public access**.
2. Either enable the **r2.dev subdomain** — quickest, and rate-limited by Cloudflare — or connect
   a **custom domain**, which has no such limit.
3. Set `R2_PUBLIC_BASE_URL` to that origin, with no trailing slash and no bucket path:

   ```
   R2_PUBLIC_BASE_URL=https://pub-<hash>.r2.dev
   ```

4. Verify from outside any session:

   ```bash
   curl -I "$R2_PUBLIC_BASE_URL/assets/<any-uploaded-key>"   # expect 200
   ```

A custom domain on the same root as the sending address is worth the extra step: images served
from a domain unrelated to the sender are more likely to be treated as tracking pixels and
blocked.

Leaving `R2_PUBLIC_BASE_URL` unset is safe — `POST /assets` returns `503` with an explanation
rather than storing an object nobody can reach.

---

## Production checklist

- [ ] **The frontend is built.** The web service's `buildCommand` runs `npm ci && npm run build`
      in `app/frontend/` before `uv sync`, writing to `app/static/`. Without it the API
      starts fine but `/app` returns `404`.
- [ ] **`R2_PUBLIC_BASE_URL` is set and publicly readable**, if campaigns will contain images.
      Check it with `curl -I` from outside any session — a link that 403s in an inbox shows as a
      broken image to every recipient.
- [ ] **`FRONTEND_URL` is `/app`**, so the OAuth callback lands on the app rather than returning
      JSON.
- [ ] **`APP_ENV` is not `development`.** This is what makes the session and OAuth state
      cookies `Secure`, and stops `/health` disclosing database hostnames to unauthenticated
      callers. Set to `production` in `render.yaml`.
- [ ] **Exactly one beat instance.**
- [ ] **`NODE_VERSION` matches CI.** Set on the web service in `render.yaml`, mirrored by
      `node-version` in `.github/workflows/ci.yml`. If they drift, a green build proves nothing
      about the one Render runs.
- [ ] **`--proxy-headers` on the web command.** Without it uvicorn sees the load balancer as
      the client and the OAuth login rate limit becomes one shared bucket for every user.
- [ ] **`MICROSOFT_REDIRECT_URI` matches Azure exactly.**
- [ ] **`ALLOWED_ORIGINS_RAW` contains no `*`.** The app refuses to start if it does, because
      credentials are enabled on CORS.
- [ ] **Migrations ran** — `alembic upgrade head` against the production database.
- [ ] **`/health` returns 200.** It checks Postgres and Redis, and `render.yaml` points
      `healthCheckPath` at it — so `503` from either store is not just a warning, it stops the
      deploy going live.

### Redis TLS

`REDIS_SSL_CERT_REQS` defaults to `required`, which is correct for Upstash and any provider
using a publicly-trusted certificate.

Only relax it for a private CA, and prefer supplying the CA bundle over disabling verification.
If the worker fails to connect on first boot with a certificate error, this is the setting to
look at — but treat `none` as a stopgap, not a fix.

### Failure modes

| If this breaks | What happens |
| --- | --- |
| Redis unreachable | The app itself survives: rate limiting degrades to per-process counters, and `/start` returns `503` leaving the campaign untouched. **Render does not.** `/health` reports `503` when either store is down, and it is the health check path — so the instance is marked unhealthy and taken out of service. A deploy with a bad `REDIS_URL` never goes live. |
| Worker dies mid-campaign | The task is redelivered. Recipients stranded at `sending` are reclaimed after 30 minutes; already-sent addresses are skipped. |
| Beat stops | Scheduled campaigns are not dispatched at their time. They are picked up as soon as beat returns — the database, not the broker, holds the schedule. |
| Postgres unreachable | `/health` returns `503`. Nothing sends. |
| Graph auth fails | The campaign pauses rather than failing, so it can resume after re-authentication. |

---

## Observability

There is no metrics or error-tracking integration. Logs go to stdout, structured as
`timestamp | level | logger | message`.

Recipient and user email addresses are deliberately **not** logged — records carry ids
instead. `email_logs` is the audit record of what was actually sent, and is the right place to
answer "did this address receive the campaign?".

Useful log lines during a send:

```
Campaign started: <id>
Processing batch. campaign=<id> batch_size=10
Email sent successfully. recipient=<recipient-id>
Released N recipient(s) stranded at 'sending'. campaign=<id>
Re-queued overdue scheduled campaign. id=<id> scheduled_at=<ts>
```

To diagnose a campaign that under-sent, prefer the API over the logs:

```
GET /campaigns/{id}/stats                    # counts per status
GET /campaigns/{id}/recipients?status=failed # addresses and failure reasons
```
