import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from text_to_sql_agent.cache import get_cached_text
from text_to_sql_agent.config import Settings, get_settings
from text_to_sql_agent.database import format_schema_for_prompt, get_connection


SCHEMA_RAG_VERSION = "2026-05-10"


@dataclass(frozen=True)
class BusinessRule:
    id: str
    title: str
    content: str
    keywords: tuple[str, ...]


BUSINESS_RULES: tuple[BusinessRule, ...] = (
    BusinessRule(
        id="course_title_matching",
        title="Course title matching",
        content=(
            "Course names live in courses.title. User phrases such as Java course, SQL course, "
            "or AI course may be partial names, so prefer courses.title LIKE '%term%' unless the exact title is known."
        ),
        keywords=("course", "courses", "title", "java", "python", "sql", "ai", "cloud", "web"),
    ),
    BusinessRule(
        id="student_course_enrollment",
        title="Student enrollments",
        content=(
            "A student is enrolled in a course through enrollments.student_id and enrollments.course_id. "
            "Questions about students in courses require joining students -> enrollments -> courses."
        ),
        keywords=("student", "students", "enrolled", "enrollment", "course", "courses"),
    ),
    BusinessRule(
        id="multi_course_counts",
        title="Counting courses per student",
        content=(
            "For questions like students enrolled in more than N courses, group by students.id and students.name, "
            "count enrollments.course_id, and compare the requested N against the total number of rows in courses."
        ),
        keywords=("more", "than", "count", "counts", "many", "multiple", "course", "courses", "enrolled"),
    ),
    BusinessRule(
        id="payments_pending_amount",
        title="Pending amount",
        content=(
            "Pending amount means courses.fee - payments.amount for the payment linked to an enrollment. "
            "Partial payments are represented by payments.status = 'partial'."
        ),
        keywords=("payment", "payments", "paid", "partial", "pending", "amount", "fee", "balance"),
    ),
    BusinessRule(
        id="course_revenue",
        title="Course revenue",
        content=(
            "Course or category revenue should use SUM(payments.amount) joined through payments.enrollment_id "
            "to enrollments.id and enrollments.course_id to courses.id."
        ),
        keywords=("revenue", "earned", "money", "income", "category", "categories", "course", "payments"),
    ),
    BusinessRule(
        id="status_domains",
        title="Status columns",
        content=(
            "Enrollment status values are active, completed, cancelled, and partial. "
            "Payment status values are paid, partial, and refunded. Choose the status column that matches the question."
        ),
        keywords=("status", "active", "completed", "cancelled", "paid", "partial", "refunded"),
    ),
    BusinessRule(
        id="date_filters",
        title="Date filters",
        content=(
            "Date columns use ISO text dates: students.joined_on, enrollments.enrolled_on, and payments.paid_on. "
            "Use BETWEEN or >= and <= for date ranges."
        ),
        keywords=("date", "dates", "joined", "enrolled", "paid", "before", "after", "between", "month", "year"),
    ),
    BusinessRule(
        id="top_bottom_queries",
        title="Top and bottom queries",
        content=(
            "Top, highest, lowest, and bottom questions need ORDER BY plus LIMIT. "
            "If the user does not specify a number, return the top 10."
        ),
        keywords=("top", "highest", "lowest", "bottom", "best", "most", "least", "rank"),
    ),
    BusinessRule(
        id="saas_subscription_revenue",
        title="SaaS subscription revenue",
        content=(
            "SaaS revenue questions should join organizations -> subscriptions -> plans. "
            "MRR is plans.monthly_price. Annual recurring revenue can be approximated as plans.monthly_price * 12."
        ),
        keywords=("saas", "subscription", "subscriptions", "mrr", "arr", "revenue", "plan", "plans", "customer"),
    ),
    BusinessRule(
        id="saas_invoice_balance",
        title="Invoice balance",
        content=(
            "Open, partial, and overdue invoice balance means invoices.amount_due - invoices.amount_paid. "
            "Join invoices -> subscriptions -> organizations for customer names."
        ),
        keywords=("invoice", "invoices", "balance", "overdue", "due", "paid", "partial", "open", "billing"),
    ),
    BusinessRule(
        id="saas_usage_analysis",
        title="Usage analytics",
        content=(
            "Usage questions use usage_events.event_count grouped by organizations, app_users, event_type, or occurred_on. "
            "Join usage_events.organization_id to organizations.id for account-level reporting."
        ),
        keywords=("usage", "events", "event", "api", "agent", "dashboard", "export", "active", "activity"),
    ),
    BusinessRule(
        id="saas_support_health",
        title="Support and account health",
        content=(
            "Support-health questions use support_tickets joined to organizations. "
            "Open urgent or high-priority tickets can indicate churn risk."
        ),
        keywords=("support", "ticket", "tickets", "priority", "urgent", "open", "resolved", "churn", "risk"),
    ),
    BusinessRule(
        id="saas_feature_adoption",
        title="Feature adoption",
        content=(
            "Feature adoption questions join feature_adoption -> feature_flags -> organizations and use active_users "
            "or usage_count for adoption strength."
        ),
        keywords=("feature", "features", "adoption", "flag", "flags", "enabled", "usage", "users"),
    ),
)


def build_retrieved_schema_context(
    question: str,
    database_path: Path | None = None,
    limit: int = 5,
    settings: Settings | None = None,
) -> str:
    active_settings = settings or get_settings()
    path = database_path or active_settings.database_path
    payload = {
        "question": question,
        "limit": limit,
        "database": _database_fingerprint(path),
        "rag_version": SCHEMA_RAG_VERSION,
        "business_rules": [rule.id for rule in BUSINESS_RULES],
    }
    return get_cached_text(
        "schema-context",
        payload,
        lambda: _build_retrieved_schema_context(question, path, limit),
        settings=active_settings,
    )


def _build_retrieved_schema_context(question: str, database_path: Path | None = None, limit: int = 5) -> str:
    schema = format_schema_for_prompt(database_path)
    rules = retrieve_business_rules(question, limit=limit)
    values = retrieve_relevant_values(question, database_path)

    sections = ["Schema:", schema]
    if rules:
        sections.extend(["", "Retrieved business rules:"])
        sections.extend(f"- {rule.title}: {rule.content}" for rule in rules)
    if values:
        sections.extend(["", "Retrieved database values:"])
        sections.extend(f"- {line}" for line in values)
    return "\n".join(sections)


def retrieve_business_rules(question: str, limit: int = 5) -> list[BusinessRule]:
    tokens = _tokenize(question)
    scored_rules = [
        (_score_rule(tokens, rule), index, rule)
        for index, rule in enumerate(BUSINESS_RULES)
    ]
    return [
        rule
        for score, _, rule in sorted(scored_rules, key=lambda item: (-item[0], item[1]))
        if score > 0
    ][:limit]


def retrieve_relevant_values(question: str, database_path: Path | None = None) -> list[str]:
    tokens = _tokenize(question)
    values: list[str] = []

    if tokens & {"course", "courses", "java", "python", "sql", "ai", "cloud", "web", "analytics"}:
        values.append("Known course titles: " + ", ".join(_distinct_values("courses", "title", database_path)))
        values.append("Known course categories: " + ", ".join(_distinct_values("courses", "category", database_path)))
    if tokens & {"city", "cities", "from", "location", "delhi", "chennai", "mumbai", "pune"}:
        values.append("Known student cities: " + ", ".join(_distinct_values("students", "city", database_path)))
    if tokens & {"status", "active", "completed", "cancelled", "paid", "partial", "refunded"}:
        values.append("Known enrollment statuses: " + ", ".join(_distinct_values("enrollments", "status", database_path)))
        values.append("Known payment statuses: " + ", ".join(_distinct_values("payments", "status", database_path)))
    if tokens & {"more", "than", "course", "courses", "enrolled"}:
        total_courses = _count_rows("courses", database_path)
        values.append(f"Total courses available: {total_courses}")
    if tokens & {"organization", "organizations", "customer", "customers", "account", "accounts", "saas"}:
        values.append("Known organization lifecycle stages: " + ", ".join(_distinct_values("organizations", "lifecycle_stage", database_path)))
        values.append("Known organization regions: " + ", ".join(_distinct_values("organizations", "region", database_path)))
    if tokens & {"subscription", "subscriptions", "plan", "plans", "mrr", "arr", "revenue"}:
        values.append("Known plan names: " + ", ".join(_distinct_values("plans", "name", database_path)))
        values.append("Known subscription statuses: " + ", ".join(_distinct_values("subscriptions", "status", database_path)))
    if tokens & {"invoice", "invoices", "overdue", "billing", "balance", "due"}:
        values.append("Known invoice statuses: " + ", ".join(_distinct_values("invoices", "status", database_path)))
    if tokens & {"usage", "event", "events", "api", "agent", "dashboard", "export"}:
        values.append("Known usage event types: " + ", ".join(_distinct_values("usage_events", "event_type", database_path)))
    if tokens & {"ticket", "tickets", "support", "priority", "urgent"}:
        values.append("Known support priorities: " + ", ".join(_distinct_values("support_tickets", "priority", database_path)))
        values.append("Known support statuses: " + ", ".join(_distinct_values("support_tickets", "status", database_path)))
    if tokens & {"feature", "features", "adoption", "flag", "flags"}:
        values.append("Known feature flags: " + ", ".join(_distinct_values("feature_flags", "key", database_path)))

    return values


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9]+", text)}


def _score_rule(tokens: set[str], rule: BusinessRule) -> int:
    return len(tokens.intersection(rule.keywords))


def _distinct_values(table: str, column: str, database_path: Path | None) -> Sequence[str]:
    try:
        with get_connection(database_path) as connection:
            rows = connection.execute(
                f"SELECT DISTINCT {column} AS value FROM {table} ORDER BY {column};"
            ).fetchall()
    except sqlite3.Error:
        return ()
    return tuple(str(row["value"]) for row in rows)


def _count_rows(table: str, database_path: Path | None) -> int:
    try:
        with get_connection(database_path) as connection:
            row = connection.execute(f"SELECT COUNT(*) AS count FROM {table};").fetchone()
    except sqlite3.Error:
        return 0
    return int(row["count"] if row else 0)


def _database_fingerprint(database_path: Path | None) -> dict[str, object]:
    if database_path is None:
        return {"path": None, "mtime_ns": None, "size": None}

    path = database_path.resolve()
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "mtime_ns": None, "size": None}
    return {"path": str(path), "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
