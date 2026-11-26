# IntelliBiz AI — technical walkthrough and interview preparation

## 90-second project explanation
IntelliBiz AI is a business intelligence and decision-support application. A user uploads a CSV or Excel dataset. The FastAPI service validates the file, associates it with the authenticated user, and uses Pandas to produce a data profile, quality metrics, numeric summaries and categorical distributions. Scikit-learn powers two separate workflows: Isolation Forest identifies unusual multivariate records, while a Random Forest regressor uses lag features for a baseline time-series forecast. A copilot answers supported factual questions with deterministic local analytics and can use a configured LLM provider for other questions. The React dashboard presents the results and generates an executive PDF report.

## Concepts to understand before presenting

### AI, ML and Generative AI
- Artificial Intelligence is the broad field of systems performing tasks associated with intelligent behaviour.
- Machine Learning learns patterns from examples to make predictions or group observations.
- Generative AI produces new text or other content from learned patterns and prompts. In this product, the LLM explains computed dataset facts; it does not replace deterministic calculations.

### Data preparation
Explain schema inspection, type conversion, missing values, duplicate rows, outliers, scaling where required, and why train/test splitting must preserve time order for time-series work. The profiler reports missingness and summary statistics; it does not silently alter the source data. Upload validation is bounded by byte, row, column, cell, and XLSX archive-expansion limits.

### Isolation Forest
Isolation Forest isolates observations by randomly selecting features and split points. An observation isolated in fewer splits tends to be more unusual. `contamination` is a sensitivity assumption that influences the expected flagged proportion; it is not a fraud probability. Evaluate flags with domain review and labelled examples when available.

### Forecasting and Random Forest
The baseline creates lag-1, lag-2, lag-3 and trend features, trains a RandomForestRegressor, evaluates on a chronological holdout, then recursively predicts the requested horizon. MAE is average absolute error; RMSE penalizes larger errors more strongly. Recursive forecasts can compound error. This simple baseline does not explicitly model holidays, seasonality, promotions or external drivers.

### Grounded Generative AI
The copilot receives bounded computed summaries and instructions to distinguish evidence from hypotheses, avoid invented metrics, and state when evidence is insufficient. Supported factual questions use deterministic local analytics without provider requests; other questions can use a server-configured provider. The API key remains on the backend. A production RAG design would add governed document retrieval, source citations, access control, prompt-injection handling and evaluation datasets.

### API and security
FastAPI validates request payloads and exposes versioned endpoints. Passwords are hashed with bcrypt; the API issues signed, expiring JWT access tokens and stores logout revocations. Dataset and conversation endpoints check authenticated ownership. Uploads are limited by extension, size, row count, column count and total cells; files use opaque generated names. Production CORS requires exact HTTPS origins.

## Endpoints
- `POST /api/v1/auth/register` — create account
- `POST /api/v1/auth/login` — obtain JWT
- `GET /api/v1/auth/me` — current account
- `POST /api/v1/datasets/upload` — upload CSV/XLSX
- `GET /api/v1/datasets` — list own datasets
- `GET /api/v1/datasets/{id}/analysis` — profile and insights
- `GET /api/v1/datasets/{id}/anomalies` — Isolation Forest
- `POST /api/v1/datasets/{id}/forecast` — Random Forest forecast
- `POST /api/v1/datasets/{id}/copilot` — grounded AI response
- `GET /api/v1/datasets/{id}/report` — PDF report
- `DELETE /api/v1/datasets/{id}` — delete own dataset

## Honest limitations to disclose
This repository is a portfolio implementation, not a certified enterprise deployment. Alembic migrations and private Supabase Storage are supported, but operators must configure them and rehearse PostgreSQL/object backups. Rate limiting is process-local and needs a shared gateway when scaling. Before production use, add malware scanning, refresh-token rotation, audit trails, tenant roles, observability, backup automation, model monitoring and independent security testing. The sample dataset is synthetic. Never claim that anomaly detection proves fraud or that a baseline forecast guarantees future revenue.

## Demonstration questions
1. Why use Pandas for tabular profiling?
2. Why is the forecast split chronological rather than random?
3. What does Isolation Forest contamination mean?
4. Why calculate KPIs in Python rather than ask the LLM to calculate them?
5. How do you prevent one user from accessing another user's dataset?
6. What are MAE and RMSE, and when can they mislead?
7. How would you scale uploads to millions of rows?
8. How would you add model monitoring and drift detection?
9. How would you evaluate LLM factuality and prompt-injection resistance?
10. What would you change before production deployment?
