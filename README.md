# Text-to-SQL Agent

FastAPI backend for asking natural-language questions over a SQLite database using LangChain and Mistral.

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

