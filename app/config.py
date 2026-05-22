from functools import lru_cache

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


OPENAI_MODEL_CHOICES = ("gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano")


class Settings(BaseSettings):
    bot_token: str = ""
    bot_use_proxy: bool = False
    bot_proxy_url: str | None = None
    gigachat_credentials: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4"
    openai_fallback_model: str = "gpt-5.4-mini"
    openai_daily_token_limit: int = 200_000
    openai_base_url: str = "https://api.openai.com/v1"
    ai_provider: str = "gigachat"
    database_url: str = "sqlite+aiosqlite:///./bot.db"
    admin_id: int | None = None
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("admin_id", mode="before")
    @classmethod
    def empty_admin_id_to_none(cls, value):
        if value == "":
            return None
        return value

    @field_validator("bot_proxy_url", mode="before")
    @classmethod
    def empty_proxy_url_to_none(cls, value):
        if value == "":
            return None
        return value

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def empty_openai_key_to_none(cls, value):
        if value == "":
            return None
        return value

    @field_validator("ai_provider", mode="before")
    @classmethod
    def normalize_ai_provider(cls, value):
        value = (value or "gigachat").strip().lower()
        return value if value in {"gigachat", "chatgpt"} else "gigachat"

    @field_validator("openai_model", mode="before")
    @classmethod
    def normalize_openai_model(cls, value):
        value = (value or "gpt-5.4").strip()
        return value if value in OPENAI_MODEL_CHOICES else "gpt-5.4"

    @field_validator("openai_fallback_model", mode="before")
    @classmethod
    def normalize_openai_fallback_model(cls, value):
        value = (value or "gpt-5.4-mini").strip()
        return value if value in OPENAI_MODEL_CHOICES else "gpt-5.4-mini"

    @field_validator("openai_daily_token_limit", mode="before")
    @classmethod
    def normalize_openai_daily_token_limit(cls, value):
        if value in {"", None}:
            return 200_000
        try:
            return int(value)
        except (TypeError, ValueError):
            return 200_000

    @field_validator("bot_use_proxy", mode="before")
    @classmethod
    def empty_use_proxy_to_false(cls, value):
        if value == "":
            return False
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
