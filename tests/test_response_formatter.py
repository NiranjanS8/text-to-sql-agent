from text_to_sql_agent.query_executor import QueryExecutionResult
from text_to_sql_agent.response_formatter import build_final_answer, explain_sql


def test_explain_sql_describes_columns_tables_and_clauses() -> None:
    explanation = explain_sql(
        """
        SELECT students.name, courses.title
        FROM students
        JOIN enrollments ON enrollments.student_id = students.id
        JOIN courses ON courses.id = enrollments.course_id
        WHERE courses.title = 'Java Masterclass'
        ORDER BY students.name;
        """
    )

    assert "students.name, courses.title" in explanation
    assert "students, enrollments, and courses tables" in explanation
    assert "filters the rows" in explanation
    assert "sorts the output" in explanation


def test_build_final_answer_for_success_empty_and_error_states() -> None:
    success = QueryExecutionResult(
        question="Show students",
        sql="SELECT name FROM students;",
        data=[{"name": "Aarav Sharma"}, {"name": "Meera Iyer"}],
        row_count=2,
    )
    empty = QueryExecutionResult(question="Show Jaipur students", sql="SELECT * FROM students;", row_count=0)
    error = QueryExecutionResult(
        question="Show bad column",
        sql="SELECT missing FROM students;",
        status="sql_error",
        error="no such column: missing",
    )

    assert build_final_answer(success) == "Found 2 matching rows. First result: Aarav Sharma."
    assert build_final_answer(empty) == "No matching rows were found for: Show Jaipur students"
    assert build_final_answer(error) == (
        "I could not answer the question because SQLite returned an error: no such column: missing"
    )


def test_build_final_answer_for_approval_preview() -> None:
    result = QueryExecutionResult(
        question="Show students",
        sql="SELECT name FROM students;",
        status="awaiting_approval",
    )

    assert build_final_answer(result) == "SQL is ready for human approval before execution."


def test_build_final_answer_summarizes_pending_amounts() -> None:
    result = QueryExecutionResult(
        question="Show students with partial payments and pending amount",
        sql="SELECT ...",
        data=[
            {"name": "Ananya Rao", "pending_amount": 9000},
            {"name": "Vikram Singh", "pending_amount": 7000},
        ],
        row_count=2,
    )

    assert build_final_answer(result) == "Found 2 matching rows. Ananya Rao has the highest pending amount of 9000."


def test_build_final_answer_summarizes_invoice_balance() -> None:
    result = QueryExecutionResult(
        question="Which customers have overdue invoice balance?",
        sql="SELECT ...",
        data=[
            {"name": "Cobalt Logistics", "amount_due": 899, "amount_paid": 0},
            {"name": "Helio Health", "amount_due": 299, "amount_paid": 0},
        ],
        row_count=2,
    )

    assert build_final_answer(result) == "Found 2 matching rows. Cobalt Logistics has the highest invoice balance of 899.0."
