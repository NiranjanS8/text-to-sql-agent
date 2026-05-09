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

