import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from text_to_sql_agent.agent_workflow import run_agent_pipeline
from text_to_sql_agent.config import get_settings
from text_to_sql_agent.database import get_schema, initialize_database
from text_to_sql_agent.history import list_query_history, save_query_history
from text_to_sql_agent.llm import LLMConfigurationError, test_mistral_connection


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, examples=["Show all students enrolled in Java course"])


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    initialize_database(settings.database_path)
    static_dir = Path(__file__).resolve().parents[2] / "static"

    app = FastAPI(
        title="Text-to-SQL Agent",
        version="0.1.0",
        description="FastAPI backend for natural-language SQL over SQLite.",
    )
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", tags=["ui"])
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

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
            workflow = run_agent_pipeline(request.question, settings=settings)
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        save_query_history(workflow, database_path=settings.database_path)
        return workflow.to_dict()

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
