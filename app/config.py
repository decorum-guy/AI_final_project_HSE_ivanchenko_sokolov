from functools import lru_cache

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class Settings(BaseSettings):
    bot_token: str = ""
    gigachat_credentials: str | None = None
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
