from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from text_to_sql_agent.approvals import (
    ApprovalError,
    consume_sql_approval,
    create_sql_approval,
    hash_sql,
    normalize_query_artifact,
)
from text_to_sql_agent.database import get_connection, initialize_database


def test_create_and_consume_sql_approval(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    created = create_sql_approval(
        "Show names",
        "SELECT name FROM students ORDER BY id;",
        database_path=database_path,
    )
    consumed = consume_sql_approval(created.id, database_path=database_path)

    assert consumed.id == created.id
    assert consumed.question == "Show names"
    assert consumed.sql == "SELECT name FROM students ORDER BY id;"
    assert consumed.sql_hash == hash_sql(consumed.sql)
    assert consumed.status == "approved"
    assert consumed.approved_at is not None


def test_consume_sql_approval_rejects_reuse(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    created = create_sql_approval("Show names", "SELECT name FROM students;", database_path=database_path)

    consume_sql_approval(created.id, database_path=database_path)

    with pytest.raises(ApprovalError, match="already been used"):
        consume_sql_approval(created.id, database_path=database_path)


def test_consume_sql_approval_rejects_expired_record(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    created = create_sql_approval("Show names", "SELECT name FROM students;", database_path=database_path)
    expired_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()

    with get_connection(database_path) as connection:
        connection.execute("UPDATE sql_approvals SET expires_at = ? WHERE id = ?;", (expired_at, created.id))
        connection.commit()

    with pytest.raises(ApprovalError, match="expired"):
        consume_sql_approval(created.id, database_path=database_path)


def test_consume_sql_approval_rejects_tampered_sql(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    created = create_sql_approval("Show names", "SELECT name FROM students;", database_path=database_path)

    with get_connection(database_path) as connection:
        connection.execute("UPDATE sql_approvals SET sql = ? WHERE id = ?;", ("SELECT email FROM students;", created.id))
        connection.commit()

    with pytest.raises(ApprovalError, match="integrity"):
        consume_sql_approval(created.id, database_path=database_path)


def test_normalize_query_artifact_preserves_json_string_spaces() -> None:
    query = '{"collection":"students","pipeline":[{"$match":{"city":"New Delhi"}}]}'

    normalized = normalize_query_artifact(query)

    assert '"New Delhi"' in normalized
    assert hash_sql(query) == hash_sql(normalized)
