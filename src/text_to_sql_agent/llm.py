from langchain_mistralai import ChatMistralAI

from text_to_sql_agent.config import Settings


class LLMConfigurationError(RuntimeError):
    """Raised when the LLM client cannot be configured."""


def create_mistral_chat(settings: Settings) -> ChatMistralAI:
    if not settings.mistral_api_key:
        raise LLMConfigurationError("MISTRAL_API_KEY is not configured.")
    return ChatMistralAI(
        model=settings.mistral_model,
        api_key=settings.mistral_api_key,
        temperature=0,
    )


def test_mistral_connection(settings: Settings) -> dict[str, str]:
    chat = create_mistral_chat(settings)
    response = chat.invoke("Reply with exactly: ok")
    return {"status": "ok", "message": str(response.content)}

