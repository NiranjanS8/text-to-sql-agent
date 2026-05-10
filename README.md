# Text-to-SQL Agent

FastAPI backend for asking natural-language questions over SQLite, PostgreSQL, or MongoDB using LangChain and Mistral.

## Sample Domain

The sample database includes both the original education domain and a richer SaaS analytics domain. The SaaS schema supports resume-grade Text-to-SQL questions across:

- organizations, lifecycle stages, industries, regions, and employee counts
- app users, roles, activity, and account ownership
- plans, subscriptions, billing intervals, seat counts, and renewal dates
- invoices, overdue balances, partial payments, and paid/open statuses
- usage events for API calls, agent runs, dashboards, exports, and query execution
- support tickets by priority, category, status, and resolution time
- feature flags and feature adoption metrics

## Evaluation Harness

The project includes a benchmark runner for measuring whether the agent behaves like a production Text-to-SQL system instead of a one-off demo.

Run the default benchmark:

```bash
python scripts/run_eval.py --pretty
```

Write a JSON report:

```bash
python scripts/run_eval.py --output reports/evaluation.json --pretty
```

The evaluator runs a curated set of natural-language questions through the agent pipeline and reports:

- SQL validity rate
- execution success rate
- expected table match rate
- row-count match rate
- final-answer term match rate
- average retry count
- average latency
- per-question pass/fail checks

Default cases cover joins, aggregations, partial payments, top-N queries, empty-result recovery, and impossible-threshold edge cases such as asking for students enrolled in more courses than exist in the database.

## Schema RAG

SQL generation and correction use a lightweight retrieval layer over schema notes, business rules, and live database values. The agent receives the full active database schema plus only the most relevant guidance for the question, such as:

- course title matching with `LIKE`
- student enrollment joins
- pending amount calculation
- revenue aggregation paths
- valid status values
- known course titles, categories, cities, and total course count

This keeps prompts grounded in domain knowledge while preserving a simple local setup.

## Redis Caching

The backend supports optional Redis-backed caching for expensive read paths:

- retrieved schema/RAG context
- generated queries for repeated questions
- corrected queries for repeated repair attempts
- semantic query reuse for paraphrased questions

Cache keys include the question, model, prompt/cache version, schema context, and database fingerprint where relevant, so prompt or data changes do not silently reuse old queries. If `REDIS_URL` is missing or Redis is unavailable, the app falls back to uncached execution.

Semantic caching is conservative: it reuses generated query text only when a normalized question vector is above `SEMANTIC_CACHE_THRESHOLD` in the same model, prompt, and database namespace. Reused queries still go through validation, semantic guardrails, approval mode, and execution policy.

Local Docker Compose starts Redis automatically:

```bash
docker compose up --build
```

For non-Docker runs, configure:

```bash
REDIS_URL=redis://localhost:6379/0
CACHE_TTL_SECONDS=900
ENABLE_SEMANTIC_CACHE=true
SEMANTIC_CACHE_THRESHOLD=0.92
SEMANTIC_CACHE_MAX_ENTRIES=200
```

Cache health is available at:

```text
GET /cache/health
```

## Human Approval Mode

The API and React UI support a human-in-the-loop execution path for safer agentic workflows.

- Normal mode: `/ask` generates, validates, executes, and formats the answer.
- Approval mode: `/ask` with `require_approval: true` generates and validates a query, stores a short-lived approval record, then returns `awaiting_approval` plus an `approval_id` without executing.
- Approval execution: `/approve` consumes the pending `approval_id`, validates the stored query again, executes it once, saves history, and returns the final answer.

Approval records include an integrity hash and expiry timestamp. `/approve` does not accept arbitrary query text, so approval mode acts like a bounded workflow instead of a second execution endpoint.

This demonstrates bounded tool use and human review before database actions.

## Answer Summaries

Final answers include lightweight result-aware summaries instead of only row counts. The formatter highlights useful signals such as highest pending amount, invoice balance, feature usage, course counts, or the first matching entity when the result shape is simple.

## CSV Export

The Results panel can export the current table as a CSV file. Filenames are generated from the natural-language question so saved results are easy to recognize.

## Saved Query Collections

The React UI includes a local saved-query collection in the History rail. Users can save the current natural-language question, rerun saved SaaS or education prompts, and remove saved prompts without changing backend data.

## Semantic Guardrails

The agent applies semantic checks after SQL validation and before database execution. These guardrails catch cases where SQL is technically safe but likely wrong or risky:

- blocks unrequested student email exposure and returns safe student fields
- asks for a clearer metric when ranking questions such as "top students" are ambiguous
- detects payment/revenue questions when generated SQL forgot the `payments` table
- catches invalid generated status filters and returns available domain values
- preserves existing empty-result recovery for impossible thresholds, unknown courses, unknown cities, and out-of-range dates

This gives the project a stronger applied-AI safety story: query execution is bounded not only by syntax, but also by domain intent.

## Query Policy

Query validation enforces a conservative read-only policy before execution:

- exactly one `SELECT` statement
- no write/DDL keywords
- no SQL comments
- no unsafe database file/extension functions
- only public domain tables are queryable
- internal tables such as query history and SQL approvals are hidden from schema prompts and `/schema`

## Docker Deployment

Create a local env file:

```bash
cp .env.example .env
```

Build and run with Docker Compose:

```bash
docker compose up --build
```

The app will be available at:

```text
http://localhost:8000
```

The container builds the React frontend, installs the FastAPI package, initializes the configured database on startup, and persists local SQLite state in the `text_to_sql_data` Docker volume.

## Database Backends

SQLite remains the default backend:

```bash
DATABASE_URL=sqlite:///data/text_to_sql.db
```

PostgreSQL is also supported for the same SQL agent workflow:

```bash
DATABASE_URL=postgresql://text_to_sql:text_to_sql@localhost:5432/text_to_sql
```

The backend detects the dialect from `DATABASE_URL`, initializes the sample schema, introspects public tables, and passes the active dialect into SQL generation and correction prompts. The SQL validator, approval workflow, Redis exact cache, and semantic cache remain shared across SQLite and PostgreSQL.

Docker Compose includes a local Postgres service. To run against it, set `DATABASE_URL` in `.env` to:

```bash
DATABASE_URL=postgresql://text_to_sql:text_to_sql@postgres:5432/text_to_sql
```

MongoDB is supported as a separate document-query workflow:

```bash
DATABASE_URL=mongodb://localhost:27017/text_to_sql
```

For MongoDB, the model generates a safe JSON aggregation envelope:

```json
{"collection":"students","pipeline":[{"$match":{"city":"Delhi"}},{"$limit":10}]}
```

The MongoDB validator allows only approved domain collections and read-only aggregation stages, blocking `$out`, `$merge`, `$where`, `$function`, and other server-side code or write operators. The approval workflow and history APIs keep the same response shape as SQL backends.

Docker Compose includes a local MongoDB service. To run against it from the API container, set:

```bash
DATABASE_URL=mongodb://mongodb:27017/text_to_sql
```

