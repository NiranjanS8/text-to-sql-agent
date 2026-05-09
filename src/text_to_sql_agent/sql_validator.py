import re
from dataclasses import dataclass


BLOCKED_SQL_KEYWORDS = ("DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "REPLACE", "TRUNCATE")


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


def _ensure_trailing_semicolon(sql: str) -> str:
    return sql if sql.endswith(";") else f"{sql};"

