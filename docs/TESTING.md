# Validation checklist

## Backend
- Register with a valid full name, email, password (10–72 UTF-8 bytes), and matching password confirmation; confirm registration does not issue a token.
- Confirm duplicate email registration returns HTTP 409.
- Sign in and verify `/auth/me`, log out, and verify that the revoked token returns HTTP 401.
- Verify existing accounts with passwords shorter than the current registration minimum can still sign in.
- Upload a valid CSV and XLSX file.
- Confirm unsupported extensions and oversized files are rejected.
- Confirm a user cannot retrieve, delete, or analyse another user's dataset.
- Verify dataset preview search, sorting, and pagination remain owner-scoped.
- Verify uploads reject invalid encodings, too many rows/columns/cells, oversized files, and XLSX archives over the expansion limit without returning parser contents.
- Verify `/health/ready` reports local storage as degraded and fails when the configured Supabase bucket is missing, public, or unreachable.
- Check missing-value percentages and numeric summaries against a manual calculation.
- Run anomaly detection and inspect flagged records.
- Run a forecast with a date and target field; inspect chronological holdout MAE/RMSE.
- Confirm supported Copilot questions return labeled local computed answers without provider calls. Provider and quota behavior must use mocked SDK responses; never use paid API calls in automated tests.
- Download and open the PDF report.
- Run Alembic migration tests against temporary databases and confirm existing rows remain.

## Frontend
- Verify responsive layout at desktop, tablet and mobile widths.
- Test registration, login, logout, upload, dataset switching and deletion.
- Test overview, data explorer, forecast, anomaly and copilot views.
- Test API error messages, loading states and reduced-motion preference.

## Automated tests
Run `pytest` from the backend directory. Add integration tests and coverage for auth, upload limits, ownership, report generation and API error cases before production.

Run the frontend checks from `frontend/`:

```bash
npx tsc --noEmit
npm run build
node --test src/lib/providerStatus.test.mjs
npm audit
```

Dependency scans do not replace a PostgreSQL/Supabase deployment test, a backup-restore rehearsal, or an independent penetration test. The application does not currently have an automated browser end-to-end suite.
