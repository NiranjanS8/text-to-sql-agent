from pathlib import Path

from text_to_sql_agent.database import initialize_database
from text_to_sql_agent.edge_cases import (
    apply_question_sql_hints,
    resolve_empty_result_edge_case,
    resolve_semantic_guardrail,
    resolve_validation_edge_case,
)
from text_to_sql_agent.sql_validator import validate_sql


def test_resolve_course_count_edge_case_when_requested_count_exceeds_total_courses(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = resolve_empty_result_edge_case(
        "Which students are enrolled in more than 12 course?",
        database_path=database_path,
    )

    assert result is not None
    assert result.status == "edge_case"
    assert result.row_count == 5
    assert "There are only 7 courses" in str(result.message)
    assert "more than 12 courses" in str(result.message)
    assert result.data[0] == {"name": "Aarav Sharma", "course_count": 2}


def test_apply_question_sql_hints_adds_limit_for_top_queries() -> None:
    sql = apply_question_sql_hints(
        "Show top students by name",
        "SELECT name FROM students ORDER BY name;",
    )

    assert sql == "SELECT name FROM students ORDER BY name LIMIT 10;"


def test_resolve_unknown_city_returns_available_cities(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = resolve_empty_result_edge_case("Show students from Indore", database_path=database_path)

    assert result is not None
    assert result.status == "edge_case"
    assert "Available student cities" in str(result.message)
    assert {"city": "Delhi"} in result.data


def test_resolve_out_of_range_payment_date_returns_recent_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = resolve_empty_result_edge_case("Show payments in 2026", database_path=database_path)

    assert result is not None
    assert result.status == "edge_case"
    assert "date range is 2025-01-15 to 2025-07-01" in str(result.message)
    assert result.data[0]["paid_on"] == "2025-07-01"


def test_resolve_payment_threshold_returns_largest_payments(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = resolve_empty_result_edge_case("Show payments above 100000", database_path=database_path)

    assert result is not None
    assert result.status == "edge_case"
    assert "highest payment amount in the database is 22000" in str(result.message)
    assert result.data[0]["amount"] == 22000


def test_resolve_pending_payment_status_returns_partial_payments(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = resolve_empty_result_edge_case("Show pending payments", database_path=database_path)

    assert result is not None
    assert result.status == "edge_case"
    assert "Available payment statuses" in str(result.message)
    assert {row["status"] for row in result.data} == {"partial"}


def test_resolve_unknown_course_returns_available_courses(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = resolve_empty_result_edge_case("Show students enrolled in Rust course", database_path=database_path)

    assert result is not None
    assert result.status == "edge_case"
    assert "Available courses are" in str(result.message)
    assert {"title": "Java Masterclass", "category": "Programming", "fee": 15000} in result.data


def test_resolve_unsafe_write_request_returns_readonly_preview(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    validation = validate_sql("DELETE FROM enrollments WHERE status = 'cancelled';")

    result = resolve_validation_edge_case("Delete inactive enrollments", validation, database_path=database_path)

    assert result is not None
    assert result.status == "edge_case"
    assert "read-only" in str(result.message)
    assert result.data[0]["status"] in {"cancelled", "completed", "partial"}


def test_semantic_guardrail_redacts_unrequested_student_email(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = resolve_semantic_guardrail(
        "Show all students",
        "SELECT name, email FROM students ORDER BY id;",
        database_path=database_path,
    )

    assert result is not None
    assert result.status == "edge_case"
    assert "avoided exposing student email" in str(result.message)
    assert "email" not in result.data[0]
    assert result.data[0] == {"name": "Aarav Sharma", "city": "Delhi", "joined_on": "2025-01-10"}


def test_semantic_guardrail_allows_requested_student_email(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = resolve_semantic_guardrail(
        "Show student email addresses",
        "SELECT name, email FROM students ORDER BY id;",
        database_path=database_path,
    )

    assert result is None


def test_semantic_guardrail_blocks_ambiguous_ranking() -> None:
    result = resolve_semantic_guardrail(
        "Show top students",
        "SELECT name FROM students LIMIT 10;",
    )

    assert result is not None
    assert result.status == "edge_case"
    assert "Please specify the metric" in str(result.message)


def test_semantic_guardrail_catches_payment_query_without_payments_table(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = resolve_semantic_guardrail(
        "Show students with partial payments",
        "SELECT students.name FROM students ORDER BY students.name;",
        database_path=database_path,
    )

    assert result is not None
    assert result.status == "edge_case"
    assert "did not reference the payments table" in str(result.message)
    assert {"name": "Ishaan Gupta", "title": "Data Analytics", "amount": 18000, "status": "paid", "paid_on": "2025-07-01"} in result.data


def test_semantic_guardrail_canonicalizes_partial_payment_pending_amount(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = resolve_semantic_guardrail(
        "Show students with partial payments and pending amount",
        """
        SELECT students.name, payments.amount
        FROM students
        JOIN enrollments ON enrollments.student_id = students.id
        JOIN payments ON payments.enrollment_id = enrollments.id
        WHERE payments.status = 'partial';
        """,
        database_path=database_path,
    )

    assert result is not None
    assert result.status == "edge_case"
    assert "courses.fee - payments.amount" in str(result.message)
    assert result.data == [
        {
            "name": "Ananya Rao",
            "title": "Data Analytics",
            "fee": 18000,
            "paid_amount": 9000,
            "pending_amount": 9000,
            "status": "partial",
            "paid_on": "2025-03-16",
        },
        {
            "name": "Ananya Rao",
            "title": "Web Development",
            "fee": 17000,
            "paid_amount": 8500,
            "pending_amount": 8500,
            "status": "partial",
            "paid_on": "2025-06-25",
        },
        {
            "name": "Vikram Singh",
            "title": "SQL for Analytics",
            "fee": 14000,
            "paid_amount": 7000,
            "pending_amount": 7000,
            "status": "partial",
            "paid_on": "2025-06-16",
        },
    ]


def test_semantic_guardrail_allows_correct_partial_payment_pending_amount(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = resolve_semantic_guardrail(
        "Show students with partial payments and pending amount",
        """
        SELECT students.name, courses.title, courses.fee - payments.amount AS pending_amount
        FROM payments
        JOIN enrollments ON enrollments.id = payments.enrollment_id
        JOIN students ON students.id = enrollments.student_id
        JOIN courses ON courses.id = enrollments.course_id
        WHERE payments.status = 'partial';
        """,
        database_path=database_path,
    )

    assert result is None


def test_semantic_guardrail_catches_invalid_status_filter(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    result = resolve_semantic_guardrail(
        "Show failed payments",
        "SELECT amount FROM payments WHERE payments.status = 'failed';",
        database_path=database_path,
    )

    assert result is not None
    assert result.status == "edge_case"
    assert "Available payments statuses" in str(result.message)
