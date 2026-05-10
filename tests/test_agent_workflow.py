from pathlib import Path

from text_to_sql_agent.agent_workflow import (
    execute_approved_sql,
    create_sql_correction_tool,
    create_sql_explanation_tool,
    create_final_answer_tool,
    create_schema_context_tool,
    create_sql_execution_tool,
    create_sql_validation_tool,
    prepare_sql_for_approval,
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
    assert execution.row_count == 10


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
    assert "Retrieved business rules:" in result.schema_context
    assert "Course title matching" in result.schema_context
    assert result.validation.is_safe is True
    assert result.validated_sql.endswith(";")
    assert result.execution.status == "success"
    assert result.execution.row_count == 2
    assert result.to_dict()["data"] == [{"name": "Meera Iyer"}, {"name": "Kabir Khan"}]
    assert result.to_dict()["original_sql"] == result.generated_sql
    assert result.to_dict()["corrected_sql"] == []
    assert result.to_dict()["explanation"] == result.explanation
    assert result.to_dict()["final_answer"] == "Found 2 matching rows. First result: Meera Iyer."


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
    assert result.execution.row_count == 10
    assert result.to_dict()["data"][0] == {"name": "Aarav Sharma"}
    assert result.to_dict()["final_answer"] == "Found 10 matching rows. First result: Aarav Sharma."


def test_run_agent_pipeline_corrects_overly_exact_empty_results(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}")

    monkeypatch.setattr(
        "text_to_sql_agent.agent_workflow.generate_sql",
        lambda question, settings=None: """
        SELECT students.name
        FROM students
        JOIN enrollments ON enrollments.student_id = students.id
        JOIN courses ON courses.id = enrollments.course_id
        WHERE courses.title = 'Java course';
        """,
    )

    def fake_correct_sql(question: str, failed_sql: str, error: str, settings=None) -> str:
        assert "returned no rows" in error
        return """
        SELECT students.name
        FROM students
        JOIN enrollments ON enrollments.student_id = students.id
        JOIN courses ON courses.id = enrollments.course_id
        WHERE courses.title LIKE '%Java%';
        """

    monkeypatch.setattr("text_to_sql_agent.agent_workflow.correct_sql", fake_correct_sql)

    result = run_agent_pipeline("Show all students enrolled in Java course", settings=settings)

    assert result.retry_count == 0
    assert result.corrected_sql == []
    assert result.execution.status == "edge_case"
    assert result.execution.row_count == 2
    assert result.to_dict()["data"] == [
        {"name": "Kabir Khan", "title": "Java Masterclass", "status": "completed"},
        {"name": "Meera Iyer", "title": "Java Masterclass", "status": "active"},
    ]
    assert "Interpreted it as Java Masterclass" in result.to_dict()["final_answer"]


def test_run_agent_pipeline_explains_impossible_course_count_request(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}")

    monkeypatch.setattr(
        "text_to_sql_agent.agent_workflow.generate_sql",
        lambda question, settings=None: """
        SELECT students.name, COUNT(enrollments.id) AS course_count
        FROM students
        JOIN enrollments ON enrollments.student_id = students.id
        GROUP BY students.id, students.name
        HAVING COUNT(enrollments.id) > 12;
        """,
    )

    result = run_agent_pipeline("Which students are enrolled in more than 12 course?", settings=settings)

    assert result.execution.status == "edge_case"
    assert result.execution.row_count == 5
    assert "There are only 7 courses" in result.to_dict()["final_answer"]
    assert result.to_dict()["data"][0] == {"name": "Aarav Sharma", "course_count": 2}


def test_run_agent_pipeline_adds_limit_for_top_queries(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}")

    monkeypatch.setattr(
        "text_to_sql_agent.agent_workflow.generate_sql",
        lambda question, settings=None: "SELECT name FROM students ORDER BY name;",
    )

    result = run_agent_pipeline("Show top students by name", settings=settings)

    assert result.execution.sql == "SELECT name FROM students ORDER BY name LIMIT 10;"
    assert result.execution.row_count == 10


def test_run_agent_pipeline_applies_semantic_guardrail_before_execution(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}")

    monkeypatch.setattr(
        "text_to_sql_agent.agent_workflow.generate_sql",
        lambda question, settings=None: "SELECT name, email FROM students ORDER BY id;",
    )

    result = run_agent_pipeline("Show all students", settings=settings)

    assert result.execution.status == "edge_case"
    assert "avoided exposing student email" in result.final_answer
    assert "email" not in result.execution.data[0]


def test_prepare_sql_for_approval_does_not_execute_query(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}")

    monkeypatch.setattr(
        "text_to_sql_agent.agent_workflow.generate_sql",
        lambda question, settings=None: "SELECT name FROM students ORDER BY id;",
    )

    result = prepare_sql_for_approval("Show all student names", settings=settings)

    assert result.execution.status == "awaiting_approval"
    assert result.execution.row_count == 0
    assert result.execution.data == []
    assert result.execution.sql == "SELECT name FROM students ORDER BY id;"
    assert result.to_dict()["final_answer"] == "SQL is ready for human approval before execution."


def test_execute_approved_sql_runs_validated_query(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}")

    result = execute_approved_sql(
        "Show all student names",
        "SELECT name FROM students ORDER BY id;",
        settings=settings,
    )

    assert result.execution.status == "success"
    assert result.execution.row_count == 10
    assert result.execution.data[0] == {"name": "Aarav Sharma"}


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
    assert "SQL database returned an error" in result.to_dict()["final_answer"]


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


def test_explanation_and_final_answer_tools() -> None:
    explanation = create_sql_explanation_tool().invoke({"sql": "SELECT name FROM students;"})
    final_answer = create_final_answer_tool().invoke(
        {
            "result": {
                "question": "Show students",
                "sql": "SELECT name FROM students;",
                "data": [{"name": "Aarav Sharma"}],
                "row_count": 1,
                "status": "success",
            }
        }
    )

    assert explanation == "This query reads the column(s) name from the students table."
    assert final_answer == "Found 1 matching row. First result: Aarav Sharma."
