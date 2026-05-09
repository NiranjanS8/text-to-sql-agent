import argparse
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from text_to_sql_agent.agent_workflow import AgentWorkflowResult, run_agent_pipeline
from text_to_sql_agent.config import Settings, get_settings
from text_to_sql_agent.database import initialize_database
from text_to_sql_agent.sql_validator import validate_sql


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    question: str
    expected_tables: tuple[str, ...]
    expected_statuses: tuple[str, ...] = ("success", "edge_case")
    expected_row_count: int | None = None
    minimum_row_count: int | None = None
    expected_answer_terms: tuple[str, ...] = ()
    expected_sql_terms: tuple[str, ...] = ()
    requires_non_empty_result: bool = True


@dataclass(frozen=True)
class CaseEvaluation:
    id: str
    question: str
    status: str
    passed: bool
    score: float
    latency_ms: float
    retry_count: int
    row_count: int
    generated_sql: str
    final_sql: str
    final_answer: str
    checks: dict[str, bool]
    failures: list[str]


@dataclass(frozen=True)
class EvaluationSummary:
    total_cases: int
    passed_cases: int
    pass_rate: float
    average_score: float
    average_latency_ms: float
    sql_validity_rate: float
    execution_success_rate: float
    table_match_rate: float
    row_count_match_rate: float
    answer_term_match_rate: float
    average_retry_count: float
    cases: list[CaseEvaluation]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["cases"] = [asdict(case) for case in self.cases]
        return payload


DEFAULT_BENCHMARK_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        id="java_students",
        question="Show all students enrolled in Java course",
        expected_tables=("students", "courses", "enrollments"),
        expected_row_count=2,
        expected_answer_terms=("java",),
        expected_sql_terms=("students", "courses", "enrollments"),
    ),
    BenchmarkCase(
        id="multi_course_students",
        question="Which students are enrolled in more than one course?",
        expected_tables=("students", "enrollments"),
        minimum_row_count=1,
        expected_sql_terms=("count", "group by", "having"),
    ),
    BenchmarkCase(
        id="category_revenue",
        question="Which course categories have earned the most money?",
        expected_tables=("courses", "enrollments", "payments"),
        minimum_row_count=1,
        expected_sql_terms=("sum", "group by"),
    ),
    BenchmarkCase(
        id="partial_payments",
        question="Show students with partial payments and pending amount",
        expected_tables=("students", "courses", "enrollments", "payments"),
        minimum_row_count=1,
        expected_answer_terms=("matching",),
        expected_sql_terms=("partial",),
    ),
    BenchmarkCase(
        id="impossible_course_threshold",
        question="Which students are enrolled in more than 12 course?",
        expected_tables=("students", "enrollments"),
        expected_statuses=("edge_case",),
        minimum_row_count=1,
        expected_answer_terms=("only", "courses"),
    ),
    BenchmarkCase(
        id="top_students_limit",
        question="Show top students by name",
        expected_tables=("students",),
        expected_row_count=10,
        expected_sql_terms=("limit",),
    ),
    BenchmarkCase(
        id="saas_overdue_invoices",
        question="Which SaaS customers have overdue invoice balance?",
        expected_tables=("organizations", "subscriptions", "invoices"),
        minimum_row_count=1,
        expected_sql_terms=("amount_due", "amount_paid"),
    ),
    BenchmarkCase(
        id="saas_feature_adoption",
        question="Which organizations have the highest AI SQL Copilot adoption?",
        expected_tables=("organizations", "feature_adoption", "feature_flags"),
        minimum_row_count=1,
        expected_sql_terms=("usage_count", "active_users"),
    ),
)


PipelineCallable = Callable[[str], AgentWorkflowResult]


def evaluate_agent(
    cases: Sequence[BenchmarkCase] = DEFAULT_BENCHMARK_CASES,
    pipeline: PipelineCallable | None = None,
    settings: Settings | None = None,
) -> EvaluationSummary:
    active_settings = settings or get_settings()
    initialize_database(active_settings.database_path)

    runner = pipeline or (lambda question: run_agent_pipeline(question, settings=active_settings))
    case_results = [_evaluate_case(case, runner) for case in cases]
    return _summarize(case_results)


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="Run the Text-to-SQL agent evaluation benchmark.")
    parser.add_argument("--output", type=Path, help="Optional path to write the JSON evaluation report.")
    parser.add_argument("--pretty", action="store_true", help="Print indented JSON to stdout.")
    args = parser.parse_args()

    summary = evaluate_agent()
    payload = summary.to_dict()
    text = json.dumps(payload, indent=2 if args.pretty else None)
    print(text)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _evaluate_case(case: BenchmarkCase, pipeline: PipelineCallable) -> CaseEvaluation:
    started_at = time.perf_counter()
    workflow = pipeline(case.question)
    latency_ms = (time.perf_counter() - started_at) * 1000

    final_sql = workflow.execution.sql
    final_answer = workflow.final_answer
    row_count = workflow.execution.row_count
    checks = {
        "sql_valid": validate_sql(final_sql).is_safe,
        "status_expected": workflow.execution.status in case.expected_statuses,
        "tables_expected": _contains_expected_tables(final_sql, case.expected_tables),
        "row_count_expected": _row_count_matches(row_count, case),
        "answer_terms_expected": _contains_all_terms(final_answer, case.expected_answer_terms),
        "sql_terms_expected": _contains_all_terms(final_sql, case.expected_sql_terms),
        "non_empty_result_expected": (row_count > 0) if case.requires_non_empty_result else True,
    }
    failures = [name for name, passed in checks.items() if not passed]
    score = sum(1 for passed in checks.values() if passed) / len(checks)

    return CaseEvaluation(
        id=case.id,
        question=case.question,
        status=workflow.execution.status,
        passed=not failures,
        score=round(score, 4),
        latency_ms=round(latency_ms, 2),
        retry_count=workflow.retry_count,
        row_count=row_count,
        generated_sql=workflow.generated_sql,
        final_sql=final_sql,
        final_answer=final_answer,
        checks=checks,
        failures=failures,
    )


def _summarize(cases: list[CaseEvaluation]) -> EvaluationSummary:
    total = len(cases)
    if total == 0:
        return EvaluationSummary(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, [])

    return EvaluationSummary(
        total_cases=total,
        passed_cases=sum(1 for case in cases if case.passed),
        pass_rate=_rate(case.passed for case in cases),
        average_score=round(mean(case.score for case in cases), 4),
        average_latency_ms=round(mean(case.latency_ms for case in cases), 2),
        sql_validity_rate=_rate(case.checks["sql_valid"] for case in cases),
        execution_success_rate=_rate(case.checks["status_expected"] for case in cases),
        table_match_rate=_rate(case.checks["tables_expected"] for case in cases),
        row_count_match_rate=_rate(case.checks["row_count_expected"] for case in cases),
        answer_term_match_rate=_rate(case.checks["answer_terms_expected"] for case in cases),
        average_retry_count=round(mean(case.retry_count for case in cases), 2),
        cases=cases,
    )


def _contains_expected_tables(sql: str, expected_tables: Sequence[str]) -> bool:
    referenced_tables = {
        table.lower()
        for table in re.findall(r"\b(?:FROM|JOIN)\b\s+([A-Za-z_][\w.]*)", sql, flags=re.IGNORECASE)
    }
    return all(table.lower() in referenced_tables for table in expected_tables)


def _contains_all_terms(text: str, terms: Sequence[str]) -> bool:
    normalized = text.lower()
    return all(term.lower() in normalized for term in terms)


def _row_count_matches(row_count: int, case: BenchmarkCase) -> bool:
    if case.expected_row_count is not None:
        return row_count == case.expected_row_count
    if case.minimum_row_count is not None:
        return row_count >= case.minimum_row_count
    return True


def _rate(values: Sequence[bool] | Any) -> float:
    materialized = list(values)
    if not materialized:
        return 0.0
    return round(sum(1 for value in materialized if value) / len(materialized), 4)


if __name__ == "__main__":
    run_cli()
