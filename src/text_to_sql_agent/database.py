import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from text_to_sql_agent.config import get_settings


INTERNAL_TABLES = {"query_history", "sql_approvals"}


SAMPLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    city TEXT NOT NULL,
    joined_on TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    fee INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,
    enrolled_on TEXT NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (course_id) REFERENCES courses(id)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enrollment_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    paid_on TEXT NOT NULL,
    method TEXT NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (enrollment_id) REFERENCES enrollments(id)
);

CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    industry TEXT NOT NULL,
    region TEXT NOT NULL,
    employee_count INTEGER NOT NULL,
    created_on TEXT NOT NULL,
    lifecycle_stage TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    created_on TEXT NOT NULL,
    last_active_on TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    tier TEXT NOT NULL,
    monthly_price INTEGER NOT NULL,
    included_seats INTEGER NOT NULL,
    included_events INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    plan_id INTEGER NOT NULL,
    started_on TEXT NOT NULL,
    renewal_on TEXT NOT NULL,
    status TEXT NOT NULL,
    billing_interval TEXT NOT NULL,
    seat_count INTEGER NOT NULL,
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (plan_id) REFERENCES plans(id)
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL,
    invoice_month TEXT NOT NULL,
    amount_due INTEGER NOT NULL,
    amount_paid INTEGER NOT NULL,
    status TEXT NOT NULL,
    due_on TEXT NOT NULL,
    paid_on TEXT,
    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id)
);

CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    user_id INTEGER,
    event_type TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    occurred_on TEXT NOT NULL,
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (user_id) REFERENCES app_users(id)
);

CREATE TABLE IF NOT EXISTS support_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    opened_by_user_id INTEGER,
    subject TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL,
    category TEXT NOT NULL,
    opened_on TEXT NOT NULL,
    resolved_on TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (opened_by_user_id) REFERENCES app_users(id)
);

CREATE TABLE IF NOT EXISTS feature_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    release_stage TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feature_adoption (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    feature_flag_id INTEGER NOT NULL,
    enabled_on TEXT NOT NULL,
    active_users INTEGER NOT NULL,
    usage_count INTEGER NOT NULL,
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (feature_flag_id) REFERENCES feature_flags(id)
);

CREATE TABLE IF NOT EXISTS query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    generated_sql TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sql_approvals (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    sql TEXT NOT NULL,
    sql_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    approved_at TEXT
);
"""


SAMPLE_ROWS: dict[str, list[tuple[Any, ...]]] = {
    "students": [
        (1, "Aarav Sharma", "aarav@example.com", "Delhi", "2025-01-10"),
        (2, "Meera Iyer", "meera@example.com", "Chennai", "2025-02-03"),
        (3, "Kabir Khan", "kabir@example.com", "Mumbai", "2025-02-20"),
        (4, "Ananya Rao", "ananya@example.com", "Bengaluru", "2025-03-12"),
        (5, "Riya Patel", "riya@example.com", "Ahmedabad", "2025-04-01"),
        (6, "Dev Malhotra", "dev@example.com", "Pune", "2025-04-18"),
        (7, "Nisha Verma", "nisha@example.com", "Hyderabad", "2025-05-02"),
        (8, "Ishaan Gupta", "ishaan@example.com", "Kolkata", "2025-05-17"),
        (9, "Sara Thomas", "sara@example.com", "Kochi", "2025-06-01"),
        (10, "Vikram Singh", "vikram@example.com", "Jaipur", "2025-06-14"),
    ],
    "courses": [
        (1, "Python Basics", "Programming", 12000),
        (2, "Java Masterclass", "Programming", 15000),
        (3, "Data Analytics", "Data", 18000),
        (4, "Cloud Fundamentals", "Cloud", 16000),
        (5, "SQL for Analytics", "Data", 14000),
        (6, "AI Foundations", "Artificial Intelligence", 22000),
        (7, "Web Development", "Programming", 17000),
    ],
    "enrollments": [
        (1, 1, 1, "2025-01-15", "active"),
        (2, 2, 2, "2025-02-07", "active"),
        (3, 3, 2, "2025-02-25", "completed"),
        (4, 4, 3, "2025-03-15", "active"),
        (5, 5, 4, "2025-04-05", "cancelled"),
        (6, 1, 3, "2025-04-10", "active"),
        (7, 6, 5, "2025-04-22", "active"),
        (8, 7, 6, "2025-05-05", "active"),
        (9, 8, 7, "2025-05-20", "active"),
        (10, 9, 1, "2025-06-03", "completed"),
        (11, 10, 5, "2025-06-16", "active"),
        (12, 2, 6, "2025-06-20", "active"),
        (13, 4, 7, "2025-06-25", "partial"),
        (14, 8, 3, "2025-07-01", "active"),
    ],
    "payments": [
        (1, 1, 12000, "2025-01-15", "card", "paid"),
        (2, 2, 15000, "2025-02-07", "upi", "paid"),
        (3, 3, 15000, "2025-02-25", "bank_transfer", "paid"),
        (4, 4, 9000, "2025-03-16", "card", "partial"),
        (5, 5, 0, "2025-04-05", "none", "refunded"),
        (6, 6, 18000, "2025-04-10", "upi", "paid"),
        (7, 7, 14000, "2025-04-22", "upi", "paid"),
        (8, 8, 22000, "2025-05-05", "card", "paid"),
        (9, 9, 17000, "2025-05-20", "bank_transfer", "paid"),
        (10, 10, 12000, "2025-06-03", "card", "paid"),
        (11, 11, 7000, "2025-06-16", "upi", "partial"),
        (12, 12, 22000, "2025-06-20", "card", "paid"),
        (13, 13, 8500, "2025-06-25", "upi", "partial"),
        (14, 14, 18000, "2025-07-01", "bank_transfer", "paid"),
    ],
    "organizations": [
        (1, "Acme Analytics", "SaaS", "North America", 240, "2024-01-12", "customer"),
        (2, "Nimbus Retail", "Retail", "Europe", 620, "2024-02-18", "customer"),
        (3, "Helio Health", "Healthcare", "North America", 410, "2024-03-05", "trial"),
        (4, "FinEdge Labs", "Finance", "Asia Pacific", 180, "2024-04-22", "customer"),
        (5, "Cobalt Logistics", "Logistics", "Europe", 950, "2024-05-16", "churn_risk"),
        (6, "Vertex AI Studio", "Technology", "Asia Pacific", 120, "2024-06-09", "customer"),
        (7, "GreenGrid Energy", "Energy", "North America", 780, "2024-07-03", "customer"),
        (8, "BrightPath EDU", "Education", "India", 320, "2024-08-21", "trial"),
    ],
    "app_users": [
        (1, 1, "Maya Chen", "admin", "maya@acme.example", "active", "2024-01-15", "2025-07-01"),
        (2, 1, "Leo Grant", "analyst", "leo@acme.example", "active", "2024-02-02", "2025-06-29"),
        (3, 2, "Eva Muller", "admin", "eva@nimbus.example", "active", "2024-02-20", "2025-06-30"),
        (4, 3, "Noah Brooks", "owner", "noah@helio.example", "invited", "2024-03-08", None),
        (5, 4, "Aisha Khan", "admin", "aisha@finedge.example", "active", "2024-04-28", "2025-07-02"),
        (6, 5, "Oliver Reed", "manager", "oliver@cobalt.example", "inactive", "2024-05-19", "2025-05-11"),
        (7, 6, "Priya Nair", "owner", "priya@vertex.example", "active", "2024-06-12", "2025-07-03"),
        (8, 7, "Grace Miller", "admin", "grace@greengrid.example", "active", "2024-07-05", "2025-07-01"),
        (9, 8, "Rohan Mehta", "admin", "rohan@brightpath.example", "active", "2024-08-24", "2025-06-28"),
        (10, 2, "Jonas Weber", "analyst", "jonas@nimbus.example", "active", "2024-03-01", "2025-06-27"),
    ],
    "plans": [
        (1, "Starter", "self_serve", 99, 5, 50000),
        (2, "Growth", "self_serve", 299, 20, 250000),
        (3, "Business", "sales_assisted", 899, 75, 1000000),
        (4, "Enterprise", "enterprise", 2499, 250, 5000000),
    ],
    "subscriptions": [
        (1, 1, 3, "2024-01-20", "2025-01-20", "active", "annual", 60),
        (2, 2, 4, "2024-02-25", "2025-02-25", "active", "annual", 220),
        (3, 3, 2, "2024-03-10", "2024-04-10", "trialing", "monthly", 18),
        (4, 4, 3, "2024-05-01", "2025-05-01", "active", "annual", 55),
        (5, 5, 3, "2024-06-01", "2025-06-01", "past_due", "annual", 80),
        (6, 6, 2, "2024-06-20", "2025-06-20", "active", "monthly", 14),
        (7, 7, 4, "2024-07-10", "2025-07-10", "active", "annual", 260),
        (8, 8, 1, "2024-09-01", "2024-10-01", "trialing", "monthly", 6),
    ],
    "invoices": [
        (1, 1, "2025-05", 899, 899, "paid", "2025-05-05", "2025-05-03"),
        (2, 1, "2025-06", 899, 899, "paid", "2025-06-05", "2025-06-04"),
        (3, 2, "2025-06", 2499, 2499, "paid", "2025-06-08", "2025-06-07"),
        (4, 3, "2025-06", 299, 0, "open", "2025-06-15", None),
        (5, 4, "2025-06", 899, 899, "paid", "2025-06-10", "2025-06-09"),
        (6, 5, "2025-06", 899, 300, "partial", "2025-06-12", "2025-06-20"),
        (7, 6, "2025-06", 299, 299, "paid", "2025-06-22", "2025-06-21"),
        (8, 7, "2025-06", 2499, 2499, "paid", "2025-06-25", "2025-06-24"),
        (9, 8, "2025-06", 99, 0, "open", "2025-06-30", None),
        (10, 5, "2025-07", 899, 0, "overdue", "2025-07-12", None),
    ],
    "usage_events": [
        (1, 1, 1, "query_executed", 12400, "2025-06-28"),
        (2, 1, 2, "dashboard_viewed", 8200, "2025-06-28"),
        (3, 2, 3, "query_executed", 45200, "2025-06-29"),
        (4, 2, 10, "export_created", 6300, "2025-06-29"),
        (5, 4, 5, "api_call", 99000, "2025-06-30"),
        (6, 5, 6, "query_executed", 1800, "2025-06-30"),
        (7, 6, 7, "agent_run", 22000, "2025-07-01"),
        (8, 7, 8, "api_call", 155000, "2025-07-01"),
        (9, 8, 9, "dashboard_viewed", 900, "2025-07-02"),
        (10, 7, 8, "agent_run", 37000, "2025-07-02"),
    ],
    "support_tickets": [
        (1, 1, 1, "Slow dashboard loads", "medium", "resolved", "performance", "2025-06-01", "2025-06-03"),
        (2, 2, 3, "Need SSO setup", "high", "open", "security", "2025-06-12", None),
        (3, 3, 4, "Trial data import failed", "high", "open", "data_import", "2025-06-18", None),
        (4, 5, 6, "Billing discrepancy", "urgent", "open", "billing", "2025-06-21", None),
        (5, 6, 7, "Agent workflow question", "low", "resolved", "product", "2025-06-24", "2025-06-25"),
        (6, 7, 8, "API rate limit increase", "medium", "in_progress", "platform", "2025-06-27", None),
        (7, 8, 9, "Onboarding checklist", "low", "open", "onboarding", "2025-06-29", None),
    ],
    "feature_flags": [
        (1, "ai_sql_copilot", "AI SQL Copilot", "ai", "ga"),
        (2, "semantic_guardrails", "Semantic Guardrails", "safety", "beta"),
        (3, "usage_anomaly_alerts", "Usage Anomaly Alerts", "analytics", "beta"),
        (4, "saml_sso", "SAML SSO", "security", "ga"),
        (5, "workflow_automation", "Workflow Automation", "automation", "alpha"),
    ],
    "feature_adoption": [
        (1, 1, 1, "2025-05-01", 28, 3400),
        (2, 1, 2, "2025-05-15", 14, 900),
        (3, 2, 4, "2025-04-20", 120, 2100),
        (4, 4, 1, "2025-05-18", 33, 4800),
        (5, 5, 3, "2025-06-01", 8, 120),
        (6, 6, 5, "2025-06-10", 7, 340),
        (7, 7, 1, "2025-05-22", 96, 8800),
        (8, 7, 2, "2025-06-05", 44, 1500),
        (9, 8, 1, "2025-06-18", 5, 80),
    ],
}


@contextmanager
def get_connection(database_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = database_path or get_settings().database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    try:
        yield connection
    finally:
        connection.close()


def initialize_database(database_path: Path | None = None) -> None:
    with get_connection(database_path) as connection:
        connection.executescript(SAMPLE_SCHEMA)
        _seed_table(
            connection,
            "students",
            "INSERT OR IGNORE INTO students (id, name, email, city, joined_on) VALUES (?, ?, ?, ?, ?)",
        )
        _seed_table(
            connection,
            "courses",
            "INSERT OR IGNORE INTO courses (id, title, category, fee) VALUES (?, ?, ?, ?)",
        )
        _seed_table(
            connection,
            "enrollments",
            "INSERT OR IGNORE INTO enrollments (id, student_id, course_id, enrolled_on, status) VALUES (?, ?, ?, ?, ?)",
        )
        _seed_table(
            connection,
            "payments",
            "INSERT OR IGNORE INTO payments (id, enrollment_id, amount, paid_on, method, status) VALUES (?, ?, ?, ?, ?, ?)",
        )
        _seed_table(
            connection,
            "organizations",
            "INSERT OR IGNORE INTO organizations (id, name, industry, region, employee_count, created_on, lifecycle_stage) VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        _seed_table(
            connection,
            "app_users",
            "INSERT OR IGNORE INTO app_users (id, organization_id, name, role, email, status, created_on, last_active_on) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        )
        _seed_table(
            connection,
            "plans",
            "INSERT OR IGNORE INTO plans (id, name, tier, monthly_price, included_seats, included_events) VALUES (?, ?, ?, ?, ?, ?)",
        )
        _seed_table(
            connection,
            "subscriptions",
            "INSERT OR IGNORE INTO subscriptions (id, organization_id, plan_id, started_on, renewal_on, status, billing_interval, seat_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        )
        _seed_table(
            connection,
            "invoices",
            "INSERT OR IGNORE INTO invoices (id, subscription_id, invoice_month, amount_due, amount_paid, status, due_on, paid_on) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        )
        _seed_table(
            connection,
            "usage_events",
            "INSERT OR IGNORE INTO usage_events (id, organization_id, user_id, event_type, event_count, occurred_on) VALUES (?, ?, ?, ?, ?, ?)",
        )
        _seed_table(
            connection,
            "support_tickets",
            "INSERT OR IGNORE INTO support_tickets (id, organization_id, opened_by_user_id, subject, priority, status, category, opened_on, resolved_on) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        _seed_table(
            connection,
            "feature_flags",
            "INSERT OR IGNORE INTO feature_flags (id, key, name, category, release_stage) VALUES (?, ?, ?, ?, ?)",
        )
        _seed_table(
            connection,
            "feature_adoption",
            "INSERT OR IGNORE INTO feature_adoption (id, organization_id, feature_flag_id, enabled_on, active_users, usage_count) VALUES (?, ?, ?, ?, ?, ?)",
        )
        connection.commit()


def _seed_table(connection: sqlite3.Connection, table: str, sql: str) -> None:
    connection.executemany(sql, SAMPLE_ROWS[table])


def get_table_names(database_path: Path | None = None) -> list[str]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name;
            """
        ).fetchall()
    return [row["name"] for row in rows]


def get_schema(database_path: Path | None = None, include_internal: bool = False) -> dict[str, list[dict[str, Any]]]:
    schema: dict[str, list[dict[str, Any]]] = {}
    with get_connection(database_path) as connection:
        for table in get_table_names(database_path):
            if not include_internal and table in INTERNAL_TABLES:
                continue
            columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
            schema[table] = [
                {
                    "name": column["name"],
                    "type": column["type"],
                    "nullable": not bool(column["notnull"]),
                    "primary_key": bool(column["pk"]),
                }
                for column in columns
            ]
    return schema


def format_schema_for_prompt(database_path: Path | None = None, include_internal: bool = False) -> str:
    schema = get_schema(database_path, include_internal=include_internal)
    lines: list[str] = []
    for table, columns in schema.items():
        column_text = ", ".join(f"{column['name']} {column['type']}" for column in columns)
        lines.append(f"{table}({column_text})")
    return "\n".join(lines)
