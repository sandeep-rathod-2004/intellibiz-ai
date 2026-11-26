# IntelliBiz AI

**Intelligent Business Analytics & AI Decision Support Platform**

An enterprise-style full-stack reference implementation for turning uploaded business data into explainable analytics, machine-learning forecasts, anomaly signals, and grounded AI-assisted business summaries.

## Product capabilities
- CSV/XLSX ingestion with validation, safe filenames, file/row/column/cell limits, and per-user dataset ownership.
- Automated profiling, missing-value summaries, numeric/categorical insights, KPIs, and chart-ready series.
- Machine learning: Isolation Forest anomaly detection and lag-feature Random Forest forecasting (with explicit limitations and evaluation metrics).
- Grounded Copilot using computed dataset facts as context; Groq GPT-OSS 20B is the default optional provider, with OpenAI/Gemini alternatives and a deterministic local analytics fallback.
- Separate registration and login, bcrypt password hashing, signed expiring JWTs with server-side logout revocation, protected React routes, SQLAlchemy persistence, and per-user dataset ownership.
- Paginated, searchable, sortable dataset previews; dataset detail pages, refreshable library, and a downloadable sample CSV.
- PDF executive report generation, Docker Compose, tests, and deployment notes.
- Premium responsive React dashboard with animated navigation, charts, glass panels, dark/light theme, motion and accessible reduced-motion support.

## Stack
React 18 + Vite + TypeScript + Tailwind CSS + Framer Motion + Recharts; Python 3.11+ + FastAPI + SQLAlchemy + Pandas + scikit-learn; SQLite by default / PostgreSQL in deployment; optional Groq/OpenAI/Gemini.

## Quick start

### 1. Backend
```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Windows: copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```
API docs: http://localhost:8000/docs

### 2. Frontend
```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```
Open http://localhost:5173. Register an account with a full name, email, password, and confirmation. Registration does not sign you in; return to Login and enter the new credentials. Download the retail sample from the empty dashboard or upload `sample-data/retail_sales.csv`, then explore the dashboard.

### 3. Docker
From the project root, first create the environment file:
```bash
cp backend/.env.example backend/.env
# Docker runs Alembic migrations before starting the API.
docker compose up --build
```
Frontend: http://localhost:5173; API: http://localhost:8000/docs. The frontend image serves the production Vite build and falls back to `index.html` for client-side routes.

## AI provider setup
The default provider is Groq with `AI_PROVIDER=groq`, `GROQ_MODEL=openai/gpt-oss-20b`, and `GROQ_BASE_URL=https://api.groq.com/openai/v1`. Put `GROQ_API_KEY` in `backend/.env`; credentials remain server-side. To switch providers, set `AI_PROVIDER=openai` with `OPENAI_API_KEY`/`OPENAI_MODEL`, `AI_PROVIDER=gemini` with `GEMINI_API_KEY`/`GEMINI_MODEL`, or `AI_PROVIDER=local` for deterministic dataset analytics only. `AI_PROVIDER=none` remains supported as an alias for local-only behavior. `COPILOT_TOKEN_BUDGET` controls the completion output budget; if unset, the legacy `OPENAI_MAX_OUTPUT_TOKENS` value is used. `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES`, and `COPILOT_MAX_CONTEXT_CHARS` bound provider requests. Pydantic loads the absolute `backend/.env` path; process environment variables override dotenv values, and settings load once when the API starts. Restart the backend after changing provider settings. The Copilot uses compact computed dataset facts, never the source CSV rows. Supported local analytics questions are answered from those computed facts without provider calls; when Groq is unavailable or quota-limited, the response is explicitly labeled as local computed analysis, not AI-generated. Never commit `.env` files.

To explicitly check OpenAI authentication without running a model completion, first set `AI_PROVIDER=openai`, then use the local-development-only models-list diagnostic from `backend/`:
```cmd
cd backend
.venv\Scripts\activate
python -m app.diagnostics
```
This makes one short-timeout `GET /v1/models` request, never prints the key, and reports only the configured source and sanitized result. The development server also exposes the explicit `POST /api/v1/copilot/diagnostics/openai` check to loopback callers only. A successful response verifies authentication for the models-list endpoint only; it does not prove access to `OPENAI_MODEL` or chat completions. Neither check runs automatically on page render or application startup, and tests mock all provider requests. Do not use the command or endpoint with `ENVIRONMENT=production`.

If local diagnostics report `key_source: process_environment` and `settings_match_backend_dotenv: false`, a process-level `OPENAI_API_KEY` is overriding the backend file. Stop the running API with Ctrl+C, then start it from a fresh Windows CMD session without that override:
```cmd
cd /d D:\Projects\IntelliBiz_AI_Full_Project\intellibiz-ai\backend
set "OPENAI_API_KEY="
call .venv\Scripts\activate.bat
python -m uvicorn app.main:app --reload --port 8000
```
Then explicitly check the running process with:
```cmd
curl.exe --request POST http://127.0.0.1:8000/api/v1/copilot/diagnostics/openai
```
The response must show `key_source: backend_dotenv`, `settings_match_backend_dotenv: true`, and the `authentication_verified` status before it is considered resolved.

## Important implementation notes
- Forecasting is a baseline model, not a promise of future performance. It requires sufficient chronological observations and reports MAE/RMSE on a chronological holdout.
- The anomaly detector flags statistical outliers, not fraud. Review flagged rows before taking action.
- Upload limits and file types are configurable. CSV/XLSX uploads have compressed file, row, column, cell, and Excel archive-expansion limits. The API applies process-local rolling-window limits to authentication and Copilot requests; this is not a distributed limiter, so use a shared gateway/WAF policy before running multiple API workers/replicas. Local uploads use the filesystem and may not survive a hosted-instance restart; production configuration requires Supabase Storage, and `/health/ready` verifies the configured bucket is reachable and private.
- This starter uses SQLite for local development. Set `DATABASE_URL` to a PostgreSQL connection string for deployment.
- Alembic migrations are required for existing databases and are run automatically by Docker Compose before the API starts. For a manually run production API, run `alembic upgrade head` from `backend/` before startup and set `AUTO_CREATE_SCHEMA=false`.
- For production, set `ENVIRONMENT=production`, a unique random `SECRET_KEY` of at least 32 characters, `AUTO_CREATE_SCHEMA=false`, exact HTTPS `CORS_ORIGINS`, a hosted database, and private Supabase Storage. Production startup rejects local storage, wildcard or HTTP CORS origins, and automatic schema creation. Configure the frontend build-time `VITE_API_URL` to the public HTTPS API URL.
- `/health` is a liveness check. `/health/ready` checks the database and storage; local storage is explicitly reported as degraded, while unavailable or public Supabase buckets fail readiness.
- The in-memory rate limiter is process-local. Run one API worker unless a shared gateway/limiter is configured; multiple workers do not share counters. Set trusted proxy handling at the hosting layer so client IPs are not collapsed to a single proxy address.

## Zero-budget deployment option

This is a low-cost deployment recipe, not a promise that any provider's free tier, quota, or availability will remain unchanged. Free services can sleep, impose limits, or require payment details. The OpenAI/Gemini provider is optional and may incur separate charges; leave `AI_PROVIDER=none` unless you have explicitly configured a provider.

One possible arrangement is a Vercel static frontend, a Render free web service using the backend Dockerfile, and Supabase free-tier PostgreSQL plus private object storage:

1. Create a Supabase project. Create a **private** Storage bucket named `intellibiz-datasets`. Use the project's PostgreSQL connection URI (prefer its session pooler if the hosting provider cannot reach the direct database host) and require TLS. The SQLAlchemy URI must use `postgresql+psycopg://`; URL-encode special characters in the database password.
2. Deploy `backend/` as a Docker web service. Set `ENVIRONMENT=production`, a randomly generated `SECRET_KEY` (at least 32 characters), `AUTO_CREATE_SCHEMA=false`, `DATABASE_URL`, `CORS_ORIGINS` (the exact HTTPS frontend origin), `DATA_STORAGE_BACKEND=supabase`, `SUPABASE_URL`, `SUPABASE_STORAGE_BUCKET=intellibiz-datasets`, and `SUPABASE_SERVICE_ROLE_KEY`. Keep the service-role key only in the backend's secret environment, never in the frontend or repository. Keep `AI_PROVIDER=none` if no paid AI provider is configured. The container runs Alembic migrations before starting the API.
3. Deploy `frontend/` as a Vercel Vite project. Set `VITE_API_URL` to the backend's public URL plus `/api/v1` (for example `https://your-api.example/api/v1`) in the build environment. The production bundle fails at startup if this variable is omitted instead of silently targeting localhost.
4. Verify `/health/ready` reports `"status":"ready"` and a private Supabase bucket, register a new account, upload a small CSV, reload its preview, and delete it. Check provider terms, quotas, backup/restore, cold-start behavior, and database connection limits before real use.

### Backups and restore

- **SQLite development:** stop the backend before copying `backend/intellibiz.db` and `backend/uploads/`. Keep the database and upload files from the same backup point. Restore both to the same paths while the backend is stopped, then verify dataset reads and Copilot history before reopening access.
- **Hosted PostgreSQL:** configure scheduled provider snapshots or run `pg_dump` to protected storage, and periodically rehearse restore into a separate database. A database backup alone does not include uploaded objects.
- **Supabase Storage:** maintain a separate inventory/backup of the private bucket objects. Preserve each dataset row's `stored_name` exactly; restore database and object backups together. Verify object counts and hashes before switching traffic.
- Store backups encrypted and access-restricted. Do not put database URLs, service-role keys, or backup files in the repository. No backup/restore operation has been run against the user's live data as part of this audit.

### Moving existing local uploads

Switching `DATA_STORAGE_BACKEND` does not copy files. Back up both the database and `backend/uploads/` first. For each dataset row, obtain its exact `stored_name` and upload the corresponding `backend/uploads/<stored_name>` file to the root of the configured **private** Supabase bucket using that exact object name. Verify every object exists and matches the local file size (ideally a locally computed SHA-256) before switching the backend setting and restarting the API. Do not delete the local copy until uploads and dataset reads have been verified. New uploads after switching use cloud storage; no credentials or dataset content should be placed in deployment logs.

## Tests
```bash
cd backend
python -m pytest
```
Frontend checks:
```bash
cd frontend
npx tsc --noEmit
npm run build
node --test src/lib/providerStatus.test.mjs
npm audit
```

## Suggested demo flow
1. Register and sign in.
2. Upload `retail_sales.csv`.
3. Review data quality and KPI cards.
4. Run anomaly detection and forecasting.
5. Ask the copilot: “What changed in sales and what should I investigate?”
6. Download an executive PDF report.

## Repository structure
```text
backend/app/       FastAPI application, API routes, services, ML, models
frontend/src/      React app, components, pages, styles, API client
sample-data/       Reproducible retail dataset
```
