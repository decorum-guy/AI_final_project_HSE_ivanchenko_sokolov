from functools import lru_cache

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class Settings(BaseSettings):
    bot_token: str = ""
    bot_use_proxy: bool = False
    bot_proxy_url: str | None = None
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

    @field_validator("bot_proxy_url", mode="before")
    @classmethod
    def empty_proxy_url_to_none(cls, value):
        if value == "":
            return None
        return value

    @field_validator("bot_use_proxy", mode="before")
    @classmethod
    def empty_use_proxy_to_false(cls, value):
        if value == "":
            return False
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
