import logging

import uvicorn
from fastapi import FastAPI

from text_to_sql_agent.config import get_settings
from text_to_sql_agent.llm import LLMConfigurationError, test_mistral_connection


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    app = FastAPI(
        title="Text-to-SQL Agent",
        version="0.1.0",
        description="FastAPI backend for natural-language SQL over SQLite.",
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

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

