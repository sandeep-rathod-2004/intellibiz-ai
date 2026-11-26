# IntelliBiz AI architecture

## Application flow

1. The React/Vite SPA calls the versioned FastAPI API with a bearer JWT. Protected routes share a persistent dashboard shell; page modules are loaded lazily.
2. FastAPI validates the JWT signature and expiry, checks server-side token revocation, and scopes dataset and Copilot conversation queries to the authenticated user.
3. Uploads are restricted to CSV/XLSX, stored under generated opaque object names, and represented by SQLAlchemy `Dataset` records. Development storage is local; production requires the configured private Supabase Storage bucket.
4. Pandas computes dataset profiles, quality metrics, and business summaries. Scikit-learn powers a Random Forest baseline forecast and Isolation Forest anomaly detection.
5. Copilot first handles supported questions from deterministic computed facts. Other questions may use the configured server-side Groq, OpenAI, or Gemini provider. Prompts are bounded and exclude source preview rows; conversations and messages persist in SQL.
6. Alembic owns schema evolution. Its three revisions create missing baseline tables and add dataset hashes and Copilot persistence without replacing existing rows.

## Security boundaries

- Passwords use bcrypt; access tokens are signed, expiring JWTs with server-side logout revocation.
- Dataset and conversation routes use explicit owner-scoped lookups. Storage object keys are not derived from the submitted filename.
- Provider keys and Supabase service-role credentials are backend-only. Provider failure logs include safe identifiers and request metadata, not prompts or credentials.
- Production configuration requires a strong secret, migrations rather than `create_all`, exact HTTPS CORS origins, and Supabase storage. Readiness verifies the database and that the configured bucket is reachable and private.
- Upload limits include bytes, rows, columns, total cells, and XLSX archive expansion. CSV export neutralizes formula-leading values.

## Deployment and operational boundaries

- The backend Docker image runs `alembic upgrade head` before Uvicorn. Run one API worker unless migrations are run as a separate single pre-deploy step and rate limiting is provided by a shared gateway.
- The frontend Docker image serves the Vite build through Nginx with SPA history fallback. Vercel deployments need a build-time public `VITE_API_URL`; the local example URL is development-only.
- SQLite and local files are for development. Hosted PostgreSQL and persistent object storage must be configured and independently backed up. A PostgreSQL migration, restore rehearsal, external storage verification, and live deployment were not performed as part of this repository audit.
- API throttling is currently in-process and does not coordinate across workers or instances. A shared limiter/WAF, observability/alerting, and backup automation remain operator responsibilities.

## Model limitations

- Forecasting is a Random Forest baseline with lag features and chronological holdout metrics; it does not guarantee future outcomes or explicitly model seasonality and external drivers.
- Isolation Forest scores are investigation signals, not fraud probabilities.
- AI output is grounded in computed facts but still requires review. Deterministic local answers are explicitly labeled as not AI-generated.
