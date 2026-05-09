import logging

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from text_to_sql_agent.config import get_settings
from text_to_sql_agent.database import get_schema, initialize_database
from text_to_sql_agent.llm import LLMConfigurationError, test_mistral_connection
from text_to_sql_agent.query_executor import execute_sql
from text_to_sql_agent.sql_generator import generate_sql


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, examples=["Show all students enrolled in Java course"])


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    initialize_database(settings.database_path)

    app = FastAPI(
        title="Text-to-SQL Agent",
        version="0.1.0",
        description="FastAPI backend for natural-language SQL over SQLite.",
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/schema", tags=["database"])
    def schema() -> dict[str, object]:
        return {"tables": get_schema(settings.database_path)}

    @app.post("/ask", tags=["agent"])
    def ask(request: AskRequest) -> dict[str, object]:
        try:
            sql = generate_sql(request.question, settings=settings)
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        result = execute_sql(
            question=request.question,
            sql=sql,
            database_path=settings.database_path,
        )
        return result.to_dict()

    @app.get("/mistral/health", tags=["system"])
    def mistral_health() -> dict[str, str]:
        try:
            return test_mistral_connection(settings)
        except LLMConfigurationError as exc:
            return {"status": "not_configured", "message": str(exc)}

    return app


app = create_app()


def run() -> None:
    uvicorn.run("text_to_sql_agent.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run()
