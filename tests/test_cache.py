from pathlib import Path

from text_to_sql_agent.cache import build_cache_key, get_cached_text, redis_health
from text_to_sql_agent.config import Settings
from text_to_sql_agent.database import initialize_database
from text_to_sql_agent.schema_rag import build_retrieved_schema_context
from text_to_sql_agent.semantic_cache import lookup_semantic_sql, store_semantic_sql
from text_to_sql_agent.sql_generator import correct_sql, generate_sql


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.ping_count = 0

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.ttls[key] = ttl

    def ping(self) -> bool:
        self.ping_count += 1
        return True


def test_get_cached_text_reads_and_writes_redis(monkeypatch) -> None:
    redis = FakeRedis()
    settings = Settings(REDIS_URL="redis://cache:6379/0", CACHE_TTL_SECONDS=30)
    calls = 0

    monkeypatch.setattr("text_to_sql_agent.cache.get_redis_client", lambda redis_url: redis)

    def factory() -> str:
        nonlocal calls
        calls += 1
        return "cached value"

    assert get_cached_text("unit", {"a": 1}, factory, settings=settings) == "cached value"
    assert get_cached_text("unit", {"a": 1}, factory, settings=settings) == "cached value"
    assert calls == 1
    assert redis.ttls[build_cache_key("unit", {"a": 1})] == 30


def test_get_cached_text_falls_back_when_redis_is_disabled() -> None:
    settings = Settings(REDIS_URL=None)

    assert get_cached_text("unit", {"a": 1}, lambda: "fresh", settings=settings) == "fresh"


def test_redis_health_reports_ok(monkeypatch) -> None:
    redis = FakeRedis()
    settings = Settings(REDIS_URL="redis://cache:6379/0")

    monkeypatch.setattr("text_to_sql_agent.cache.get_redis_client", lambda redis_url: redis)

    assert redis_health(settings) == {"status": "ok", "message": "Redis cache is reachable."}
    assert redis.ping_count == 1


def test_schema_context_uses_cache_when_redis_is_configured(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    redis = FakeRedis()
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}", REDIS_URL="redis://cache:6379/0")

    monkeypatch.setattr("text_to_sql_agent.schema_rag.get_settings", lambda: settings)
    monkeypatch.setattr("text_to_sql_agent.cache.get_redis_client", lambda redis_url: redis)

    first = build_retrieved_schema_context("Show Java course students", database_path)
    second = build_retrieved_schema_context("Show Java course students", database_path)

    assert first == second
    assert len(redis.values) == 1


def test_generate_sql_uses_redis_cache(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    redis = FakeRedis()
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}", REDIS_URL="redis://cache:6379/0")
    calls = 0

    monkeypatch.setattr("text_to_sql_agent.cache.get_redis_client", lambda redis_url: redis)

    def fake_generate_uncached(question: str, schema: str, settings: Settings) -> str:
        nonlocal calls
        calls += 1
        return "SELECT name FROM students ORDER BY id;"

    monkeypatch.setattr("text_to_sql_agent.sql_generator._generate_sql_uncached", fake_generate_uncached)

    assert generate_sql("Show all student names", settings=settings) == "SELECT name FROM students ORDER BY id;"
    assert generate_sql("Show all student names", settings=settings) == "SELECT name FROM students ORDER BY id;"
    assert calls == 1


def test_correct_sql_uses_redis_cache(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    redis = FakeRedis()
    settings = Settings(DATABASE_URL=f"sqlite:///{database_path}", REDIS_URL="redis://cache:6379/0")
    calls = 0

    monkeypatch.setattr("text_to_sql_agent.cache.get_redis_client", lambda redis_url: redis)

    def fake_correct_uncached(question: str, failed_sql: str, error: str, schema: str, settings: Settings) -> str:
        nonlocal calls
        calls += 1
        return "SELECT name FROM students ORDER BY id;"

    monkeypatch.setattr("text_to_sql_agent.sql_generator._correct_sql_uncached", fake_correct_uncached)

    assert correct_sql("Show names", "SELECT missing FROM students;", "no such column", settings=settings) == (
        "SELECT name FROM students ORDER BY id;"
    )
    assert correct_sql("Show names", "SELECT missing FROM students;", "no such column", settings=settings) == (
        "SELECT name FROM students ORDER BY id;"
    )
    assert calls == 1


def test_semantic_cache_reuses_similar_question(monkeypatch) -> None:
    redis = FakeRedis()
    settings = Settings(
        REDIS_URL="redis://cache:6379/0",
        ENABLE_SEMANTIC_CACHE=True,
        SEMANTIC_CACHE_THRESHOLD=0.9,
    )
    namespace = {"schema": "invoices(...)", "model": "test-model", "prompt_version": "test"}

    monkeypatch.setattr("text_to_sql_agent.cache.get_redis_client", lambda redis_url: redis)

    store_semantic_sql(
        "Which customers have overdue invoice balance?",
        "SELECT name FROM organizations;",
        namespace,
        settings,
    )

    assert lookup_semantic_sql("Show overdue invoice balances by customer", namespace, settings) == (
        "SELECT name FROM organizations;"
    )


def test_semantic_cache_respects_threshold(monkeypatch) -> None:
    redis = FakeRedis()
    settings = Settings(
        REDIS_URL="redis://cache:6379/0",
        ENABLE_SEMANTIC_CACHE=True,
        SEMANTIC_CACHE_THRESHOLD=0.99,
    )
    namespace = {"schema": "invoices(...)", "model": "test-model", "prompt_version": "test"}

    monkeypatch.setattr("text_to_sql_agent.cache.get_redis_client", lambda redis_url: redis)

    store_semantic_sql(
        "Which customers have overdue invoice balance?",
        "SELECT name FROM organizations;",
        namespace,
        settings,
    )

    assert lookup_semantic_sql("List support ticket priorities", namespace, settings) is None


def test_generate_sql_uses_semantic_cache_for_similar_questions(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sample.db"
    initialize_database(database_path)
    redis = FakeRedis()
    settings = Settings(
        DATABASE_URL=f"sqlite:///{database_path}",
        REDIS_URL="redis://cache:6379/0",
        ENABLE_SEMANTIC_CACHE=True,
        SEMANTIC_CACHE_THRESHOLD=0.9,
    )
    calls = 0

    monkeypatch.setattr("text_to_sql_agent.cache.get_redis_client", lambda redis_url: redis)

    def fake_generate_uncached(question: str, schema: str, settings: Settings) -> str:
        nonlocal calls
        calls += 1
        return "SELECT organizations.name FROM organizations JOIN invoices ON invoices.id = invoices.id;"

    monkeypatch.setattr("text_to_sql_agent.sql_generator._generate_sql_uncached", fake_generate_uncached)

    first = generate_sql("Which customers have overdue invoice balance?", settings=settings)
    second = generate_sql("Show overdue invoice balances by customer", settings=settings)

    assert first == second
    assert calls == 1
