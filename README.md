# Text-to-SQL Agent

FastAPI backend for asking natural-language questions over a SQLite database using LangChain and Mistral.

## Sample Domain

The SQLite database includes both the original education domain and a richer SaaS analytics domain. The SaaS schema supports resume-grade Text-to-SQL questions across:

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

SQL generation and correction use a lightweight retrieval layer over schema notes, business rules, and live database values. The agent receives the full SQLite schema plus only the most relevant guidance for the question, such as:

- course title matching with `LIKE`
- student enrollment joins
- pending amount calculation
- revenue aggregation paths
- valid status values
- known course titles, categories, cities, and total course count

This keeps prompts grounded in domain knowledge while preserving a simple local setup.

## Human Approval Mode

The API and React UI support a human-in-the-loop execution path for safer agentic workflows.

- Normal mode: `/ask` generates, validates, executes, and formats the answer.
- Approval mode: `/ask` with `require_approval: true` generates and validates SQL, then returns `awaiting_approval` without executing.
- Approval execution: `/approve` validates the reviewed SQL again, executes it, saves history, and returns the final answer.

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

The container builds the React frontend, installs the FastAPI package, initializes SQLite on startup, and persists database state in the `text_to_sql_data` Docker volume.

