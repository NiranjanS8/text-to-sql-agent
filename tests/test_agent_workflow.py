from pathlib import Path

from text_to_sql_agent.agent_workflow import (
    create_sql_correction_tool,
    create_schema_context_tool,
    create_sql_execution_tool,
    create_sql_validation_tool,
    run_agent_pipeline,
)
from text_to_sql_agent.config import Settings
from text_to_sql_agent.database import initialize_database


def test_langchain_tools_wrap_schema_validation_and_execution(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    schema = create_schema_context_tool(database_path).invoke({})
    validation = create_sql_validation_tool().invoke({"sql": "SELECT name FROM students"})
    execution = create_sql_execution_tool(database_path).invoke(
        {"question": "Show students", "sql": validation.sql}
    )

    assert "students(" in schema
    assert validation.is_safe is True
    assert validation.sql == "SELECT name FROM students;"
    assert execution.status == "success"
    assert execution.row_count == 5


def test_run_agent_pipeline_uses_structured_steps(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}")

    def fake_generate_sql(question: str, settings=None) -> str:
        assert question == "Show Java students"
        return """
        SELECT students.name
        FROM students
        JOIN enrollments ON enrollments.student_id = students.id
        JOIN courses ON courses.id = enrollments.course_id
        WHERE courses.title = 'Java Masterclass';
        """

    monkeypatch.setattr("text_to_sql_agent.agent_workflow.generate_sql", fake_generate_sql)

    result = run_agent_pipeline("Show Java students", settings=settings)

    assert "courses(" in result.schema_context
    assert result.validation.is_safe is True
    assert result.validated_sql.endswith(";")
    assert result.execution.status == "success"
    assert result.execution.row_count == 2
    assert result.to_dict()["data"] == [{"name": "Meera Iyer"}, {"name": "Kabir Khan"}]
    assert result.to_dict()["original_sql"] == result.generated_sql
    assert result.to_dict()["corrected_sql"] == []


def test_run_agent_pipeline_corrects_sql_execution_errors(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}")

    monkeypatch.setattr(
        "text_to_sql_agent.agent_workflow.generate_sql",
        lambda question, settings=None: "SELECT student_name FROM students;",
    )

    def fake_correct_sql(question: str, failed_sql: str, error: str, settings=None) -> str:
        assert failed_sql == "SELECT student_name FROM students;"
        assert "student_name" in error
        return "SELECT name FROM students ORDER BY id;"

    monkeypatch.setattr("text_to_sql_agent.agent_workflow.correct_sql", fake_correct_sql)

    result = run_agent_pipeline("Show all student names", settings=settings)

    assert result.generated_sql == "SELECT student_name FROM students;"
    assert result.corrected_sql == ["SELECT name FROM students ORDER BY id;"]
    assert result.retry_count == 1
    assert result.execution.status == "success"
    assert result.execution.row_count == 5
    assert result.to_dict()["data"][0] == {"name": "Aarav Sharma"}


def test_run_agent_pipeline_returns_final_error_when_retries_fail(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}")

    monkeypatch.setattr(
        "text_to_sql_agent.agent_workflow.generate_sql",
        lambda question, settings=None: "SELECT missing_one FROM students;",
    )

    corrections = iter(["SELECT missing_two FROM students;", "SELECT missing_three FROM students;"])

    def fake_correct_sql(question: str, failed_sql: str, error: str, settings=None) -> str:
        return next(corrections)

    monkeypatch.setattr("text_to_sql_agent.agent_workflow.correct_sql", fake_correct_sql)

    result = run_agent_pipeline("Show broken column", settings=settings, max_retries=2)

    assert result.corrected_sql == ["SELECT missing_two FROM students;", "SELECT missing_three FROM students;"]
    assert result.retry_count == 2
    assert result.execution.status == "sql_error"
    assert "missing_three" in str(result.execution.error)
    assert result.to_dict()["error"] == result.execution.error


def test_sql_correction_tool_wraps_repair_function(monkeypatch) -> None:
    monkeypatch.setattr(
        "text_to_sql_agent.agent_workflow.correct_sql",
        lambda question, failed_sql, error, settings=None: "SELECT name FROM students;",
    )

    result = create_sql_correction_tool().invoke(
        {
            "question": "Show names",
            "failed_sql": "SELECT missing FROM students;",
            "error": "no such column: missing",
        }
    )

    assert result == "SELECT name FROM students;"
