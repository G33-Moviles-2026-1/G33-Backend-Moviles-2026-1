# G33-Backend-Moviles-2026-1

## 1) Backend repo structure

Create the repo like this:

```text
backend/
  app/
    main.py

    core/
      config.py
      security.py
      time_rules.py

    api/
      deps.py
      routes/
        health.py
        sessions.py
        rooms.py
        bookings.py
        favorites.py
        reports.py
        schedule.py
        analytics.py
        chatbot.py
        navigation.py

    schemas/
      common.py
      sessions.py
      rooms.py
      bookings.py
      favorites.py
      reports.py
      schedule.py
      analytics.py
      chatbot.py
      navigation.py

    services/
      auth_service.py
      sessions_service.py
      rooms_service.py
      availability_service.py
      bookings_service.py
      favorites_service.py
      reports_service.py
      reliability_service.py
      schedule_service.py
      analytics_service.py
      chatbot_service.py
      navigation_service.py
      ingest_service.py

    db/
      session.py
      base.py
      models.py
      repositories/
        users_repo.py
        sessions_repo.py
        terms_repo.py
        buildings_repo.py
        rooms_repo.py
        availability_repo.py
        bookings_repo.py
        favorites_repo.py
        reports_repo.py
        schedule_repo.py
        analytics_repo.py
        chatbot_repo.py
        navigation_repo.py
      init_db.py
      seed_db.py

    integrations/
      uniandes/
        client.py
        parser.py
        ingest_runner.py

    workers/
      ingest_job.py
      reliability_job.py

  docker-compose.yml
  Dockerfile
  pyproject.toml
  .env.example
  README.md
```

## What each folder means

### `app/api/`

**HTTP layer only.** Routers define endpoints and call services.

* No SQL queries here.
* No heavy business logic here.

### `app/schemas/`

**Pydantic request/response contracts** for the API.

* These are what Flutter/Kotlin will consume.
* Keep them stable and explicit.

### `app/services/`

**Business rules live here.**
Examples:

* enforce “max 3 active bookings”
* enforce “no overlaps”
* enforce “booking locks room time window”
* enforce “today..+7 days”
* compute “availability for a day” from availability rules
* compute reliability and update `rooms.reliability`

### `app/db/`

**Database glue and persistence layer.**

* `session.py`: async engine + async session factory
* `models.py`: SQLAlchemy models matching your DBML
* `repositories/`: queries per domain (bookings_repo, rooms_repo, etc.)
* `init_db.py`: create tables (dev)
* `seed_db.py`: add mock data (dev)

### `app/integrations/uniandes/`

All code that touches Uniandes API + parsing/ingest.

* Makes it easy to mock / swap later.

### `app/workers/`

Longer jobs (ingest, reliability recompute) that you can run:

* via CLI
* or via a backend endpoint later
* or via cron (future)

---

## Team workflow (how to implement features cleanly)

When adding a feature or endpoint:

1. Add/extend **Pydantic schemas** in `schemas/xxx.py`
2. Add endpoint in `api/routes/xxx.py`
3. Implement business rules in `services/xxx_service.py`
4. Implement queries in `db/repositories/xxx_repo.py`
5. Wire router into `main.py`

The rule that prevents spaghetti:

> **Routes call Services; Services call Repositories; Repositories call DB.**

---

## 2) Initialize DB + insert mock data (dev workflow)

## Step A — Start Postgres

From `backend/`:

```bash
docker compose up -d db
```

---

## Step B — Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env`:

```bash
cp .env.example .env
```

---

## Step C — Initialize tables

Create: `app/db/init_db.py`

```python
import asyncio
from app.db.session import engine
from app.db.base import Base
import app.db.models  # noqa: F401 (ensures models are imported)

async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

if __name__ == "__main__":
    asyncio.run(init())
```

Run:

```bash
python -m app.db.init_db
```

---

## Step D — Seed mock data

---

## Step E — Run the backend

```bash
uvicorn app.main:app --reload
```

Verify:

* `GET http://localhost:8000/health`

---

## Notes

* The models enforce the schema shape; **complex booking constraints** (max 3 active, no overlaps, lock room window, match availability rule, 05:30–22:00, today..+7 days) belong in `services/bookings_service.py`, not DB constraints.
* PowerBI can connect directly to Postgres later and read `analytics_events` (or views).
