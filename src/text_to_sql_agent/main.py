import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from text_to_sql_agent.agent_workflow import execute_approved_sql, prepare_sql_for_approval, run_agent_pipeline
from text_to_sql_agent.cache import redis_health
from text_to_sql_agent.config import get_settings
from text_to_sql_agent.database import get_schema, initialize_database
from text_to_sql_agent.history import list_query_history, save_query_history
from text_to_sql_agent.llm import LLMConfigurationError, test_mistral_connection


RATE_LIMIT_MESSAGE = (
    "The LLM provider is rate limiting requests right now. Please wait a minute and try again, "
    "or switch to a lower-traffic model/API key."
)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, examples=["Show all students enrolled in Java course"])
    require_approval: bool = Field(default=False, description="Return generated SQL for review before execution.")


class ApproveRequest(BaseModel):
    question: str = Field(..., min_length=1)
    sql: str = Field(..., min_length=1)


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    initialize_database(settings.database_path)
    static_dir = Path(__file__).resolve().parents[2] / "static"
    react_index = static_dir / "react" / "index.html"

    app = FastAPI(
        title="Text-to-SQL Agent",
        version="0.1.0",
        description="FastAPI backend for natural-language SQL over SQLite.",
    )
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", tags=["ui"])
    def index() -> FileResponse:
        return FileResponse(react_index)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/schema", tags=["database"])
    def schema() -> dict[str, object]:
        return {"tables": get_schema(settings.database_path)}

    @app.get("/history", tags=["agent"])
    def history(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
        records = list_query_history(limit=limit, database_path=settings.database_path)
        return {"history": [record.to_dict() for record in records]}

    @app.post("/ask", tags=["agent"])
    def ask(request: AskRequest) -> dict[str, object]:
        try:
            if request.require_approval:
                workflow = prepare_sql_for_approval(request.question, settings=settings)
            else:
                workflow = run_agent_pipeline(request.question, settings=settings)
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            if _is_rate_limit_error(exc):
                raise HTTPException(status_code=429, detail=RATE_LIMIT_MESSAGE) from exc
            raise

        if workflow.execution.status != "awaiting_approval":
            save_query_history(workflow, database_path=settings.database_path)
        return workflow.to_dict()

    @app.post("/approve", tags=["agent"])
    def approve(request: ApproveRequest) -> dict[str, object]:
        workflow = execute_approved_sql(request.question, request.sql, settings=settings)
        save_query_history(workflow, database_path=settings.database_path)
        return workflow.to_dict()

    @app.get("/mistral/health", tags=["system"])
    def mistral_health() -> dict[str, str]:
        try:
            return test_mistral_connection(settings)
        except LLMConfigurationError as exc:
            return {"status": "not_configured", "message": str(exc)}
        except Exception as exc:
            if _is_rate_limit_error(exc):
                return {"status": "rate_limited", "message": RATE_LIMIT_MESSAGE}
            raise

    @app.get("/cache/health", tags=["system"])
    def cache_health() -> dict[str, str]:
        return redis_health(settings)

    return app


app = create_app()


def run() -> None:
    uvicorn.run("text_to_sql_agent.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run()


def _is_rate_limit_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(
        marker in text
        for marker in (
            "429",
            "rate limit",
            "rate_limit",
            "too many requests",
            "quota exceeded",
            "insufficient_quota",
        )
    )
