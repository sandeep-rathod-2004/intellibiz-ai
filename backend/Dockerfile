FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["sh", "-c", "case \"${RUN_MIGRATIONS:-false}\" in true) case \"$(printf '%s' \"${ENVIRONMENT:-}\" | tr '[:upper:]' '[:lower:]')\" in prod|production) ;; *) echo 'RUN_MIGRATIONS=true requires ENVIRONMENT=production.' >&2; exit 1 ;; esac; case \"${DATABASE_URL:-}\" in postgresql://*|postgresql+psycopg://*) alembic upgrade head ;; *) echo 'RUN_MIGRATIONS=true requires a PostgreSQL DATABASE_URL.' >&2; exit 1 ;; esac ;; false) ;; *) echo 'RUN_MIGRATIONS must be true or false.' >&2; exit 1 ;; esac; exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
