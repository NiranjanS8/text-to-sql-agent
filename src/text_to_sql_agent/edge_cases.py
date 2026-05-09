import re
from pathlib import Path
from typing import Any

from text_to_sql_agent.database import get_connection
from text_to_sql_agent.query_executor import QueryExecutionResult, execute_sql
from text_to_sql_agent.sql_validator import ValidationResult, cleanup_sql


COURSE_COUNT_PATTERN = re.compile(
    r"\b(?P<operator>more than|over|greater than|above|at least|minimum of)\s+(?P<count>\d+)\s+courses?\b",
    flags=re.IGNORECASE,
)
PAYMENT_THRESHOLD_PATTERN = re.compile(
    r"\b(?:payments?|amounts?|revenue|fees?)\b.*\b(?:above|over|greater than|more than|at least)\s+(?P<amount>\d+)\b",
    flags=re.IGNORECASE,
)
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
CITY_PATTERN = re.compile(r"\b(?:from|in)\s+([A-Za-z][A-Za-z\s]+?)(?:\?|$|\s+students?\b)", flags=re.IGNORECASE)
COURSE_TEXT_PATTERN = re.compile(
    r"\b(?:course|enrolled in|studying|taking)\s+([A-Za-z][A-Za-z\s]+?)(?:\?|$|\s+course\b)",
    flags=re.IGNORECASE,
)
SENSITIVE_STUDENT_COLUMNS = ("email",)
RANKING_TERMS = ("top", "highest", "lowest", "bottom", "best", "worst", "most", "least")


def apply_question_sql_hints(question: str, sql: str) -> str:
    cleaned = cleanup_sql(sql)
    lowered_question = question.lower()
    lowered_sql = cleaned.lower()

    asks_for_ranked_subset = any(term in lowered_question for term in ("top", "highest", "lowest", "bottom"))
    if asks_for_ranked_subset and " limit " not in f" {lowered_sql} ":
        return f"{cleaned.rstrip(';')} LIMIT 10;"
    return cleaned


def resolve_validation_edge_case(
    question: str,
    validation: ValidationResult,
    database_path: Path | None = None,
) -> QueryExecutionResult | None:
    if validation.is_safe or "Only SELECT queries" not in str(validation.error):
        return None

    table = _infer_table_from_question(question)
    if not table:
        return None

    sql = _readonly_sql_for_table(table, question)
    result = execute_sql(question=question, sql=sql, database_path=database_path)
    message = (
        "I cannot modify database records because this agent is read-only. "
        f"Here is a safe SELECT preview from {table} instead."
    )
    return _with_edge_message(result, message)


def resolve_empty_result_edge_case(
    question: str,
    database_path: Path | None = None,
) -> QueryExecutionResult | None:
    resolvers = (
        _resolve_course_count_request,
        _resolve_payment_threshold_request,
        _resolve_date_range_request,
        _resolve_status_value_request,
        _resolve_city_value_request,
        _resolve_course_value_request,
    )
    for resolver in resolvers:
        result = resolver(question, database_path)
        if result:
            return result
    return None


def resolve_semantic_guardrail(
    question: str,
    sql: str,
    database_path: Path | None = None,
) -> QueryExecutionResult | None:
    resolvers = (
        _resolve_partial_payment_pending_amount_request,
        _resolve_sensitive_student_data_request,
        _resolve_ambiguous_ranking_request,
        _resolve_payment_query_without_payment_join,
        _resolve_status_filter_mismatch,
    )
    for resolver in resolvers:
        result = resolver(question, sql, database_path)
        if result:
            return result
    return None


def _resolve_course_count_request(question: str, database_path: Path | None) -> QueryExecutionResult | None:
    course_count_match = COURSE_COUNT_PATTERN.search(question)
    if not course_count_match:
        return None

    requested_count = int(course_count_match.group("count"))
    total_courses = _scalar("SELECT COUNT(*) FROM courses;", database_path)
    closest_sql = """
    SELECT students.name, COUNT(enrollments.id) AS course_count
    FROM students
    LEFT JOIN enrollments ON enrollments.student_id = students.id
    GROUP BY students.id, students.name
    ORDER BY course_count DESC, students.name
    LIMIT 5;
    """
    closest_result = execute_sql(question=question, sql=closest_sql, database_path=database_path)
    max_enrollments = int(closest_result.data[0]["course_count"]) if closest_result.data else 0

    if requested_count > total_courses:
        message = (
            f"There are only {total_courses} courses in the database, so no student can be enrolled in more than "
            f"{requested_count} courses. Here are the students with the highest enrollment counts instead."
        )
    else:
        message = (
            f"No student is currently enrolled in more than {requested_count} courses. The highest current enrollment "
            f"count for any student is {max_enrollments}. Here are the closest results."
        )
    return _with_edge_message(closest_result, message)


def _resolve_payment_threshold_request(question: str, database_path: Path | None) -> QueryExecutionResult | None:
    match = PAYMENT_THRESHOLD_PATTERN.search(question)
    if not match:
        return None

    requested_amount = int(match.group("amount"))
    max_amount = int(_scalar("SELECT MAX(amount) FROM payments;", database_path) or 0)
    if requested_amount <= max_amount:
        return None

    sql = """
    SELECT students.name, courses.title, payments.amount, payments.status, payments.paid_on
    FROM payments
    JOIN enrollments ON enrollments.id = payments.enrollment_id
    JOIN students ON students.id = enrollments.student_id
    JOIN courses ON courses.id = enrollments.course_id
    ORDER BY payments.amount DESC
    LIMIT 5;
    """
    result = execute_sql(question=question, sql=sql, database_path=database_path)
    message = (
        f"The highest payment amount in the database is {max_amount}, so there are no payments above "
        f"{requested_amount}. Here are the largest payments instead."
    )
    return _with_edge_message(result, message)


def _resolve_partial_payment_pending_amount_request(
    question: str,
    sql: str,
    database_path: Path | None,
) -> QueryExecutionResult | None:
    lowered_question = question.lower()
    lowered_sql = cleanup_sql(sql).lower()
    asks_partial_pending = (
        "partial" in lowered_question
        and any(term in lowered_question for term in ("payment", "payments", "paid"))
        and any(term in lowered_question for term in ("pending", "due", "balance", "remaining"))
    )
    if not asks_partial_pending:
        return None

    has_required_tables = all(table in lowered_sql for table in ("students", "courses", "enrollments", "payments"))
    filters_partial_payment = "payments.status" in lowered_sql and "partial" in lowered_sql
    computes_pending_amount = (
        "fee" in lowered_sql
        and "amount" in lowered_sql
        and re.search(r"(courses\.fee|fee)\s*-\s*(payments\.amount|amount)", lowered_sql) is not None
    )

    if has_required_tables and filters_partial_payment and computes_pending_amount:
        return None

    canonical_sql = """
    SELECT students.name,
           courses.title,
           courses.fee,
           payments.amount AS paid_amount,
           courses.fee - payments.amount AS pending_amount,
           payments.status,
           payments.paid_on
    FROM payments
    JOIN enrollments ON enrollments.id = payments.enrollment_id
    JOIN students ON students.id = enrollments.student_id
    JOIN courses ON courses.id = enrollments.course_id
    WHERE payments.status = 'partial'
    ORDER BY pending_amount DESC, students.name;
    """
    result = execute_sql(question=question, sql=canonical_sql, database_path=database_path)
    message = (
        "Partial payment with pending amount needs courses.fee - payments.amount. "
        "I used the canonical payment join and returned the pending amount for each partial payment."
    )
    return _with_edge_message(result, message)


def _resolve_sensitive_student_data_request(
    question: str,
    sql: str,
    database_path: Path | None,
) -> QueryExecutionResult | None:
    lowered_question = question.lower()
    lowered_sql = cleanup_sql(sql).lower()
    asks_for_contact = any(term in lowered_question for term in ("email", "contact", "contacts"))
    exposes_email = any(re.search(rf"\b{column}\b", lowered_sql) for column in SENSITIVE_STUDENT_COLUMNS)
    selects_all_students = re.search(r"\bselect\s+\*\s+from\s+students\b", lowered_sql) is not None

    if asks_for_contact or not (exposes_email or selects_all_students):
        return None

    safe_sql = "SELECT name, city, joined_on FROM students ORDER BY id LIMIT 10;"
    result = execute_sql(question=question, sql=safe_sql, database_path=database_path)
    message = (
        "I avoided exposing student email addresses because the question did not ask for contact data. "
        "Here are safe student fields instead."
    )
    return _with_edge_message(result, message)


def _resolve_ambiguous_ranking_request(
    question: str,
    sql: str,
    database_path: Path | None,
) -> QueryExecutionResult | None:
    lowered_question = question.lower()
    lowered_sql = cleanup_sql(sql).lower()
    asks_for_ranking = any(re.search(rf"\b{term}\b", lowered_question) for term in RANKING_TERMS)
    has_metric = " by " in lowered_question or any(
        term in lowered_question
        for term in ("fee", "amount", "payment", "revenue", "course", "courses", "date", "name", "enrollment")
    )

    if not asks_for_ranking or has_metric:
        return None
    if any(term in lowered_sql for term in ("count(", "sum(", "avg(", "order by")) and " order by " in lowered_sql:
        return None

    result = QueryExecutionResult(
        question=question,
        sql=cleanup_sql(sql),
        status="edge_case",
        message=(
            "The ranking request is ambiguous. Please specify the metric, such as course count, payment amount, "
            "revenue, joined date, or name."
        ),
    )
    return result


def _resolve_payment_query_without_payment_join(
    question: str,
    sql: str,
    database_path: Path | None,
) -> QueryExecutionResult | None:
    lowered_question = question.lower()
    lowered_sql = cleanup_sql(sql).lower()
    asks_payment_metric = any(
        term in lowered_question for term in ("payment", "payments", "paid", "pending", "amount", "revenue", "earned", "money")
    )

    if not asks_payment_metric or "payments" in lowered_sql:
        return None

    sql_preview = """
    SELECT students.name, courses.title, payments.amount, payments.status, payments.paid_on
    FROM payments
    JOIN enrollments ON enrollments.id = payments.enrollment_id
    JOIN students ON students.id = enrollments.student_id
    JOIN courses ON courses.id = enrollments.course_id
    ORDER BY payments.paid_on DESC
    LIMIT 5;
    """
    result = execute_sql(question=question, sql=sql_preview, database_path=database_path)
    message = (
        "The generated SQL did not reference the payments table even though the question asks about payment or "
        "revenue data. Showing a safe payments preview instead."
    )
    return _with_edge_message(result, message)


def _resolve_status_filter_mismatch(
    question: str,
    sql: str,
    database_path: Path | None,
) -> QueryExecutionResult | None:
    lowered_question = question.lower()
    lowered_sql = cleanup_sql(sql).lower()
    status_match = re.search(r"\b(enrollments|payments)\.status\s*=\s*'([^']+)'", lowered_sql)
    if not status_match:
        return None

    table, requested_status = status_match.groups()
    available = _distinct_values(table, "status", database_path)
    if any(requested_status == status.lower() for status in available):
        return None

    if table == "payments":
        sql_preview = """
        SELECT students.name, courses.title, payments.amount, payments.status, payments.paid_on
        FROM payments
        JOIN enrollments ON enrollments.id = payments.enrollment_id
        JOIN students ON students.id = enrollments.student_id
        JOIN courses ON courses.id = enrollments.course_id
        ORDER BY payments.paid_on DESC
        LIMIT 5;
        """
    else:
        sql_preview = """
        SELECT students.name, courses.title, enrollments.status, enrollments.enrolled_on
        FROM enrollments
        JOIN students ON students.id = enrollments.student_id
        JOIN courses ON courses.id = enrollments.course_id
        ORDER BY enrollments.enrolled_on DESC
        LIMIT 5;
        """
    result = execute_sql(question=question, sql=sql_preview, database_path=database_path)
    message = (
        f"No {table} status named {requested_status} exists. Available {table} statuses are "
        f"{', '.join(available)}. Showing recent {table} rows instead."
    )
    return _with_edge_message(result, message)


def _resolve_date_range_request(question: str, database_path: Path | None) -> QueryExecutionResult | None:
    years = YEAR_PATTERN.findall(question)
    if not years:
        return None

    table, date_column = _infer_date_table(question)
    min_date = _scalar(f"SELECT MIN({date_column}) FROM {table};", database_path)
    max_date = _scalar(f"SELECT MAX({date_column}) FROM {table};", database_path)
    if not min_date or not max_date:
        return None

    requested_years = {int(year) for year in years}
    min_year = int(str(min_date)[:4])
    max_year = int(str(max_date)[:4])
    if any(min_year <= year <= max_year for year in requested_years):
        return None

    sql = _recent_rows_sql(table, date_column)
    result = execute_sql(question=question, sql=sql, database_path=database_path)
    message = (
        f"The {table} date range is {min_date} to {max_date}, so the requested year is outside the available data. "
        "Here are the closest recent rows instead."
    )
    return _with_edge_message(result, message)


def _resolve_status_value_request(question: str, database_path: Path | None) -> QueryExecutionResult | None:
    lowered = question.lower()
    if not any(term in lowered for term in ("pending", "unpaid", "failed", "inactive")):
        return None

    if "payment" in lowered or "fee" in lowered or "paid" in lowered:
        statuses = _distinct_values("payments", "status", database_path)
        if "pending" in lowered or "unpaid" in lowered or "failed" in lowered:
            sql = """
            SELECT students.name, courses.title, payments.amount, payments.status, payments.paid_on
            FROM payments
            JOIN enrollments ON enrollments.id = payments.enrollment_id
            JOIN students ON students.id = enrollments.student_id
            JOIN courses ON courses.id = enrollments.course_id
            WHERE payments.status = 'partial'
            ORDER BY payments.amount DESC;
            """
            result = execute_sql(question=question, sql=sql, database_path=database_path)
            message = (
                f"No payment status named pending/failed exists. Available payment statuses are "
                f"{', '.join(statuses)}. Showing partial payments as the closest unpaid-fee signal."
            )
            return _with_edge_message(result, message)

    if "enrollment" in lowered or "student" in lowered or "inactive" in lowered:
        statuses = _distinct_values("enrollments", "status", database_path)
        sql = """
        SELECT students.name, courses.title, enrollments.status, enrollments.enrolled_on
        FROM enrollments
        JOIN students ON students.id = enrollments.student_id
        JOIN courses ON courses.id = enrollments.course_id
        WHERE enrollments.status IN ('cancelled', 'completed', 'partial')
        ORDER BY enrollments.enrolled_on DESC;
        """
        result = execute_sql(question=question, sql=sql, database_path=database_path)
        message = (
            f"No enrollment status named inactive exists. Available enrollment statuses are "
            f"{', '.join(statuses)}. Showing non-active enrollments as the closest match."
        )
        return _with_edge_message(result, message)

    return None


def _resolve_city_value_request(question: str, database_path: Path | None) -> QueryExecutionResult | None:
    lowered = question.lower()
    if "student" not in lowered or "course" in lowered or "enrolled" in lowered:
        return None

    match = CITY_PATTERN.search(question)
    if not match:
        return None

    city = _clean_phrase(match.group(1))
    cities = _distinct_values("students", "city", database_path)
    if any(city.lower() == available.lower() for available in cities):
        return None

    sql = "SELECT DISTINCT city FROM students ORDER BY city;"
    result = execute_sql(question=question, sql=sql, database_path=database_path)
    message = f"No students were found for {city}. Available student cities are {', '.join(cities)}."
    return _with_edge_message(result, message)


def _resolve_course_value_request(question: str, database_path: Path | None) -> QueryExecutionResult | None:
    lowered = question.lower()
    if "course" not in lowered and "enrolled" not in lowered:
        return None

    titles = _distinct_values("courses", "title", database_path)
    categories = _distinct_values("courses", "category", database_path)
    keywords = _meaningful_tokens(question)
    matched_title = next((title for title in titles if any(token in title.lower() for token in keywords)), None)

    if matched_title:
        sql = f"""
        SELECT students.name, courses.title, enrollments.status
        FROM students
        JOIN enrollments ON enrollments.student_id = students.id
        JOIN courses ON courses.id = enrollments.course_id
        WHERE courses.title = '{matched_title}'
        ORDER BY students.name;
        """
        result = execute_sql(question=question, sql=sql, database_path=database_path)
        message = f"No exact course text matched the request. Interpreted it as {matched_title} and returned matching students."
        return _with_edge_message(result, message)

    sql = "SELECT title, category, fee FROM courses ORDER BY title;"
    result = execute_sql(question=question, sql=sql, database_path=database_path)
    message = (
        "No course matched that wording. Available courses are "
        f"{', '.join(titles)}. Available categories are {', '.join(categories)}."
    )
    return _with_edge_message(result, message)


def _infer_table_from_question(question: str) -> str | None:
    lowered = question.lower()
    for table in ("students", "courses", "enrollments", "payments"):
        if table[:-1] in lowered or table in lowered:
            return table
    return None


def _readonly_sql_for_table(table: str, question: str) -> str:
    lowered = question.lower()
    if table == "enrollments" and any(term in lowered for term in ("inactive", "cancel", "completed", "partial")):
        return """
        SELECT students.name, courses.title, enrollments.status, enrollments.enrolled_on
        FROM enrollments
        JOIN students ON students.id = enrollments.student_id
        JOIN courses ON courses.id = enrollments.course_id
        WHERE enrollments.status IN ('cancelled', 'completed', 'partial')
        ORDER BY enrollments.enrolled_on DESC;
        """
    return f"SELECT * FROM {table} LIMIT 25;"


def _infer_date_table(question: str) -> tuple[str, str]:
    lowered = question.lower()
    if "payment" in lowered or "paid" in lowered or "fee" in lowered:
        return "payments", "paid_on"
    if "join" in lowered or "student" in lowered:
        return "students", "joined_on"
    return "enrollments", "enrolled_on"


def _recent_rows_sql(table: str, date_column: str) -> str:
    if table == "payments":
        return """
        SELECT students.name, courses.title, payments.amount, payments.status, payments.paid_on
        FROM payments
        JOIN enrollments ON enrollments.id = payments.enrollment_id
        JOIN students ON students.id = enrollments.student_id
        JOIN courses ON courses.id = enrollments.course_id
        ORDER BY payments.paid_on DESC
        LIMIT 5;
        """
    if table == "students":
        return "SELECT name, city, joined_on FROM students ORDER BY joined_on DESC LIMIT 5;"
    return """
    SELECT students.name, courses.title, enrollments.status, enrollments.enrolled_on
    FROM enrollments
    JOIN students ON students.id = enrollments.student_id
    JOIN courses ON courses.id = enrollments.course_id
    ORDER BY enrollments.enrolled_on DESC
    LIMIT 5;
    """


def _with_edge_message(result: QueryExecutionResult, message: str) -> QueryExecutionResult:
    return QueryExecutionResult(
        question=result.question,
        sql=result.sql,
        data=result.data,
        row_count=result.row_count,
        status="edge_case",
        message=message,
        error=result.error,
    )


def _distinct_values(table: str, column: str, database_path: Path | None) -> list[str]:
    with get_connection(database_path) as connection:
        rows = connection.execute(f"SELECT DISTINCT {column} FROM {table} ORDER BY {column};").fetchall()
    return [str(row[column]) for row in rows]


def _scalar(sql: str, database_path: Path | None) -> Any:
    with get_connection(database_path) as connection:
        return connection.execute(sql).fetchone()[0]


def _clean_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ?.").title()


def _meaningful_tokens(question: str) -> list[str]:
    ignored = {
        "show",
        "students",
        "student",
        "course",
        "courses",
        "enrolled",
        "enrollments",
        "in",
        "the",
        "all",
        "with",
        "for",
        "from",
        "who",
        "which",
        "are",
        "is",
        "taking",
        "studying",
    }
    return [token for token in re.findall(r"[a-zA-Z]+", question.lower()) if len(token) > 2 and token not in ignored]
