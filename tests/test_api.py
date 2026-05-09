from fastapi.testclient import TestClient

from text_to_sql_agent.main import app


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_schema_endpoint_returns_sample_tables() -> None:
    response = client.get("/schema")

    assert response.status_code == 200
    tables = response.json()["tables"]
    assert {"students", "courses", "enrollments", "payments"}.issubset(tables.keys())


def test_history_endpoint_returns_saved_queries(monkeypatch) -> None:
    monkeypatch.setattr(
        "text_to_sql_agent.agent_workflow.generate_sql",
        lambda question, settings=None: "SELECT name FROM students ORDER BY id;",
    )

    ask_response = client.post("/ask", json={"question": "Show student names for history"})
    history_response = client.get("/history?limit=1")

    assert ask_response.status_code == 200
    assert history_response.status_code == 200
    history = history_response.json()["history"]
    assert len(history) == 1
    assert history[0]["question"] == "Show student names for history"
    assert history[0]["generated_sql"] == "SELECT name FROM students ORDER BY id;"
    assert history[0]["execution_status"] == "success"
    assert history[0]["error_message"] is None


def test_ask_endpoint_generates_validates_and_executes_sql(monkeypatch) -> None:
    def fake_generate_sql(question: str, settings=None) -> str:
        assert question == "Show all students"
        return "SELECT name, city FROM students ORDER BY id;"

    monkeypatch.setattr("text_to_sql_agent.agent_workflow.generate_sql", fake_generate_sql)

    response = client.post("/ask", json={"question": "Show all students"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["question"] == "Show all students"
    assert payload["sql"] == "SELECT name, city FROM students ORDER BY id;"
    assert payload["status"] == "success"
    assert payload["row_count"] == 5
    assert payload["data"][0] == {"name": "Aarav Sharma", "city": "Delhi"}
    assert payload["explanation"] == (
        "This query reads the column(s) name, city from the students table and sorts the output."
    )
    assert payload["final_answer"] == "Found 5 matching rows for: Show all students"


def test_ask_endpoint_returns_validation_error_for_unsafe_generated_sql(monkeypatch) -> None:
    monkeypatch.setattr("text_to_sql_agent.agent_workflow.generate_sql", lambda question, settings=None: "DROP TABLE students;")

    response = client.post("/ask", json={"question": "Remove students"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "validation_error"
    assert payload["error"] == "Only SELECT queries are allowed."
