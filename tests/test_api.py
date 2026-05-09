from fastapi.testclient import TestClient

from text_to_sql_agent.main import RATE_LIMIT_MESSAGE
from text_to_sql_agent.main import app


client = TestClient(app)


def test_index_serves_demo_ui() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert '<div id="root">' in response.text
    assert "/static/react/assets/" in response.text


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
    assert payload["row_count"] == 10
    assert payload["data"][0] == {"name": "Aarav Sharma", "city": "Delhi"}
    assert payload["explanation"] == (
        "This query reads the column(s) name, city from the students table and sorts the output."
    )
    assert payload["final_answer"] == "Found 10 matching rows for: Show all students"


def test_ask_endpoint_can_prepare_sql_for_approval(monkeypatch) -> None:
    monkeypatch.setattr(
        "text_to_sql_agent.agent_workflow.generate_sql",
        lambda question, settings=None: "SELECT name FROM students ORDER BY id;",
    )

    response = client.post(
        "/ask",
        json={"question": "Show all student names", "require_approval": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "awaiting_approval"
    assert payload["row_count"] == 0
    assert payload["data"] == []
    assert payload["sql"] == "SELECT name FROM students ORDER BY id;"
    assert payload["final_answer"] == "SQL is ready for human approval before execution."


def test_approve_endpoint_executes_reviewed_sql() -> None:
    response = client.post(
        "/approve",
        json={"question": "Show all student names", "sql": "SELECT name FROM students ORDER BY id;"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["row_count"] == 10
    assert payload["data"][0] == {"name": "Aarav Sharma"}


def test_ask_endpoint_returns_validation_error_for_unsafe_generated_sql(monkeypatch) -> None:
    monkeypatch.setattr("text_to_sql_agent.agent_workflow.generate_sql", lambda question, settings=None: "DROP TABLE students;")

    response = client.post("/ask", json={"question": "Remove students"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "edge_case"
    assert "read-only" in payload["final_answer"]


def test_ask_endpoint_returns_helpful_edge_case_for_impossible_course_count(monkeypatch) -> None:
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

    response = client.post("/ask", json={"question": "Which students are enrolled in more than 12 course?"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "edge_case"
    assert "There are only 7 courses" in payload["final_answer"]
    assert payload["row_count"] == 5


def test_ask_endpoint_returns_json_for_llm_rate_limit(monkeypatch) -> None:
    def raise_rate_limit(question, settings=None):
        raise RuntimeError("429 Too Many Requests: rate limit exceeded")

    monkeypatch.setattr("text_to_sql_agent.main.run_agent_pipeline", raise_rate_limit)

    response = client.post("/ask", json={"question": "Show all students"})

    assert response.status_code == 429
    assert response.json() == {"detail": RATE_LIMIT_MESSAGE}


def test_mistral_health_reports_rate_limit(monkeypatch) -> None:
    def raise_rate_limit(settings):
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr("text_to_sql_agent.main.test_mistral_connection", raise_rate_limit)

    response = client.get("/mistral/health")

    assert response.status_code == 200
    assert response.json() == {"status": "rate_limited", "message": RATE_LIMIT_MESSAGE}
