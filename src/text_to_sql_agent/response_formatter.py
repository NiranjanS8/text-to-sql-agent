import re

from typing import Any

from text_to_sql_agent.query_executor import QueryExecutionResult
from text_to_sql_agent.sql_validator import cleanup_sql


def explain_sql(sql: str) -> str:
    cleaned = cleanup_sql(sql).rstrip(";")
    if not cleaned:
        return "No SQL query was generated."

    selected_columns = _extract_selected_columns(cleaned)
    tables = _extract_tables(cleaned)
    clauses = _extract_clauses(cleaned)

    parts = [f"This query reads {selected_columns}"]
    if tables:
        parts.append(f"from {tables}")
    if clauses:
        parts.append(clauses)
    return " ".join(parts).strip() + "."


def build_final_answer(result: QueryExecutionResult | dict[str, Any]) -> str:
    status = _value(result, "status")
    error = _value(result, "error")
    question = _value(result, "question")
    row_count = int(_value(result, "row_count") or 0)

    if status == "validation_error":
        return f"I could not run the query because it failed safety validation: {error}"
    if status == "sql_error":
        return f"I could not answer the question because SQLite returned an error: {error}"
    if status == "awaiting_approval":
        return "SQL is ready for human approval before execution."
    if status == "edge_case":
        return str(_value(result, "message") or f"The query needed an edge-case explanation for: {question}")
    if row_count == 0:
        return f"No matching rows were found for: {question}"
    data = list(_value(result, "data") or [])
    summary = _summarize_result_rows(data)
    row_text = "row" if row_count == 1 else "rows"
    if summary:
        return f"Found {row_count} matching {row_text}. {summary}"
    return f"Found {row_count} matching {row_text} for: {question}"


def _extract_selected_columns(sql: str) -> str:
    match = re.search(r"\bSELECT\b\s+(.*?)\s+\bFROM\b", sql, flags=re.IGNORECASE)
    if not match:
        return "the requested columns"

    columns = match.group(1).strip()
    if columns == "*":
        return "all columns"
    return f"the column(s) {columns}"


def _extract_tables(sql: str) -> str:
    tables = re.findall(r"\b(?:FROM|JOIN)\b\s+([A-Za-z_][\w.]*)", sql, flags=re.IGNORECASE)
    if not tables:
        return ""

    unique_tables = list(dict.fromkeys(table.split(".")[-1] for table in tables))
    if len(unique_tables) == 1:
        return f"the {unique_tables[0]} table"
    return "the " + ", ".join(unique_tables[:-1]) + f", and {unique_tables[-1]} tables"


def _extract_clauses(sql: str) -> str:
    clauses: list[str] = []
    if re.search(r"\bWHERE\b", sql, flags=re.IGNORECASE):
        clauses.append("filters the rows")
    if re.search(r"\bGROUP BY\b", sql, flags=re.IGNORECASE):
        clauses.append("groups the results")
    if re.search(r"\bORDER BY\b", sql, flags=re.IGNORECASE):
        clauses.append("sorts the output")
    if re.search(r"\bLIMIT\b", sql, flags=re.IGNORECASE):
        clauses.append("limits how many rows are returned")

    if not clauses:
        return ""
    if len(clauses) == 1:
        return f"and {clauses[0]}"
    return "and " + ", ".join(clauses[:-1]) + f", and {clauses[-1]}"


def _summarize_result_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""

    if _has_columns(rows, ("name", "pending_amount")):
        top = max(rows, key=lambda row: _number(row.get("pending_amount")))
        return (
            f"{_display(top.get('name'))} has the highest pending amount of "
            f"{_display(top.get('pending_amount'))}."
        )

    if _has_columns(rows, ("name", "balance")):
        top = max(rows, key=lambda row: _number(row.get("balance")))
        return f"{_display(top.get('name'))} has the highest balance of {_display(top.get('balance'))}."

    if _has_columns(rows, ("name", "amount_due", "amount_paid")):
        balances = [
            {**row, "balance": _number(row.get("amount_due")) - _number(row.get("amount_paid"))}
            for row in rows
        ]
        top = max(balances, key=lambda row: row["balance"])
        return f"{_display(top.get('name'))} has the highest invoice balance of {_display(top.get('balance'))}."

    if _has_columns(rows, ("name", "usage_count")):
        top = max(rows, key=lambda row: _number(row.get("usage_count")))
        return f"{_display(top.get('name'))} leads usage with {_display(top.get('usage_count'))} events."

    if _has_columns(rows, ("name", "course_count")):
        top = max(rows, key=lambda row: _number(row.get("course_count")))
        return f"{_display(top.get('name'))} has the highest course count at {_display(top.get('course_count'))}."

    first = rows[0]
    label_key = next((key for key in ("name", "title", "category", "status", "city") if key in first), None)
    if label_key:
        return f"First result: {_display(first[label_key])}."
    return ""


def _has_columns(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> bool:
    return all(column in rows[0] for column in columns)


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _display(value: Any) -> str:
    return str(value if value is not None else "unknown")


def _value(result: QueryExecutionResult | dict[str, Any], key: str) -> Any:
    if isinstance(result, dict):
        return result.get(key)
    return getattr(result, key)
