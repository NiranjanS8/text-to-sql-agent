import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from text_to_sql_agent.database import get_connection, get_database_dialect
from text_to_sql_agent.sql_validator import cleanup_sql


APPROVAL_TTL_MINUTES = 15


class ApprovalError(ValueError):
    """Raised when a SQL approval record cannot be used."""


@dataclass(frozen=True)
class SQLApprovalRecord:
    id: str
    question: str
    sql: str
    sql_hash: str
    status: str
    created_at: str
    expires_at: str
    approved_at: str | None = None


def create_sql_approval(
    question: str,
    sql: str,
    database_path: Path | str | None = None,
    ttl_minutes: int = APPROVAL_TTL_MINUTES,
) -> SQLApprovalRecord:
    created_at = datetime.now(UTC)
    expires_at = created_at + timedelta(minutes=ttl_minutes)
    normalized_sql = normalize_query_artifact(sql)
    record = SQLApprovalRecord(
        id=secrets.token_urlsafe(24),
        question=question,
        sql=normalized_sql,
        sql_hash=hash_sql(normalized_sql),
        status="pending",
        created_at=created_at.isoformat(),
        expires_at=expires_at.isoformat(),
    )
    dialect = get_database_dialect(database_path)

    if dialect == "mongodb":
        with get_connection(database_path) as database:
            database["sql_approvals"].insert_one(record.__dict__)
        return record

    with get_connection(database_path) as connection:
        placeholder = "%s" if dialect == "postgresql" else "?"
        connection.execute(
            f"""
            INSERT INTO sql_approvals (
                id,
                question,
                sql,
                sql_hash,
                status,
                created_at,
                expires_at,
                approved_at
            )
            VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder});
            """,
            (
                record.id,
                record.question,
                record.sql,
                record.sql_hash,
                record.status,
                record.created_at,
                record.expires_at,
                record.approved_at,
            ),
        )
        connection.commit()

    return record


def consume_sql_approval(approval_id: str, database_path: Path | str | None = None) -> SQLApprovalRecord:
    dialect = get_database_dialect(database_path)
    if dialect == "mongodb":
        with get_connection(database_path) as database:
            row = database["sql_approvals"].find_one({"id": approval_id})
            if row is None:
                raise ApprovalError("Approval record was not found.")
            record = _record_from_mapping(row)
            _validate_approval_record(record)
            approved_at = datetime.now(UTC).isoformat()
            database["sql_approvals"].update_one(
                {"id": approval_id, "status": "pending"},
                {"$set": {"status": "approved", "approved_at": approved_at}},
            )
        return SQLApprovalRecord(
            id=record.id,
            question=record.question,
            sql=record.sql,
            sql_hash=record.sql_hash,
            status="approved",
            created_at=record.created_at,
            expires_at=record.expires_at,
            approved_at=approved_at,
        )

    with get_connection(database_path) as connection:
        placeholder = "%s" if dialect == "postgresql" else "?"
        row = connection.execute(
            f"""
            SELECT id, question, sql, sql_hash, status, created_at, expires_at, approved_at
            FROM sql_approvals
            WHERE id = {placeholder};
            """,
            (approval_id,),
        ).fetchone()

        if row is None:
            raise ApprovalError("Approval record was not found.")

        record = SQLApprovalRecord(
            id=row["id"],
            question=row["question"],
            sql=row["sql"],
            sql_hash=row["sql_hash"],
            status=row["status"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            approved_at=row["approved_at"],
        )
        _validate_approval_record(record)

        approved_at = datetime.now(UTC).isoformat()
        connection.execute(
            f"""
            UPDATE sql_approvals
            SET status = 'approved', approved_at = {placeholder}
            WHERE id = {placeholder} AND status = 'pending';
            """,
            (approved_at, approval_id),
        )
        connection.commit()

    return SQLApprovalRecord(
        id=record.id,
        question=record.question,
        sql=record.sql,
        sql_hash=record.sql_hash,
        status="approved",
        created_at=record.created_at,
        expires_at=record.expires_at,
        approved_at=approved_at,
    )


def hash_sql(sql: str) -> str:
    return hashlib.sha256(normalize_query_artifact(sql).encode("utf-8")).hexdigest()


def normalize_query_artifact(query: str) -> str:
    cleaned = query.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").strip()
        if cleaned.lower().startswith(("sql", "json", "javascript", "js")):
            cleaned = cleaned.split(None, 1)[1] if len(cleaned.split(None, 1)) == 2 else ""
        cleaned = cleaned.removesuffix("```").strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return cleanup_sql(query)
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def _record_from_mapping(row: object) -> SQLApprovalRecord:
    return SQLApprovalRecord(
        id=row["id"],
        question=row["question"],
        sql=row["sql"],
        sql_hash=row["sql_hash"],
        status=row["status"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        approved_at=row.get("approved_at"),
    )


def _validate_approval_record(record: SQLApprovalRecord) -> None:
    if record.status != "pending":
        raise ApprovalError("Approval record has already been used.")
    if hash_sql(record.sql) != record.sql_hash:
        raise ApprovalError("Approval record failed integrity validation.")
    expires_at = datetime.fromisoformat(record.expires_at)
    if expires_at <= datetime.now(UTC):
        raise ApprovalError("Approval record has expired.")
