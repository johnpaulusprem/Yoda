# How to run the app

The app requires **Python 3.11+** (uses `|` union syntax and other 3.10+ features).

## Option 1: Python 3.11+ on your machine

1. **Install Python 3.11** (if needed):
   - macOS: `brew install python@3.11`. Then use `/opt/homebrew/bin/python3.11` (or run `brew link python@3.11` to get `python3.11` in PATH).
   - Or download from [python.org](https://www.python.org/downloads/)

2. **Create venv and install** (from `teams-meeting-assistant/`):
   ```bash
   /opt/homebrew/bin/python3.11 -m venv .venv   # or: python3.11 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

3. **Configure env**  
   Copy `deployment/.env.template` or `deployment/.env` to `.env` in this directory and set at least `DATABASE_URL` and `BASE_URL`.

4. **Run**:
   ```bash
   .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

5. **Database**  
   Run PostgreSQL (e.g. via Docker) and apply migrations:
   ```bash
   .venv/bin/alembic upgrade head
   ```

## Option 2: Docker Compose (recommended)

From the repo root (or from `teams-meeting-assistant/`):

```bash
# Ensure .env exists (e.g. copy from deployment/.env)
cp deployment/.env .env   # if needed

# Start app + Postgres + Redis
docker compose -f deployment/docker-compose.yml up --build
```

App will be at **http://localhost:8000**. Run migrations inside the container or against the exposed Postgres port.

---

If you see `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`, you are on Python 3.9 or 3.10; switch to Python 3.11+ or use Docker.
