from pathlib import Path

from text_to_sql_agent.agent_workflow import (
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

