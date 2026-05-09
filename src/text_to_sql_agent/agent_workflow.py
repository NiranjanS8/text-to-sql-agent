from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from text_to_sql_agent.config import Settings, get_settings
from text_to_sql_agent.database import format_schema_for_prompt
from text_to_sql_agent.edge_cases import (
    apply_question_sql_hints,
    resolve_empty_result_edge_case,
    resolve_validation_edge_case,
)
from text_to_sql_agent.query_executor import QueryExecutionResult, execute_sql
from text_to_sql_agent.response_formatter import build_final_answer, explain_sql
from text_to_sql_agent.schema_rag import build_retrieved_schema_context
from text_to_sql_agent.sql_generator import correct_sql, generate_sql
from text_to_sql_agent.sql_validator import ValidationResult, validate_sql


@dataclass(frozen=True)
class AgentWorkflowResult:
    question: str
    schema_context: str
    generated_sql: str
    validated_sql: str
    validation: ValidationResult
    execution: QueryExecutionResult
    corrected_sql: list[str]
    retry_count: int
    explanation: str
    final_answer: str

    def to_dict(self) -> dict[str, Any]:
        response = self.execution.to_dict()
        response["original_sql"] = self.generated_sql
        response["corrected_sql"] = self.corrected_sql
        response["retry_count"] = self.retry_count
        response["explanation"] = self.explanation
        response["final_answer"] = self.final_answer
        return response


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


def create_sql_correction_tool(settings: Settings | None = None) -> StructuredTool:
    active_settings = settings or get_settings()

    def repair(question: str, failed_sql: str, error: str) -> str:
        return correct_sql(question=question, failed_sql=failed_sql, error=error, settings=active_settings)

    return StructuredTool.from_function(
        func=repair,
        name="sql_correction",
        description="Repairs a failed SQLite SELECT query using the database schema and SQLite error.",
    )


def create_sql_explanation_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=explain_sql,
        name="sql_explanation",
        description="Explains a generated SQL query in simple English.",
    )


def create_final_answer_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=build_final_answer,
        name="final_answer",
        description="Builds a concise natural-language answer from query execution results.",
    )


def prepare_sql_for_approval(question: str, settings: Settings | None = None) -> AgentWorkflowResult:
    active_settings = settings or get_settings()
    database_path = active_settings.database_path

    generation_tool = create_sql_generation_tool(active_settings)
    validation_tool = create_sql_validation_tool()
    explanation_tool = create_sql_explanation_tool()
    final_answer_tool = create_final_answer_tool()

    schema_context = build_retrieved_schema_context(question, database_path)
    generated_sql = generation_tool.invoke({"question": question})
    hinted_sql = apply_question_sql_hints(question, generated_sql)
    validation = validation_tool.invoke({"sql": hinted_sql})
    preview_sql = validation.sql if validation.is_safe else hinted_sql
    execution = QueryExecutionResult(
        question=question,
        sql=preview_sql,
        status="awaiting_approval" if validation.is_safe else "validation_error",
        error=None if validation.is_safe else validation.error,
        message="Review and approve this read-only SQL before execution." if validation.is_safe else None,
    )
    explanation = explanation_tool.invoke({"sql": preview_sql})
    final_answer = final_answer_tool.invoke({"result": execution})

    return AgentWorkflowResult(
        question=question,
        schema_context=schema_context,
        generated_sql=generated_sql,
        validated_sql=validation.sql,
        validation=validation,
        execution=execution,
        corrected_sql=[],
        retry_count=0,
        explanation=explanation,
        final_answer=final_answer,
    )


def execute_approved_sql(question: str, sql: str, settings: Settings | None = None) -> AgentWorkflowResult:
    active_settings = settings or get_settings()
    database_path = active_settings.database_path

    validation_tool = create_sql_validation_tool()
    execution_tool = create_sql_execution_tool(database_path)
    explanation_tool = create_sql_explanation_tool()
    final_answer_tool = create_final_answer_tool()

    schema_context = build_retrieved_schema_context(question, database_path)
    validation = validation_tool.invoke({"sql": sql})
    sql_to_execute = validation.sql if validation.is_safe else sql
    execution = execution_tool.invoke({"question": question, "sql": sql_to_execute})

    if execution.status == "validation_error":
        edge_case_result = resolve_validation_edge_case(question, validation, database_path)
        if edge_case_result:
            execution = edge_case_result

    if execution.status == "success" and execution.row_count == 0:
        edge_case_result = resolve_empty_result_edge_case(question, database_path)
        if edge_case_result:
            execution = edge_case_result

    explanation = explanation_tool.invoke({"sql": execution.sql})
    final_answer = final_answer_tool.invoke({"result": execution})

    return AgentWorkflowResult(
        question=question,
        schema_context=schema_context,
        generated_sql=sql,
        validated_sql=validation.sql,
        validation=validation,
        execution=execution,
        corrected_sql=[],
        retry_count=0,
        explanation=explanation,
        final_answer=final_answer,
    )


def run_agent_pipeline(
    question: str,
    settings: Settings | None = None,
    max_retries: int = 2,
    max_empty_result_retries: int = 1,
) -> AgentWorkflowResult:
    active_settings = settings or get_settings()
    database_path = active_settings.database_path

    generation_tool = create_sql_generation_tool(active_settings)
    validation_tool = create_sql_validation_tool()
    execution_tool = create_sql_execution_tool(database_path)
    correction_tool = create_sql_correction_tool(active_settings)
    explanation_tool = create_sql_explanation_tool()
    final_answer_tool = create_final_answer_tool()

    schema_context = build_retrieved_schema_context(question, database_path)
    generated_sql = generation_tool.invoke({"question": question})
    hinted_sql = apply_question_sql_hints(question, generated_sql)
    validation = validation_tool.invoke({"sql": hinted_sql})
    sql_to_execute = validation.sql if validation.is_safe else generated_sql
    execution = execution_tool.invoke({"question": question, "sql": sql_to_execute})
    corrected_sql: list[str] = []

    if execution.status == "validation_error":
        edge_case_result = resolve_validation_edge_case(question, validation, database_path)
        if edge_case_result:
            execution = edge_case_result

    retries_used = 0
    while execution.status == "sql_error" and retries_used < max_retries:
        retries_used += 1
        repaired_sql = correction_tool.invoke(
            {
                "question": question,
                "failed_sql": execution.sql,
                "error": execution.error or "Unknown SQLite error.",
            }
        )
        corrected_sql.append(repaired_sql)
        validation = validation_tool.invoke({"sql": repaired_sql})
        sql_to_execute = validation.sql if validation.is_safe else repaired_sql
        execution = execution_tool.invoke({"question": question, "sql": sql_to_execute})
        if not validation.is_safe:
            break

    if execution.status == "success" and execution.row_count == 0:
        edge_case_result = resolve_empty_result_edge_case(question, database_path)
        if edge_case_result:
            execution = edge_case_result

    empty_result_retries = 0
    while execution.status == "success" and execution.row_count == 0 and empty_result_retries < max_empty_result_retries:
        empty_result_retries += 1
        retries_used += 1
        repaired_sql = correction_tool.invoke(
            {
                "question": question,
                "failed_sql": execution.sql,
                "error": (
                    "Query executed successfully but returned no rows. "
                    "Reconsider exact text filters and use LIKE wildcards for partial user terms."
                ),
            }
        )
        corrected_sql.append(repaired_sql)
        validation = validation_tool.invoke({"sql": repaired_sql})
        sql_to_execute = validation.sql if validation.is_safe else repaired_sql
        execution = execution_tool.invoke({"question": question, "sql": sql_to_execute})
        if not validation.is_safe:
            break

    explanation = explanation_tool.invoke({"sql": execution.sql})
    final_answer = final_answer_tool.invoke({"result": execution})

    return AgentWorkflowResult(
        question=question,
        schema_context=schema_context,
        generated_sql=generated_sql,
        validated_sql=validation.sql,
        validation=validation,
        execution=execution,
        corrected_sql=corrected_sql,
        retry_count=retries_used,
        explanation=explanation,
        final_answer=final_answer,
    )
