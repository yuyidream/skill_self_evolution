"""
skill-engine 测试夹具
"""

import sys
import tempfile
from pathlib import Path

import pytest

# 确保 skill-engine 在 path 中
_SKILL_ENGINE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SKILL_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ENGINE_ROOT))


@pytest.fixture
def temp_log_dir():
    """临时日志目录"""
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp
