from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from text_to_sql_agent.config import Settings, get_settings
from text_to_sql_agent.database import format_schema_for_prompt
from text_to_sql_agent.query_executor import QueryExecutionResult, execute_sql
from text_to_sql_agent.sql_generator import generate_sql
from text_to_sql_agent.sql_validator import ValidationResult, validate_sql


@dataclass(frozen=True)
class AgentWorkflowResult:
    question: str
    schema_context: str
    generated_sql: str
    validated_sql: str
    validation: ValidationResult
    execution: QueryExecutionResult

    def to_dict(self) -> dict[str, Any]:
        return self.execution.to_dict()


def create_schema_context_tool(database_path: Path | None = None) -> StructuredTool:
    def get_schema_context() -> str:
        return format_schema_for_prompt(database_path)

    return StructuredTool.from_function(
        func=get_schema_context,
        name="schema_context",
        description="Fetches the SQLite schema context used for Text-to-SQL generation.",
    )


def create_sql_generation_tool(settings: Settings | None = None) -> StructuredTool:
    active_settings = settings or get_settings()

    def generate(question: str) -> str:
        return generate_sql(question, settings=active_settings)

    return StructuredTool.from_function(
        func=generate,
        name="sql_generation",
        description="Generates a SQLite SELECT query from a natural-language question.",
    )


def create_sql_validation_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=validate_sql,
        name="sql_validation",
        description="Validates that generated SQL is a single safe SELECT query.",
    )


def create_sql_execution_tool(database_path: Path | None = None) -> StructuredTool:
    def execute(question: str, sql: str) -> QueryExecutionResult:
        return execute_sql(question=question, sql=sql, database_path=database_path)

    return StructuredTool.from_function(
        func=execute,
        name="sql_execution",
        description="Executes validated SQL against SQLite and returns JSON-ready rows.",
    )


def run_agent_pipeline(question: str, settings: Settings | None = None) -> AgentWorkflowResult:
    active_settings = settings or get_settings()
    database_path = active_settings.database_path

    schema_tool = create_schema_context_tool(database_path)
    generation_tool = create_sql_generation_tool(active_settings)
    validation_tool = create_sql_validation_tool()
    execution_tool = create_sql_execution_tool(database_path)

    schema_context = schema_tool.invoke({})
    generated_sql = generation_tool.invoke({"question": question})
    validation = validation_tool.invoke({"sql": generated_sql})
    sql_to_execute = validation.sql if validation.is_safe else generated_sql
    execution = execution_tool.invoke({"question": question, "sql": sql_to_execute})

    return AgentWorkflowResult(
        question=question,
        schema_context=schema_context,
        generated_sql=generated_sql,
        validated_sql=validation.sql,
        validation=validation,
        execution=execution,
    )

