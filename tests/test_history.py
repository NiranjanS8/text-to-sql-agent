from pathlib import Path

from text_to_sql_agent.agent_workflow import run_agent_pipeline
from text_to_sql_agent.config import Settings
from text_to_sql_agent.database import get_table_names, initialize_database
from text_to_sql_agent.history import list_query_history, save_query_history


def test_initialize_database_creates_query_history_table(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    assert "query_history" in get_table_names(database_path)


def test_save_and_list_query_history(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}")

    monkeypatch.setattr(
        "text_to_sql_agent.agent_workflow.generate_sql",
        lambda question, settings=None: "SELECT name FROM students ORDER BY id;",
    )

    workflow = run_agent_pipeline("Show student names", settings=settings)
    saved = save_query_history(workflow, database_path=database_path)
    records = list_query_history(database_path=database_path)

    assert saved.id == 1
    assert saved.question == "Show student names"
    assert saved.generated_sql == "SELECT name FROM students ORDER BY id;"
    assert saved.execution_status == "success"
    assert saved.error_message is None
    assert records == [saved]
