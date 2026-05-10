from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from text_to_sql_agent.database import get_connection
from text_to_sql_agent.sql_validator import validate_sql


@dataclass(frozen=True)
class QueryExecutionResult:
    question: str
    sql: str
    data: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    status: str = "success"
    message: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        response: dict[str, Any] = {
            "question": self.question,
            "sql": self.sql,
            "data": self.data,
            "row_count": self.row_count,
            "status": self.status,
        }
        if self.message:
            response["message"] = self.message
        if self.error:
            response["error"] = self.error
        return response


def execute_sql(question: str, sql: str, database_path: Path | str | None = None) -> QueryExecutionResult:
    validation = validate_sql(sql)
    if not validation.is_safe:
        return QueryExecutionResult(
            question=question,
            sql=validation.sql,
            status="validation_error",
            error=validation.error,
        )

    try:
        with get_connection(database_path) as connection:
            rows = connection.execute(validation.sql).fetchall()
    except Exception as exc:
        return QueryExecutionResult(
            question=question,
            sql=validation.sql,
            status="sql_error",
            error=str(exc),
        )

    data = [_row_to_dict(row) for row in rows]
    return QueryExecutionResult(
        question=question,
        sql=validation.sql,
        data=data,
        row_count=len(data),
        message="No rows found." if not data else None,
    )


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    return {key: row[key] for key in row.keys()}
