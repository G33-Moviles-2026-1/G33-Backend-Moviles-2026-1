# G33-Backend-Moviles-2026-1

Backend for AndeSpace using **FastAPI + PostgreSQL + SQLAlchemy + Pydantic**.

---

## 1) Backend repo structure

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
        ingest.py

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
      ingest.py

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
        room_utilities_repo.py
        bookings_repo.py
        favorites_repo.py
        reports_repo.py
        schedule_repo.py
        analytics_repo.py
        chatbot_repo.py
        navigation_repo.py
      init_db.py
      seed_utilities.py

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
  requirements.txt
  .env.example
  README.md
````

---

## 2) What each folder means

### `app/api/`

HTTP layer only. Routers define endpoints and call services.

* No SQL queries here.
* No heavy business logic here.

### `app/schemas/`

Pydantic request/response contracts for the API.

* These are what Flutter/Kotlin will consume.
* Keep them stable and explicit.

### `app/services/`

Business rules live here.

Examples:

* enforce `max 3 active bookings`
* enforce `no overlaps`
* enforce `booking locks room time window`
* enforce `today..+7 days`
* compute `availability for a day` from availability rules
* compute and update `rooms.reliability`

### `app/db/`

Database glue and persistence layer.

* `session.py`: async engine + async session factory
* `models.py`: SQLAlchemy models matching the DB schema
* `repositories/`: queries per domain
* `init_db.py`: create tables
* `seed_utilities.py`: populate room utilities after ingest

### `app/integrations/uniandes/`

All code that touches the Uniandes API and parsing/ingest.

### `app/workers/`

Longer jobs that can later be run by CLI, endpoint or cron.

---

## 3) Team workflow

When adding a feature or endpoint:

1. Add or extend **Pydantic schemas** in `schemas/xxx.py`
2. Add endpoint in `api/routes/xxx.py`
3. Implement business rules in `services/xxx_service.py`
4. Implement queries in `db/repositories/xxx_repo.py`
5. Wire router into `main.py`

Golden rule:

> **Routes call Services; Services call Repositories; Repositories call DB.**

---

## 4) First-time setup: from clone to fully functional DB

This is the recommended order for a fresh setup.

### Step 1 — Clone the repo

```bash
git clone <repo-url>
cd G33-Backend-Moviles-2026-1
```

### Step 2 — Create and activate virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Create local environment file

Copy the example file:

```bash
cp .env.example .env
```

Make sure `.env` contains the correct local database URL. Example:

```env
DATABASE_URL=postgresql+asyncpg://andespace:andespace@localhost:5433/andespace
CURRENT_TERM_ID=202610
```

### Step 5 — Start PostgreSQL with Docker

```bash
docker compose up -d db
```

### Step 6 — Initialize database tables

```bash
python -m app.db.init_db
```

This creates all tables defined in `app/db/models.py`.

### Step 7 — Run the backend

```bash
uvicorn app.main:app --reload
```

### Step 8 — Verify backend health

Open or call:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"ok": true}
```

### Step 9 — Run Uniandes ingest

This fetches course data from the Uniandes API and populates:

* `terms`
* `buildings`
* `rooms`
* `room_availability_rules`

Run:

```bash
curl -X POST http://localhost:8000/ingest/run
```

You should get a response similar to:

```json
{
  "term_id": "202610",
  "term_start": "2026-01-19",
  "term_end": "2026-05-24",
  "raw_courses": 6044,
  "normalized_meetings": 8928,
  "buildings_upserted": 29,
  "rooms_upserted": 331,
  "availability_rules_written": 61571
}
```

### Step 10 — Verify ingest summary

```bash
curl http://localhost:8000/ingest/summary
```

### Step 11 — Populate utilities

Utilities are **not** part of the Uniandes source. They are populated separately with a deterministic script.

Run:

```bash
python -m app.db.seed_utilities
```

This fills `room_utilities` consistently for all ingested rooms.

---

## 5) Recommended execution order summary

For a completely fresh setup, run in this order:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d db
python -m app.db.init_db
uvicorn app.main:app --reload
```

In another terminal:

```bash
curl -X POST http://localhost:8000/ingest/run
python -m app.db.seed_utilities
curl http://localhost:8000/ingest/summary
```

---

## 6) How to reset everything from scratch

Use this only when you want to completely wipe the local database and rebuild everything.

### Step 1 — Stop containers and remove the Postgres volume

```bash
docker compose down -v
```

This deletes all persisted database data.

### Step 2 — Repeat the initial setup

```bash
docker compose up -d db
python -m app.db.init_db
uvicorn app.main:app --reload
```

Then, in another terminal:

```bash
curl -X POST http://localhost:8000/ingest/run
python -m app.db.seed_utilities
```

---

## 7) How it works across work sessions

When you finish working and come back later, the database data is still there as long as you did **not** delete the Docker volume.

### Usual next-day workflow

```bash
source .venv/bin/activate
docker compose up -d db
uvicorn app.main:app --reload
```

That is usually enough.

### Do I need to run `init_db` again?

No, not in normal work sessions.

### Do I need to run `/ingest/run` again?

No, not unless:

* you want to rebuild ingested data
* ingest logic changed
* you reset the DB

### Do I need to run `seed_utilities` again?

No, not unless:

* you reset the DB
* you want to overwrite/rebuild utilities

---

## 8) Useful inspection commands

### Check backend health

```bash
curl http://localhost:8000/health
```

### Check ingest summary

```bash
curl http://localhost:8000/ingest/summary
```

### Enter PostgreSQL

```bash
docker compose exec db psql -U andespace -d andespace
```

### Useful `psql` commands

```sql
\dt
\d rooms
\d room_availability_rules
```

### Count main tables

```sql
select
  (select count(*) from terms) as terms,
  (select count(*) from buildings) as buildings,
  (select count(*) from rooms) as rooms,
  (select count(*) from room_availability_rules) as availability_rules,
  (select count(*) from room_utilities) as room_utilities;
```

### Rooms per building

```sql
select r.building_code, b.name, count(*) as room_count
from rooms r
join buildings b on b.code = r.building_code
group by r.building_code, b.name
order by room_count desc, r.building_code;
```

### Sample availability rules for a room

```sql
select room_id, day, start_time, end_time, valid_from, valid_to
from room_availability_rules
where room_id = 'ML 517'
order by day, start_time, valid_from;
```

---

## 9) Notes

* Models enforce schema shape.
* Complex booking constraints belong in services, not database constraints.
* Ingest is the source of truth for academic room availability.
* Utilities are intentionally populated outside ingest.
* PowerBI will later consume analytics data directly from PostgreSQL or from SQL views.
