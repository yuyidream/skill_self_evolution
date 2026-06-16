"""
DeepSeek API 与数据库配置 — 通用，不绑定任何业务项目。

调用方应显式传入参数，或通过标准环境变量覆盖：
  DEEPSEEK_API_KEY / DEEPSEEK_API_BASE / DEEPSEEK_MODEL
  DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME
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
    """数据库配置 Pydantic 模型。调用方应显式传入 database。"""

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=3306, ge=1, le=65535)
    user: str = Field(default="root")
    password: str = Field(default="")
    database: str = Field(default="")


def get_deepseek_config(
    api_key: str = "",
    api_base: str = "",
    model: str = "",
) -> DeepSeekEnvConfig:
    if api_key and api_base:
        return DeepSeekEnvConfig(
            api_key=api_key,
            api_base=api_base,
            model=model or "deepseek-chat",
        )
    return DeepSeekEnvConfig(
        api_key=api_key or os.getenv("DEEPSEEK_API_KEY", ""),
        api_base=api_base or os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"),
        model=model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    )


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
            database=database or "",
        )
    return DbConfig(
        host=host or os.getenv("DB_HOST", "127.0.0.1"),
        port=port or int(os.getenv("DB_PORT", "3306")),
        user=user or os.getenv("DB_USER", "root"),
        password=password or os.getenv("DB_PASSWORD", ""),
        database=database or os.getenv("DB_NAME", ""),
    )
