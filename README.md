# Telegram Agents Web

This repository is organized as a conventional web application with a Python
backend and a React frontend.

```text
backend/
  src/tg_agent_bot/        Python package: Telegram bots, WebSocket API, services
  tests/                   Python tests
  docs/                    Backend architecture and protocol notes
  pyproject.toml
  requirements.txt
  .env.example

frontend/
  src/                     React app
  package.json
  tailwind.config.js
  vite.config.ts

scripts/                   Local development and verification helpers
.editorconfig              Shared editor formatting defaults
.github/workflows/ci.yml   Backend test and frontend build checks
README.md
```

## Local Shortcuts

From the repository root, PowerShell helpers are available for the common
developer loops:

```powershell
.\scripts\dev-backend.ps1
.\scripts\dev-frontend.ps1
.\scripts\check.ps1
```

`check.ps1` runs the backend test suite and the frontend production build.

## Backend

The Python package lives under `backend/src`, so install the backend package
before running `python -m tg_agent_bot...`.

From the repository root, using the checked-in local virtual environment:

```powershell
.\.venv\Scripts\python -m pip install -e .\backend
```

Or from the backend directory:

```powershell
cd backend
python -m pip install -e .
```

For development tooling such as Ruff and MyPy:

```powershell
python -m pip install -e ".[dev]"
```

Create local configuration:

```powershell
cd backend
Copy-Item .env.example .env
```

Fill in the real Telegram bot tokens and Codex API values in `backend/.env`.

Start the WebSocket backend from `backend/`:

```powershell
cd backend
python -m tg_agent_bot.web
```

Or use the repository shortcut from the root:

```powershell
.\scripts\dev-backend.ps1
```

The WebSocket endpoint is:

```text
ws://127.0.0.1:8000/ws/chat
```

The original Telegram bot runtime is also available from `backend/`:

```powershell
cd backend
python -m tg_agent_bot A
python -m tg_agent_bot B
python -m tg_agent_bot C
python -m tg_agent_bot D
```

## Frontend

Install dependencies and start the React app from `frontend/`:

```powershell
cd frontend
npm install
npm run dev
```

Or use the repository shortcut from the root:

```powershell
.\scripts\dev-frontend.ps1
```

Optional frontend-only environment overrides can be copied from
`frontend/.env.example` into `frontend/.env.local`.

Open:

```text
http://127.0.0.1:5173
```

The frontend connects to `ws://127.0.0.1:8000/ws/chat` by default. To use a
different backend URL, set `VITE_WS_URL`.

## Verification

Backend tests:

```powershell
cd backend
python -m pytest
```

Or from the root:

```powershell
.\scripts\check.ps1
```

Frontend production build:

```powershell
cd frontend
npm run build
```

Frontend type checking:

```powershell
cd frontend
npm run typecheck
```

## Current Integration

The first web version calls the existing backend domain services directly from
the WebSocket layer:

```text
frontend React UI
  -> backend WebSocket API
  -> planner / calendar / weather / slot matcher / memory
```

The existing Telegram bot-to-bot protocol and bot entrypoints remain in the
backend package, so the web interface can evolve without removing Telegram
support.

The web UI also includes direct function views. For example, the Schedule
button requests structured calendar data over WebSocket and renders a 7-day
timetable without asking the LLM to format a chat response.
