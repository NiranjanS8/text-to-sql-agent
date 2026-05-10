import json

from text_to_sql_agent.config import Settings
from text_to_sql_agent.mongo_query import (
    cleanup_mongo_query,
    execute_mongo_query,
    explain_mongo_query,
    run_mongo_pipeline,
    validate_mongo_query,
)


class FakeMongoContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def __getitem__(self, name):
        return self

    def aggregate(self, pipeline):
        return [{"_id": "students:1", "name": "Aarav Sharma", "city": "Delhi"}]


def test_cleanup_mongo_query_removes_json_fences() -> None:
    raw = '```json\n{"collection":"students","pipeline":[{"$limit":5}]}\n```'

    assert cleanup_mongo_query(raw) == '{"collection":"students","pipeline":[{"$limit":5}]}'


def test_validate_mongo_query_allows_safe_aggregation() -> None:
    query = {
        "collection": "students",
        "pipeline": [
            {"$match": {"city": "Delhi"}},
            {"$project": {"_id": 0, "name": 1, "city": 1}},
            {"$limit": 10},
        ],
    }

    result = validate_mongo_query(json.dumps(query))

    assert result.is_safe is True
    assert result.collection == "students"
    assert result.pipeline == query["pipeline"]


def test_validate_mongo_query_blocks_unknown_collection() -> None:
    result = validate_mongo_query('{"collection":"query_history","pipeline":[{"$limit":5}]}')

    assert result.is_safe is False
    assert result.error == "Collection is not queryable by this agent: query_history."


def test_validate_mongo_query_blocks_write_stage() -> None:
    result = validate_mongo_query('{"collection":"students","pipeline":[{"$out":"copy"}]}')

    assert result.is_safe is False
    assert result.error == "MongoDB stage is not allowed: $out."


def test_validate_mongo_query_blocks_nested_function_operator() -> None:
    result = validate_mongo_query(
        '{"collection":"students","pipeline":[{"$project":{"x":{"$function":{"body":"function() {}","args":[],"lang":"js"}}}}]}'
    )

    assert result.is_safe is False
    assert result.error == "MongoDB operator is not allowed: $function."


def test_explain_mongo_query_describes_pipeline() -> None:
    explanation = explain_mongo_query('{"collection":"students","pipeline":[{"$match":{"city":"Delhi"}},{"$limit":5}]}')

    assert explanation == "This MongoDB aggregation reads from the students collection using these stage(s): $match, $limit."


def test_execute_mongo_query_returns_json_ready_rows(monkeypatch) -> None:
    monkeypatch.setattr("text_to_sql_agent.mongo_query.get_connection", lambda database_path=None: FakeMongoContext())

    result = execute_mongo_query(
        "Show Delhi students",
        '{"collection":"students","pipeline":[{"$match":{"city":"Delhi"}},{"$limit":5}]}',
        "mongodb://localhost:27017/text_to_sql",
    )

    assert result.status == "success"
    assert result.row_count == 1
    assert result.data == [{"_id": "students:1", "name": "Aarav Sharma", "city": "Delhi"}]


def test_run_mongo_pipeline_uses_generated_aggregation(monkeypatch) -> None:
    settings = Settings(DATABASE_URL="mongodb://localhost:27017/text_to_sql")
    monkeypatch.setattr("text_to_sql_agent.mongo_query.get_connection", lambda database_path=None: FakeMongoContext())
    monkeypatch.setattr("text_to_sql_agent.mongo_query.build_retrieved_schema_context", lambda *args, **kwargs: "students(id int, name str)")
    monkeypatch.setattr(
        "text_to_sql_agent.mongo_query.generate_mongo_query",
        lambda question, settings=None: '{"collection":"students","pipeline":[{"$limit":5}]}',
    )

    result = run_mongo_pipeline("Show students", settings=settings)

    assert result.execution.status == "success"
    assert result.execution.row_count == 1
    assert result.validated_sql == '{"collection":"students","pipeline":[{"$limit":5}]}'
