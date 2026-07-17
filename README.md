# Exchange

Spot crypto exchange. Early scaffold.

Read [docs/00-reality-check.md](docs/00-reality-check.md) before planning anything —
the code is the easy part.

```
client/     React + TypeScript (Vite)
server/     Python + FastAPI
docs/       research: what Binance is, how exchanges work, the plan
```

## Prerequisites

Node 22+ · Python 3.13+ · Docker Desktop (must be **running**)

## Setup

```bash
# 1. infrastructure
docker compose up -d

# 2. backend
cd server
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux
cp .env.example .env

# 3. frontend
cd ../client
npm install
cp .env.example .env
```

## Run

```bash
docker compose up -d          # Postgres + Redis

cd server && python run.py    # http://localhost:8000  — use run.py, not `uvicorn` directly
cd client && npm run dev      # http://localhost:5173
```

| | URL |
|---|---|
| Frontend | http://localhost:5173 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/api/v1/docs |
| Postgres | `localhost:5433` (not 5432 — see below) |
| Redis | `localhost:6379` |

The frontend's landing page is a live connectivity check: it goes green only when the API and
the database both answer.

## Two environment quirks on this machine

Both are real and will bite you again if you forget them.

**1. Postgres is on host port 5433, not 5432.**
A native Windows PostgreSQL service already owns 5432 here. Docker will happily publish a second
listener on the same port and lose the race, and you get `password authentication failed for user
"binance"` — because you reached the *native* Postgres, which has no such user. The container
speaks 5432 internally; only the host port moved.

**2. Start the API with `python run.py`, never `uvicorn app.main:app`.**
Windows defaults to `ProactorEventLoop`, which psycopg's async mode refuses to run on. The loop
policy has to be set before uvicorn builds its loop, so it cannot live in `app/main.py` —
uvicorn imports the app from inside an already-running loop. `run.py` sets it first. This is a
no-op on Linux/macOS and in production.

### If the API serves stale config after a restart

`reload=True` spawns a `multiprocessing` child. Killing the parent leaves that child alive and
still holding port 8000 — and its command line says `spawn_main`, not `run.py`, so a naive
`pkill -f run.py` misses it. Windows then lets the new server bind 8000 *too*, and your requests
land on the zombie. Symptom: you fixed the config, the log says startup complete, and the error
message still quotes the old value.

```powershell
# find every listener on 8000, including orphans
Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object {
  "PID $($_.OwningProcess): $((Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)").CommandLine)"
}
Stop-Process -Id <pid> -Force
```

### Errors must be returned, not raised — or the browser can't read them

Starlette's `ServerErrorMiddleware` sits *outside* `CORSMiddleware`, so an unhandled exception
produces a 500 with **no CORS headers at all**. The browser blocks it, and the frontend sees an
opaque network error instead of your status code and body. Every error a browser client needs to
read has to be a returned response with an explicit status — see `health_db` in
`server/app/api/routes/health.py`, which returns 503 rather than letting the driver error escape.

### `reload=True` does not always reload

WatchFiles missed a change to `app/core/db.py` here, and the worker kept serving stale config —
the log said "startup complete" while the behaviour was from the previous edit. If a change
seems to have no effect, kill the tree (parent *and* the `spawn_main` child) and start fresh
before debugging the code.

## The one rule

**Money is never a float.** `server/app/core/money.py` enforces it — it rejects `float` inputs
outright and refuses to silently round away precision. Read its docstring before touching any
balance, price, or quantity. This is cheap now and impossible to retrofit later.

## Status

Scaffold only: health checks, config, DB connection, the money primitives.
No engine, no ledger tables, no auth yet. Next steps in [docs/02-plan.md](docs/02-plan.md).
