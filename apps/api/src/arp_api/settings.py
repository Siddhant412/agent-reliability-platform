from __future__ import annotations

from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARP_", extra="ignore")

    app_name: str = "Agent Reliability Platform API"
    database_url: str = "sqlite+pysqlite:///./.arp/dev.db"
    auth_mode: Literal["development_header", "api_key"] = "development_header"
    api_tokens: dict[str, UUID] = Field(default_factory=dict)


@lru_cache(maxsize=1)
def get_settings() -> APISettings:
    return APISettings()
