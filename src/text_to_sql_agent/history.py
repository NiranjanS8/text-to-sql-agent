from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from text_to_sql_agent.agent_workflow import AgentWorkflowResult
from text_to_sql_agent.database import get_connection


@dataclass(frozen=True)
class QueryHistoryRecord:
    id: int
    question: str
    generated_sql: str
    execution_status: str
    error_message: str | None
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "generated_sql": self.generated_sql,
            "execution_status": self.execution_status,
            "error_message": self.error_message,
            "created_at": self.created_at,
        }


def save_query_history(workflow: AgentWorkflowResult, database_path: Path | None = None) -> QueryHistoryRecord:
    created_at = datetime.now(UTC).isoformat()
    sql_to_store = workflow.execution.sql or workflow.generated_sql

    with get_connection(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO query_history (
                question,
                generated_sql,
                execution_status,
                error_message,
                created_at
            )
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                workflow.question,
                sql_to_store,
                workflow.execution.status,
                workflow.execution.error,
                created_at,
            ),
        )
        connection.commit()

    return QueryHistoryRecord(
        id=int(cursor.lastrowid),
        question=workflow.question,
        generated_sql=sql_to_store,
        execution_status=workflow.execution.status,
        error_message=workflow.execution.error,
        created_at=created_at,
    )


def list_query_history(limit: int = 50, database_path: Path | None = None) -> list[QueryHistoryRecord]:
    safe_limit = max(1, min(limit, 200))
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, question, generated_sql, execution_status, error_message, created_at
            FROM query_history
            ORDER BY id DESC
            LIMIT ?;
            """,
            (safe_limit,),
        ).fetchall()

    return [
        QueryHistoryRecord(
            id=row["id"],
            question=row["question"],
            generated_sql=row["generated_sql"],
            execution_status=row["execution_status"],
            error_message=row["error_message"],
            created_at=row["created_at"],
        )
        for row in rows
    ]

