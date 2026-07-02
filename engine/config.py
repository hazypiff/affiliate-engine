from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://njbot:CHANGEME@127.0.0.1:5432/affiliate_engine"
    test_database_url: str = "postgresql://njbot:CHANGEME@127.0.0.1:5432/affiliate_engine_test"
    llm_base: str = "http://127.0.0.1:18080"
    embed_base: str = "http://127.0.0.1:8095"
    embed_dim: int = 768


@lru_cache
def settings() -> Settings:
    return Settings()
