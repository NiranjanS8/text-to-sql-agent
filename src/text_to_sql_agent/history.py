from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from text_to_sql_agent.agent_workflow import AgentWorkflowResult
from text_to_sql_agent.database import get_connection, get_database_dialect


@dataclass(frozen=True)
class QueryHistoryRecord:
    id: int | str
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


def save_query_history(workflow: AgentWorkflowResult, database_path: Path | str | None = None) -> QueryHistoryRecord:
    created_at = datetime.now(UTC).isoformat()
    sql_to_store = workflow.execution.sql or workflow.generated_sql
    dialect = get_database_dialect(database_path)

    if dialect == "mongodb":
        with get_connection(database_path) as database:
            result = database["query_history"].insert_one(
                {
                    "question": workflow.question,
                    "generated_sql": sql_to_store,
                    "execution_status": workflow.execution.status,
                    "error_message": workflow.execution.error,
                    "created_at": created_at,
                }
            )
        return QueryHistoryRecord(
            id=str(result.inserted_id),
            question=workflow.question,
            generated_sql=sql_to_store,
            execution_status=workflow.execution.status,
            error_message=workflow.execution.error,
            created_at=created_at,
        )

    with get_connection(database_path) as connection:
        if dialect == "postgresql":
            cursor = connection.execute(
                """
                INSERT INTO query_history (
                    question,
                    generated_sql,
                    execution_status,
                    error_message,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    workflow.question,
                    sql_to_store,
                    workflow.execution.status,
                    workflow.execution.error,
                    created_at,
                ),
            )
            record_id = int(cursor.fetchone()["id"])
        else:
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
            record_id = int(cursor.lastrowid)
        connection.commit()

    return QueryHistoryRecord(
        id=record_id,
        question=workflow.question,
        generated_sql=sql_to_store,
        execution_status=workflow.execution.status,
        error_message=workflow.execution.error,
        created_at=created_at,
    )


def list_query_history(limit: int = 50, database_path: Path | str | None = None) -> list[QueryHistoryRecord]:
    safe_limit = max(1, min(limit, 200))
    dialect = get_database_dialect(database_path)
    if dialect == "mongodb":
        with get_connection(database_path) as database:
            rows = list(database["query_history"].find({}, {"_id": 1, "question": 1, "generated_sql": 1, "execution_status": 1, "error_message": 1, "created_at": 1}).sort("created_at", -1).limit(safe_limit))
        return [
            QueryHistoryRecord(
                id=str(row["_id"]),
                question=row["question"],
                generated_sql=row["generated_sql"],
                execution_status=row["execution_status"],
                error_message=row.get("error_message"),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    with get_connection(database_path) as connection:
        if dialect == "postgresql":
            rows = connection.execute(
                """
                SELECT id, question, generated_sql, execution_status, error_message, created_at
                FROM query_history
                ORDER BY id DESC
                LIMIT %s;
                """,
                (safe_limit,),
            ).fetchall()
        else:
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
