import pytest

from text_to_sql_agent.sql_validator import SQLValidationError, assert_safe_sql, cleanup_sql, validate_sql


def test_cleanup_sql_removes_markdown_fences_and_normalizes_whitespace() -> None:
    raw = "```sql\nSELECT   *\nFROM students\n```"

    assert cleanup_sql(raw) == "SELECT * FROM students"


def test_validate_sql_allows_single_select_query() -> None:
    result = validate_sql("SELECT name FROM students")

    assert result.is_safe is True
    assert result.sql == "SELECT name FROM students;"
    assert result.error is None


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE students;",
        "DELETE FROM students;",
        "UPDATE students SET city = 'Delhi';",
        "INSERT INTO students (name) VALUES ('A');",
        "ALTER TABLE students ADD COLUMN phone TEXT;",
    ],
)
def test_validate_sql_blocks_dangerous_queries(sql: str) -> None:
    result = validate_sql(sql)

    assert result.is_safe is False
    assert result.error == "Only SELECT queries are allowed."


def test_validate_sql_blocks_dangerous_keyword_inside_select() -> None:
    result = validate_sql("SELECT * FROM students; DROP TABLE students;")

    assert result.is_safe is False
    assert result.error == "Only one SQL statement is allowed."


def test_validate_sql_blocks_system_tables() -> None:
    result = validate_sql("SELECT question FROM query_history;")

    assert result.is_safe is False
    assert result.error == "Table is not queryable by this agent: query_history."


def test_validate_sql_blocks_unknown_tables() -> None:
    result = validate_sql("SELECT * FROM secrets;")

    assert result.is_safe is False
    assert result.error == "Unknown or disallowed table referenced: secrets."


def test_validate_sql_blocks_sql_comments() -> None:
    result = validate_sql("SELECT name FROM students -- explain")

    assert result.is_safe is False
    assert result.error == "SQL comments are not allowed."


def test_validate_sql_blocks_unsafe_functions() -> None:
    result = validate_sql("SELECT load_extension('x') FROM students;")

    assert result.is_safe is False
    assert result.error == "Unsafe SQL function blocked: load_extension."


def test_assert_safe_sql_raises_clear_error() -> None:
    with pytest.raises(SQLValidationError, match="Only SELECT queries are allowed"):
        assert_safe_sql("DELETE FROM payments;")
