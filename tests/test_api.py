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


def test_ask_endpoint_returns_validation_error_for_unsafe_generated_sql(monkeypatch) -> None:
    monkeypatch.setattr("text_to_sql_agent.agent_workflow.generate_sql", lambda question, settings=None: "DROP TABLE students;")

    response = client.post("/ask", json={"question": "Remove students"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "validation_error"
    assert payload["error"] == "Only SELECT queries are allowed."
