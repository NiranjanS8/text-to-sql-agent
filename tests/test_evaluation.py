from pathlib import Path

from text_to_sql_agent.agent_workflow import AgentWorkflowResult
from text_to_sql_agent.config import Settings
from text_to_sql_agent.database import initialize_database
from text_to_sql_agent.evaluation import BenchmarkCase, DEFAULT_BENCHMARK_CASES, evaluate_agent
from text_to_sql_agent.query_executor import QueryExecutionResult
from text_to_sql_agent.sql_validator import validate_sql


def test_evaluate_agent_scores_successful_cases(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}")

    cases = (
        BenchmarkCase(
            id="java_students",
            question="Show Java students",
            expected_tables=("students", "courses", "enrollments"),
            expected_row_count=2,
            expected_answer_terms=("found",),
            expected_sql_terms=("java",),
        ),
    )

    def fake_pipeline(question: str) -> AgentWorkflowResult:
        sql = """
        SELECT students.name
        FROM students
        JOIN enrollments ON enrollments.student_id = students.id
        JOIN courses ON courses.id = enrollments.course_id
        WHERE courses.title LIKE '%Java%';
        """
        execution = QueryExecutionResult(
            question=question,
            sql=validate_sql(sql).sql,
            data=[{"name": "Meera Iyer"}, {"name": "Kabir Khan"}],
            row_count=2,
        )
        return AgentWorkflowResult(
            question=question,
            schema_context="students(...)\ncourses(...)\nenrollments(...)",
            generated_sql=sql,
            validated_sql=execution.sql,
            validation=validate_sql(sql),
            execution=execution,
            corrected_sql=[],
            retry_count=0,
            explanation="Reads Java students.",
            final_answer="Found 2 matching rows for: Show Java students",
        )

    summary = evaluate_agent(cases=cases, pipeline=fake_pipeline, settings=settings)

    assert summary.total_cases == 1
    assert summary.passed_cases == 1
    assert summary.pass_rate == 1.0
    assert summary.average_score == 1.0
    assert summary.sql_validity_rate == 1.0
    assert summary.table_match_rate == 1.0
    assert summary.row_count_match_rate == 1.0
    assert summary.cases[0].failures == []


def test_evaluate_agent_reports_failed_checks(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}")
    cases = (
        BenchmarkCase(
            id="bad_case",
            question="Show Java students",
            expected_tables=("students", "courses"),
            expected_row_count=2,
            expected_answer_terms=("java",),
            expected_sql_terms=("join",),
        ),
    )

    def fake_pipeline(question: str) -> AgentWorkflowResult:
        sql = "SELECT name FROM students;"
        execution = QueryExecutionResult(
            question=question,
            sql=validate_sql(sql).sql,
            data=[],
            row_count=0,
        )
        return AgentWorkflowResult(
            question=question,
            schema_context="students(...)",
            generated_sql=sql,
            validated_sql=execution.sql,
            validation=validate_sql(sql),
            execution=execution,
            corrected_sql=[],
            retry_count=0,
            explanation="Reads names.",
            final_answer="No matching rows were found.",
        )

    summary = evaluate_agent(cases=cases, pipeline=fake_pipeline, settings=settings)
    failure_names = set(summary.cases[0].failures)

    assert summary.passed_cases == 0
    assert summary.pass_rate == 0.0
    assert "tables_expected" in failure_names
    assert "row_count_expected" in failure_names
    assert "answer_terms_expected" in failure_names
    assert "sql_terms_expected" in failure_names
    assert "non_empty_result_expected" in failure_names


def test_default_benchmark_cases_cover_resume_metrics() -> None:
    case_ids = {case.id for case in DEFAULT_BENCHMARK_CASES}

    assert "java_students" in case_ids
    assert "category_revenue" in case_ids
    assert "impossible_course_threshold" in case_ids
    assert "saas_overdue_invoices" in case_ids
    assert "saas_feature_adoption" in case_ids
    assert all(case.expected_tables for case in DEFAULT_BENCHMARK_CASES)
