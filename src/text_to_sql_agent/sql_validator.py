import re
from dataclasses import dataclass


BLOCKED_SQL_KEYWORDS = ("DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "REPLACE", "TRUNCATE")
ALLOWED_TABLES = {
    "app_users",
    "courses",
    "enrollments",
    "feature_adoption",
    "feature_flags",
    "invoices",
    "organizations",
    "payments",
    "plans",
    "students",
    "subscriptions",
    "support_tickets",
    "usage_events",
}
BLOCKED_TABLES = {"query_history", "sql_approvals", "sqlite_master", "sqlite_schema", "sqlite_sequence"}
BLOCKED_FUNCTIONS = ("load_extension", "readfile", "writefile")


class SQLValidationError(ValueError):
    """Raised when generated SQL is unsafe or unsupported."""


@dataclass(frozen=True)
class ValidationResult:
    sql: str
    is_safe: bool
    error: str | None = None


def cleanup_sql(sql: str) -> str:
    cleaned = sql.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").strip()
        if cleaned.lower().startswith("sql"):
            cleaned = cleaned[3:].strip()
        cleaned = cleaned.removesuffix("```").strip()

    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def validate_sql(sql: str) -> ValidationResult:
    cleaned = cleanup_sql(sql)
    if not cleaned:
        return ValidationResult(sql=cleaned, is_safe=False, error="Generated SQL is empty.")

    if _contains_multiple_statements(cleaned):
        return ValidationResult(sql=cleaned, is_safe=False, error="Only one SQL statement is allowed.")

    normalized = cleaned.lstrip().upper()
    if not normalized.startswith("SELECT "):
        return ValidationResult(sql=cleaned, is_safe=False, error="Only SELECT queries are allowed.")

    blocked_keyword = _find_blocked_keyword(cleaned)
    if blocked_keyword:
        return ValidationResult(
            sql=cleaned,
            is_safe=False,
            error=f"Unsafe SQL keyword blocked: {blocked_keyword}.",
        )

    if _contains_comment(cleaned):
        return ValidationResult(sql=cleaned, is_safe=False, error="SQL comments are not allowed.")

    blocked_function = _find_blocked_function(cleaned)
    if blocked_function:
        return ValidationResult(
            sql=cleaned,
            is_safe=False,
            error=f"Unsafe SQL function blocked: {blocked_function}.",
        )

    table_error = _validate_table_policy(cleaned)
    if table_error:
        return ValidationResult(sql=cleaned, is_safe=False, error=table_error)

    return ValidationResult(sql=_ensure_trailing_semicolon(cleaned), is_safe=True)


def assert_safe_sql(sql: str) -> str:
    result = validate_sql(sql)
    if not result.is_safe:
        raise SQLValidationError(result.error or "Generated SQL is unsafe.")
    return result.sql


def _contains_multiple_statements(sql: str) -> bool:
    without_trailing_semicolon = sql.rstrip().removesuffix(";")
    return ";" in without_trailing_semicolon


def _find_blocked_keyword(sql: str) -> str | None:
    for keyword in BLOCKED_SQL_KEYWORDS:
        if re.search(rf"\b{keyword}\b", sql, flags=re.IGNORECASE):
            return keyword
    return None


def _contains_comment(sql: str) -> bool:
    return "--" in sql or "/*" in sql or "*/" in sql


def _find_blocked_function(sql: str) -> str | None:
    for function_name in BLOCKED_FUNCTIONS:
        if re.search(rf"\b{function_name}\s*\(", sql, flags=re.IGNORECASE):
            return function_name
    return None


def _validate_table_policy(sql: str) -> str | None:
    tables = _extract_referenced_tables(sql)
    if not tables:
        return None

    for table in tables:
        normalized = table.lower()
        if normalized in BLOCKED_TABLES or normalized.startswith("sqlite_"):
            return f"Table is not queryable by this agent: {table}."
        if normalized not in ALLOWED_TABLES:
            return f"Unknown or disallowed table referenced: {table}."
    return None


def _extract_referenced_tables(sql: str) -> list[str]:
    matches = re.findall(
        r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)(?:\s+(?:AS\s+)?[A-Za-z_][\w]*)?",
        sql,
        flags=re.IGNORECASE,
    )
    return [match.split(".")[-1] for match in matches]


def _ensure_trailing_semicolon(sql: str) -> str:
    return sql if sql.endswith(";") else f"{sql};"
