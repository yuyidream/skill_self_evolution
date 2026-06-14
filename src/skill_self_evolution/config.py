"""
?????? ? ? APP_ENV ?? DeepSeek API ???

- local: DeepSeek ?? API (api.deepseek.com)
- test/prod: ??? MaaS (api.modelarts-maas.com/v2)
"""

import os
from dataclasses import dataclass

__all__ = ["DeepSeekEnvConfig", "get_deepseek_config", "get_db_config"]


@dataclass
class DeepSeekEnvConfig:
    api_key: str = ""
    api_base: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"


def _resolve_app_env() -> str:
    return os.getenv("APP_ENV", "local").strip().lower()


def get_deepseek_config(api_key="", api_base="", model=""):
    env = _resolve_app_env()
    if api_key and api_base:
        return DeepSeekEnvConfig(api_key=api_key, api_base=api_base, model=model or "deepseek-chat")
    if env == "local":
        key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        base = api_base or os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
        m = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        return DeepSeekEnvConfig(api_key=key, api_base=base, model=m)
    else:
        key = api_key or os.getenv("WX_MATCH_DEEPSEEK_API_KEY", "")
        base = api_base or os.getenv("WX_MATCH_DEEPSEEK_API_BASE", "https://api.modelarts-maas.com/v2")
        m = model or os.getenv("WX_MATCH_AI_MODEL_NAME", "DeepSeek-V3.2")
        return DeepSeekEnvConfig(api_key=key, api_base=base, model=m)


def get_db_config(host="", port=0, user="", password="", database=""):
    if host and user and password:
        return {"host": host, "port": port or 3306, "user": user, "password": password, "database": database or "housekeeping_ai_match_dev"}
    return {
        "host": host or os.getenv("DB_HOST", "127.0.0.1"),
        "port": port or int(os.getenv("DB_PORT", "3306")),
        "user": user or os.getenv("DB_USER", "root"),
        "password": password or os.getenv("DB_PASSWORD", ""),
        "database": database or os.getenv("DB_NAME", "housekeeping_ai_match_dev"),
    }
