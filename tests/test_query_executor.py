from pathlib import Path

from text_to_sql_agent.database import initialize_database
from text_to_sql_agent.query_executor import execute_sql


def test_execute_sql_returns_json_ready_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = execute_sql(
        question="Show all students enrolled in Java course",
        sql="""
        SELECT students.name, courses.title
        FROM students
        JOIN enrollments ON enrollments.student_id = students.id
        JOIN courses ON courses.id = enrollments.course_id
        WHERE courses.title = 'Java Masterclass';
        """,
        database_path=database_path,
    )

    assert result.status == "success"
    assert result.row_count == 2
    assert result.data == [
        {"name": "Meera Iyer", "title": "Java Masterclass"},
        {"name": "Kabir Khan", "title": "Java Masterclass"},
    ]
    assert result.to_dict()["data"] == result.data


def test_execute_sql_handles_empty_results(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = execute_sql(
        question="Show students from Jaipur",
        sql="SELECT name FROM students WHERE city = 'Jaipur';",
        database_path=database_path,
    )

    assert result.status == "success"
    assert result.data == []
    assert result.row_count == 0
    assert result.message == "No rows found."


def test_execute_sql_returns_validation_error_without_execution(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = execute_sql(
        question="Delete all students",
        sql="DELETE FROM students;",
        database_path=database_path,
    )

    assert result.status == "validation_error"
    assert result.error == "Only SELECT queries are allowed."
    assert result.data == []


def test_execute_sql_handles_sql_errors(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = execute_sql(
        question="Show unknown column",
        sql="SELECT missing_column FROM students;",
        database_path=database_path,
    )

    assert result.status == "sql_error"
    assert "missing_column" in str(result.error)
    assert result.data == []

