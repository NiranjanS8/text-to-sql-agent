from langchain_core.output_parsers import StrOutputParser

from text_to_sql_agent.cache import get_cached_text
from text_to_sql_agent.config import Settings, get_settings
from text_to_sql_agent.llm import create_mistral_chat
from text_to_sql_agent.prompts import SQL_CORRECTION_PROMPT, SQL_GENERATION_PROMPT
from text_to_sql_agent.schema_rag import build_retrieved_schema_context
from text_to_sql_agent.sql_validator import cleanup_sql


SQL_GENERATION_CACHE_VERSION = "2026-05-10"


def cleanup_generated_sql(sql: str) -> str:
    return cleanup_sql(sql)


def generate_sql(question: str, settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    schema = build_retrieved_schema_context(question, active_settings.database_path, settings=active_settings)
    payload = {
        "question": question,
        "schema": schema,
        "model": active_settings.mistral_model,
        "prompt_version": SQL_GENERATION_CACHE_VERSION,
        "prompt": str(SQL_GENERATION_PROMPT),
    }
    return get_cached_text(
        "generated-sql",
        payload,
        lambda: _generate_sql_uncached(question, schema, active_settings),
        settings=active_settings,
    )


def _generate_sql_uncached(question: str, schema: str, settings: Settings) -> str:
    chat = create_mistral_chat(settings)
    chain = SQL_GENERATION_PROMPT | chat | StrOutputParser()
    sql = chain.invoke({"schema": schema, "question": question})
    return cleanup_generated_sql(sql)


def correct_sql(question: str, failed_sql: str, error: str, settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    schema = build_retrieved_schema_context(question, active_settings.database_path, settings=active_settings)
    payload = {
        "question": question,
        "schema": schema,
        "failed_sql": failed_sql,
        "error": error,
        "model": active_settings.mistral_model,
        "prompt_version": SQL_GENERATION_CACHE_VERSION,
        "prompt": str(SQL_CORRECTION_PROMPT),
    }
    return get_cached_text(
        "corrected-sql",
        payload,
        lambda: _correct_sql_uncached(question, failed_sql, error, schema, active_settings),
        settings=active_settings,
    )


def _correct_sql_uncached(question: str, failed_sql: str, error: str, schema: str, settings: Settings) -> str:
    chat = create_mistral_chat(settings)
    chain = SQL_CORRECTION_PROMPT | chat | StrOutputParser()
    sql = chain.invoke(
        {
            "schema": schema,
            "question": question,
            "failed_sql": failed_sql,
            "error": error,
        }
    )
    return cleanup_generated_sql(sql)
