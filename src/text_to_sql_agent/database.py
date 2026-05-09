import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from text_to_sql_agent.config import get_settings


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

CREATE TABLE IF NOT EXISTS query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    generated_sql TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL
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


def get_schema(database_path: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    schema: dict[str, list[dict[str, Any]]] = {}
    with get_connection(database_path) as connection:
        for table in get_table_names(database_path):
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


def format_schema_for_prompt(database_path: Path | None = None) -> str:
    schema = get_schema(database_path)
    lines: list[str] = []
    for table, columns in schema.items():
        column_text = ", ".join(f"{column['name']} {column['type']}" for column in columns)
        lines.append(f"{table}({column_text})")
    return "\n".join(lines)
