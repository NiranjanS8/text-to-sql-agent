from langchain_core.output_parsers import StrOutputParser

from text_to_sql_agent.config import Settings, get_settings
from text_to_sql_agent.database import format_schema_for_prompt
from text_to_sql_agent.llm import create_mistral_chat
from text_to_sql_agent.prompts import SQL_GENERATION_PROMPT


def cleanup_generated_sql(sql: str) -> str:
    cleaned = sql.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").removesuffix("```").strip()
        if cleaned.lower().startswith("sql"):
            cleaned = cleaned[3:]
    return cleaned.strip()


def generate_sql(question: str, settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    schema = format_schema_for_prompt(active_settings.database_path)
    chat = create_mistral_chat(active_settings)
    chain = SQL_GENERATION_PROMPT | chat | StrOutputParser()
    sql = chain.invoke({"schema": schema, "question": question})
    return cleanup_generated_sql(sql)
