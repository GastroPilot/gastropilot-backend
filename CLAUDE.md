# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Linting (CI uses these exact checks)
```bash
ruff check services/ packages/
black --check services/ packages/
isort --check-only services/ packages/
```

### Formatting
```bash
black services/ packages/
isort services/ packages/
```

### Tests
```bash
pytest                              # full suite with coverage (min 35%)
pytest tests/test_orders.py         # single file
pytest -m "not slow"                # skip slow tests
pytest -m "integration"             # integration only
```

### Running services locally
```bash
docker compose -f docker-compose.dev.yml up -d   # backend + postgres
uvicorn app.main:app --reload --port 8000         # legacy monolith
uvicorn app.main:app --reload --port 8000 --app-dir services/core   # core service
```

### Alembic (core service only)
```bash
cd services/core && alembic upgrade head
cd services/core && alembic revision --autogenerate -m "description"
```

## Architecture

**Microservices backend** (Python 3.11, FastAPI, SQLAlchemy 2.0 async, PostgreSQL + asyncpg):

| Service | Port | Responsibility |
|---------|------|---------------|
| `services/core` | 8000 | Auth, users, restaurants, reservations, menus, tables, vouchers, blocks, waitlist |
| `services/orders` | 8001 | Orders, kitchen, invoices, SumUp payments, WebSocket |
| `services/ai` | 8002 | Seating solver, peak prediction, menu recommendations |
| `services/notifications` | 8003 | Email (SMTP/Resend), SMS, WhatsApp (Twilio), Celery worker |

There is also a **legacy monolith** in `/app/` (Integer IDs, German role names) — being migrated to the microservices above.

### Shared packages (`packages/shared/`)
- `auth.py` — JWT creation/verification, password/PIN hashing (shared across all services)
- `tenant.py` — TenantMiddleware (extracts tenant_id from JWT), PostgreSQL RLS context
- `events.py` — Redis Pub/Sub event publisher with typed event constants
- `schemas.py` — Shared enums (UserRole, PLATFORM_ROLES)

### Multi-tenancy
Every request carries a `tenant_id` from the JWT. The TenantMiddleware sets `request.state.tenant_id` and `request.state.is_admin`. PostgreSQL Row-Level Security enforces isolation at the DB level via `set_tenant_context()`.

Platform admin users (`is_admin=True`) use a separate DB session factory (`session_factory_admin`) with elevated privileges — see `services/core/app/core/deps.py`.

### Database
- Two engines per service: `_engine_app` (normal) and `_engine_admin` (platform admin)
- Config fields: `DATABASE_URL` and `DATABASE_URL_ADMIN` (must match docker-compose env var names exactly — pydantic-settings matches by field name)
- SSL handling: `_strip_sslmode()` removes sslmode from URL and passes it via `connect_args` because asyncpg rejects sslmode as a URL parameter
- UUID primary keys, `tenant_id` on all tenant-scoped tables
- Init scripts in `/sql/init.sql` and `/sql/rls.sql`

### Event system
Redis Pub/Sub channels: `gastropilot:{tenant_id}:{event_name}`. Events defined in `packages/shared/events.py`. Services publish events (e.g. reservation.created) and notifications service consumes them.

### API routing
All routes registered under both `/api/v1` and `/v1` prefixes. Public endpoints (`/public/*`) and webhooks (`/webhook_*`) have no auth. Swagger UI only available in development.

## Code style
- Line length: 100 chars
- Ruff rules: E, F, W, UP
- isort profile: black
- SQLAlchemy models use `Mapped[]` type annotations with `mapped_column()`

## Docker images
Built by CI/CD as: `servecta/gastropilot-core`, `servecta/gastropilot-orders`, `servecta/gastropilot-ai`, `servecta/gastropilot-notifications`. Each service has its own `Dockerfile` under `services/{name}/`.

## Nginx routing (staging/production)
```
/api/v1/              → core:8000       (default)
/api/v1/orders/       → orders:8001
/api/v1/kitchen/      → orders:8001
/api/v1/ai/           → ai:8002
/webhooks/whatsapp    → notifications:8003
/webhooks/sumup       → orders:8001
/ws/                  → orders:8001     (WebSocket upgrade)
```
