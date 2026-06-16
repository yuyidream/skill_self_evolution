"""内容哈希缓存 — 从 EvoSkill RunCache 适配。

原始：https://github.com/sentient-agi/EvoSkill

去掉了 AgentTrace / pydantic 依赖，简化为纯 JSON 键值缓存。
"""

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from skill_self_evolution.logging import get_logger

logger = get_logger(__name__)


class CacheConfig:
    """缓存配置。"""

    def __init__(
        self,
        cache_dir: str | Path = ".cache/runs",
        enabled: bool = True,
        hash_length: int = 12,
    ):
        self.cache_dir = Path(cache_dir)
        self.enabled = enabled
        self.hash_length = hash_length


class RunCache:
    """内容感知缓存：基于文件内容哈希自动失效。

    用法:
        cache = RunCache(watch_dirs=["./config/", "./prompts/"])
        result = cache.get("some_key")
        if result is None:
            result = expensive_computation()
            cache.set("some_key", result)
    """

    def __init__(
        self,
        config: CacheConfig | None = None,
        watch_dirs: list[str | Path] | None = None,
    ):
        self.config = config or CacheConfig()
        self._watch_dirs: list[Path] = [Path(d) for d in (watch_dirs or [])]
        if self.config.enabled:
            self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("cache.init", enabled=self.config.enabled,
                     watch_dirs=[str(d) for d in self._watch_dirs])

    def _get_tree_hash(self) -> str:
        """计算监控目录内容的聚合哈希。"""
        if not self._watch_dirs:
            return "no_watch_dirs"

        hasher = hashlib.sha256()
        for watch_dir in sorted(self._watch_dirs):
            if not watch_dir.exists():
                continue
            files = sorted(watch_dir.rglob("*"))
            for fp in files:
                if fp.is_file():
                    try:
                        hasher.update(str(fp.relative_to(watch_dir)).encode())
                        hasher.update(fp.read_bytes())
                    except (OSError, IOError):
                        pass
        tree_hash = hasher.hexdigest()
        logger.debug("cache.tree_hash", hash=tree_hash[:12])
        return tree_hash

    def _get_cache_path(self, key: str) -> Path:
        """获取缓存文件路径。"""
        tree_hash = self._get_tree_hash()
        key_hash = hashlib.sha256(key.encode()).hexdigest()[: self.config.hash_length]
        return self.config.cache_dir / tree_hash[: self.config.hash_length] / f"{key_hash}.json"

    def get(self, key: str) -> Any | None:
        """获取缓存值。若文件内容已变更则返回 None。"""
        if not self.config.enabled:
            return None

        cache_path = self._get_cache_path(key)
        if not cache_path.exists():
            logger.debug("cache.miss", key=key)
            return None

        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            logger.debug("cache.hit", key=key)
            return data.get("value")
        except (json.JSONDecodeError, OSError):
            logger.warning("cache.corrupt", key=key)
            cache_path.unlink(missing_ok=True)
            return None

    def set(self, key: str, value: Any) -> None:
        """写入缓存。"""
        if not self.config.enabled:
            return

        cache_path = self._get_cache_path(key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "key": key,
            "value": value,
        }

        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, indent=2, default=str), encoding="utf-8")
        tmp.rename(cache_path)
        logger.debug("cache.set", key=key)

    def clear(self) -> int:
        """清除所有缓存。返回删除条目数。"""
        if not self.config.cache_dir.exists():
            return 0
        count = sum(1 for _ in self.config.cache_dir.rglob("*.json"))
        shutil.rmtree(self.config.cache_dir)
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("cache.clear", entries=count)
        return count
