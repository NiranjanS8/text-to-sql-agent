from pathlib import Path

from text_to_sql_agent.database import initialize_database
from text_to_sql_agent.schema_rag import (
    build_retrieved_schema_context,
    retrieve_business_rules,
    retrieve_relevant_values,
)


def test_retrieve_business_rules_prioritizes_payment_questions() -> None:
    rules = retrieve_business_rules("Show students with partial payments and pending amount")
    rule_ids = [rule.id for rule in rules]

    assert rule_ids[0] == "payments_pending_amount"
    assert "status_domains" in rule_ids


def test_retrieve_relevant_values_adds_database_grounding(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    values = retrieve_relevant_values("Show all students enrolled in Java course", database_path)

    assert any("Known course titles" in value and "Java Masterclass" in value for value in values)
    assert any("Total courses available: 7" in value for value in values)


def test_build_retrieved_schema_context_combines_schema_rules_and_values(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    context = build_retrieved_schema_context(
        "Which course categories have earned the most money?",
        database_path,
    )

    assert "Schema:" in context
    assert "courses(id INTEGER" in context
    assert "Retrieved business rules:" in context
    assert "Course revenue" in context
    assert "Retrieved database values:" in context
    assert "Known course categories" in context


def test_schema_rag_retrieves_saas_revenue_context(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    context = build_retrieved_schema_context(
        "Which SaaS customers have overdue invoice balance?",
        database_path,
    )

    assert "organizations(id INTEGER" in context
    assert "subscriptions(id INTEGER" in context
    assert "invoices(id INTEGER" in context
    assert "SaaS subscription revenue" in context
    assert "Invoice balance" in context
    assert "Known invoice statuses" in context


def test_schema_rag_retrieves_feature_adoption_context(tmp_path: Path) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)

    values = retrieve_relevant_values("Show feature adoption for AI SQL Copilot", database_path)

    assert any("Known feature flags" in value and "ai_sql_copilot" in value for value in values)
