from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


class Settings(BaseSettings):
    mistral_api_key: str | None = Field(default=None, alias="MISTRAL_API_KEY")
    mistral_model: str = Field(default="mistral-large-latest", alias="MISTRAL_MODEL")
    database_url: str = Field(default="sqlite:///data/text_to_sql.db", alias="DATABASE_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    @property
    def database_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("Only sqlite:/// DATABASE_URL values are supported.")
        path = self.database_url.replace("sqlite:///", "", 1)
        return (ROOT_DIR / path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()

