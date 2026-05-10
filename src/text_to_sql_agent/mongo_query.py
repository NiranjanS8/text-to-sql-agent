import json
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from text_to_sql_agent.config import Settings, get_settings
from text_to_sql_agent.database import get_connection
from text_to_sql_agent.llm import create_mistral_chat
from text_to_sql_agent.query_executor import QueryExecutionResult
from text_to_sql_agent.response_formatter import build_final_answer
from text_to_sql_agent.schema_rag import build_retrieved_schema_context
from text_to_sql_agent.sql_validator import ALLOWED_TABLES


MONGO_ALLOWED_STAGES = {
    "$addFields",
    "$count",
    "$group",
    "$limit",
    "$lookup",
    "$match",
    "$project",
    "$set",
    "$sort",
    "$unwind",
}
MONGO_BLOCKED_OPERATORS = {"$accumulator", "$function", "$merge", "$out", "$where"}
MONGO_QUERY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a careful Text-to-MongoDB assistant.
Use only the collections and fields in the schema.
Return exactly one JSON object and no prose.
The JSON object must have this shape: {"collection": "collection_name", "pipeline": [aggregation stages]}.
Use aggregation pipelines only. Do not use JavaScript functions, $where, $out, or $merge.
Add a reasonable $limit when returning raw documents.
""".strip(),
        ),
        (
            "human",
            """
Schema:
{schema}

Question:
{question}

MongoDB query JSON:
""".strip(),
        ),
    ]
)


@dataclass(frozen=True)
class MongoValidationResult:
    query: str
    is_safe: bool
    error: str | None = None
    collection: str | None = None
    pipeline: list[dict[str, Any]] | None = None


def generate_mongo_query(question: str, settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    schema = build_retrieved_schema_context(question, active_settings.database_source, settings=active_settings)
    chat = create_mistral_chat(active_settings)
    chain = MONGO_QUERY_PROMPT | chat | StrOutputParser()
    return cleanup_mongo_query(chain.invoke({"schema": schema, "question": question}))


def validate_mongo_query(query: str) -> MongoValidationResult:
    cleaned = cleanup_mongo_query(query)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return MongoValidationResult(query=cleaned, is_safe=False, error=f"MongoDB query must be valid JSON: {exc.msg}.")

    if not isinstance(payload, dict):
        return MongoValidationResult(query=cleaned, is_safe=False, error="MongoDB query must be a JSON object.")

    collection = payload.get("collection")
    pipeline = payload.get("pipeline")
    if not isinstance(collection, str) or not collection:
        return MongoValidationResult(query=cleaned, is_safe=False, error="MongoDB query must specify a collection.")
    if collection not in ALLOWED_TABLES:
        return MongoValidationResult(query=cleaned, is_safe=False, error=f"Collection is not queryable by this agent: {collection}.")
    if not isinstance(pipeline, list):
        return MongoValidationResult(query=cleaned, is_safe=False, error="MongoDB query must include a pipeline array.")
    if len(pipeline) > 12:
        return MongoValidationResult(query=cleaned, is_safe=False, error="MongoDB pipeline is too large.")

    for stage in pipeline:
        if not isinstance(stage, dict) or len(stage) != 1:
            return MongoValidationResult(query=cleaned, is_safe=False, error="Each MongoDB pipeline stage must be a single-key object.")
        stage_name = next(iter(stage))
        if stage_name not in MONGO_ALLOWED_STAGES:
            return MongoValidationResult(query=cleaned, is_safe=False, error=f"MongoDB stage is not allowed: {stage_name}.")
        blocked = _find_blocked_operator(stage)
        if blocked:
            return MongoValidationResult(query=cleaned, is_safe=False, error=f"MongoDB operator is not allowed: {blocked}.")

    normalized = json.dumps({"collection": collection, "pipeline": pipeline}, sort_keys=True, separators=(",", ":"))
    return MongoValidationResult(query=normalized, is_safe=True, collection=collection, pipeline=pipeline)


def execute_mongo_query(question: str, query: str, database_path: str | None = None) -> QueryExecutionResult:
    validation = validate_mongo_query(query)
    if not validation.is_safe:
        return QueryExecutionResult(question=question, sql=validation.query, status="validation_error", error=validation.error)

    try:
        with get_connection(database_path) as database:
            rows = list(database[validation.collection].aggregate(validation.pipeline or []))
    except Exception as exc:
        return QueryExecutionResult(question=question, sql=validation.query, status="query_error", error=str(exc))

    data = [_json_ready(row) for row in rows]
    return QueryExecutionResult(
        question=question,
        sql=validation.query,
        data=data,
        row_count=len(data),
        message="No rows found." if not data else None,
    )


def explain_mongo_query(query: str) -> str:
    validation = validate_mongo_query(query)
    if not validation.is_safe:
        return "No safe MongoDB query was generated."
    stages = ", ".join(stage_name for stage in validation.pipeline or [] for stage_name in stage)
    return f"This MongoDB aggregation reads from the {validation.collection} collection using these stage(s): {stages}."


def run_mongo_pipeline(question: str, settings: Settings | None = None) -> Any:
    from text_to_sql_agent.agent_workflow import AgentWorkflowResult
    from text_to_sql_agent.sql_validator import ValidationResult

    active_settings = settings or get_settings()
    schema_context = build_retrieved_schema_context(question, active_settings.database_source, settings=active_settings)
    generated_query = generate_mongo_query(question, settings=active_settings)
    validation = validate_mongo_query(generated_query)
    execution = execute_mongo_query(question, validation.query, str(active_settings.database_source))
    explanation = explain_mongo_query(execution.sql)
    final_answer = build_final_answer(execution)

    return AgentWorkflowResult(
        question=question,
        schema_context=schema_context,
        generated_sql=generated_query,
        validated_sql=validation.query,
        validation=ValidationResult(sql=validation.query, is_safe=validation.is_safe, error=validation.error),
        execution=execution,
        corrected_sql=[],
        retry_count=0,
        explanation=explanation,
        final_answer=final_answer,
    )


def prepare_mongo_for_approval(question: str, settings: Settings | None = None) -> Any:
    from text_to_sql_agent.agent_workflow import AgentWorkflowResult
    from text_to_sql_agent.sql_validator import ValidationResult

    active_settings = settings or get_settings()
    schema_context = build_retrieved_schema_context(question, active_settings.database_source, settings=active_settings)
    generated_query = generate_mongo_query(question, settings=active_settings)
    validation = validate_mongo_query(generated_query)
    execution = QueryExecutionResult(
        question=question,
        sql=validation.query,
        status="awaiting_approval" if validation.is_safe else "validation_error",
        error=None if validation.is_safe else validation.error,
        message="Review and approve this read-only MongoDB aggregation before execution." if validation.is_safe else None,
    )
    explanation = explain_mongo_query(validation.query)
    final_answer = build_final_answer(execution)
    return AgentWorkflowResult(
        question=question,
        schema_context=schema_context,
        generated_sql=generated_query,
        validated_sql=validation.query,
        validation=ValidationResult(sql=validation.query, is_safe=validation.is_safe, error=validation.error),
        execution=execution,
        corrected_sql=[],
        retry_count=0,
        explanation=explanation,
        final_answer=final_answer,
    )


def execute_approved_mongo_query(question: str, query: str, settings: Settings | None = None) -> Any:
    from text_to_sql_agent.agent_workflow import AgentWorkflowResult
    from text_to_sql_agent.sql_validator import ValidationResult

    active_settings = settings or get_settings()
    schema_context = build_retrieved_schema_context(question, active_settings.database_source, settings=active_settings)
    validation = validate_mongo_query(query)
    execution = execute_mongo_query(question, validation.query, str(active_settings.database_source))
    explanation = explain_mongo_query(execution.sql)
    final_answer = build_final_answer(execution)
    return AgentWorkflowResult(
        question=question,
        schema_context=schema_context,
        generated_sql=query,
        validated_sql=validation.query,
        validation=ValidationResult(sql=validation.query, is_safe=validation.is_safe, error=validation.error),
        execution=execution,
        corrected_sql=[],
        retry_count=0,
        explanation=explanation,
        final_answer=final_answer,
    )


def cleanup_mongo_query(query: str) -> str:
    cleaned = query.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").strip()
        if cleaned.lower().startswith(("json", "javascript", "js")):
            cleaned = re.sub(r"^(json|javascript|js)", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = cleaned.removesuffix("```").strip()
    return cleaned


def _find_blocked_operator(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in MONGO_BLOCKED_OPERATORS:
                return key
            blocked = _find_blocked_operator(nested)
            if blocked:
                return blocked
    if isinstance(value, list):
        for item in value:
            blocked = _find_blocked_operator(item)
            if blocked:
                return blocked
    return None


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_ready(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if not isinstance(value, str | int | float | bool | type(None)):
        return str(value)
    return value
