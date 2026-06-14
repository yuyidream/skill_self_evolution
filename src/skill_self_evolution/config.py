"""
?????? ? ? APP_ENV ?? DeepSeek API ???????

- local: DeepSeek ?? API (api.deepseek.com)
- test/prod: ??? MaaS (api.modelarts-maas.com/v2)
"""

import os

from pydantic import BaseModel, Field

__all__ = ["DeepSeekEnvConfig", "DbConfig", "get_deepseek_config", "get_db_config"]


class DeepSeekEnvConfig(BaseModel):
    """DeepSeek API ?????Pydantic ????"""

    api_key: str = Field(default="", description="API Key")
    api_base: str = Field(
        default="https://api.deepseek.com/v1",
        description="API ????",
    )
    model: str = Field(default="deepseek-chat", description="????")


class DbConfig(BaseModel):
    """????????Pydantic ????"""

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=3306, ge=1, le=65535)
    user: str = Field(default="root")
    password: str = Field(default="")
    database: str = Field(default="housekeeping_ai_match_dev")


def _resolve_app_env() -> str:
    return os.getenv("APP_ENV", "local").strip().lower()


def get_deepseek_config(
    api_key: str = "",
    api_base: str = "",
    model: str = "",
) -> DeepSeekEnvConfig:
    env = _resolve_app_env()
    if api_key and api_base:
        return DeepSeekEnvConfig(
            api_key=api_key,
            api_base=api_base,
            model=model or "deepseek-chat",
        )
    if env == "local":
        key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        base = api_base or os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
        m = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        return DeepSeekEnvConfig(api_key=key, api_base=base, model=m)
    else:
        key = api_key or os.getenv("WX_MATCH_DEEPSEEK_API_KEY", "")
        base = api_base or os.getenv(
            "WX_MATCH_DEEPSEEK_API_BASE", "https://api.modelarts-maas.com/v2"
        )
        m = model or os.getenv("WX_MATCH_AI_MODEL_NAME", "DeepSeek-V3.2")
        return DeepSeekEnvConfig(api_key=key, api_base=base, model=m)


def get_db_config(
    host: str = "",
    port: int = 0,
    user: str = "",
    password: str = "",
    database: str = "",
) -> DbConfig:
    if host and user and password:
        return DbConfig(
            host=host,
            port=port or 3306,
            user=user,
            password=password,
            database=database or "housekeeping_ai_match_dev",
        )
    return DbConfig(
        host=host or os.getenv("DB_HOST", "127.0.0.1"),
        port=port or int(os.getenv("DB_PORT", "3306")),
        user=user or os.getenv("DB_USER", "root"),
        password=password or os.getenv("DB_PASSWORD", ""),
        database=database or os.getenv("DB_NAME", "housekeeping_ai_match_dev"),
    )
