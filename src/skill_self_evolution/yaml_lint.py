"""YAML linting utilities powered by ryl (Rust YAML Linter).

Provides a thin wrapper that calls `ryl` CLI for YAML 1.2 linting and auto-fix.
Falls back gracefully if ryl is not installed.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from loguru import logger

RYL_CONFIG_PATH = Path(__file__).resolve().parents[2] / ".ryl.toml"


def _find_ryl() -> str | None:
    """Locate the ryl executable. Returns path or None."""
    import shutil

    which = shutil.which("ryl")
    if which:
        return which

    # Check venv Scripts directory (where pip installs console scripts)
    venv_scripts = Path(sys.prefix) / "Scripts"
    candidates = [
        venv_scripts / "ryl.exe",
        venv_scripts / "ryl",
        Path.home() / ".local" / "bin" / "ryl",
        Path.home() / ".cargo" / "bin" / "ryl",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def lint_yaml(yaml_text: str) -> list[str]:
    """Run ryl lint on a YAML string. Returns list of error messages (empty = clean).

    Args:
        yaml_text: The YAML content to lint.

    Returns:
        List of lint error strings. Empty list means clean.
    """
    ryl = _find_ryl()
    if not ryl:
        logger.debug("ryl not found, skipping YAML lint")
        return []

    config_flag = []
    if RYL_CONFIG_PATH.is_file():
        config_flag = ["--config-file", str(RYL_CONFIG_PATH)]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", encoding="utf-8", newline="\n", delete=False
    ) as tf:
        tf.write(yaml_text)
        tf_path = tf.name

    try:
        result = subprocess.run(
            [ryl, *config_flag, tf_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return []
        # ryl exits 2 when no config enables rules, exit 1 on lint errors
        errors = [
            line.strip()
            for line in (result.stdout + result.stderr).splitlines()
            if line.strip() and "error" in line.lower()
        ]
        if not errors:
            errors = [line.strip() for line in (result.stdout + result.stderr).splitlines() if line.strip()]
        return errors
    except FileNotFoundError:
        logger.debug("ryl not found, skipping YAML lint")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("ryl timed out, YAML lint skipped")
        return []
    finally:
        Path(tf_path).unlink(missing_ok=True)


def lint_and_fix_yaml(yaml_text: str) -> tuple[str, list[str]]:
    """Run ryl lint + auto-fix on a YAML string.

    Args:
        yaml_text: The YAML content to lint and fix.

    Returns:
        (fixed_yaml_text, remaining_errors) — fixed_text may be unchanged if no fixes,
        remaining_errors are issues ryl couldn't auto-fix.
    """
    ryl = _find_ryl()
    if not ryl:
        logger.debug("ryl not found, returning original")
        return yaml_text, []

    config_flag = []
    if RYL_CONFIG_PATH.is_file():
        config_flag = ["--config-file", str(RYL_CONFIG_PATH)]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", encoding="utf-8", newline="\n", delete=False
    ) as tf:
        tf.write(yaml_text)
        tf_path = tf.name

    try:
        # First, attempt auto-fix
        fix_result = subprocess.run(
            [ryl, "--fix", *config_flag, tf_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        # Read the (potentially fixed) file
        fixed_text = Path(tf_path).read_text(encoding="utf-8")

        # Then lint the fixed version
        lint_result = subprocess.run(
            [ryl, *config_flag, tf_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if lint_result.returncode == 0:
            return fixed_text, []

        remaining = [
            line.strip()
            for line in (lint_result.stdout + lint_result.stderr).splitlines()
            if line.strip()
        ]
        return fixed_text, remaining
    except FileNotFoundError:
        return yaml_text, []
    except subprocess.TimeoutExpired:
        logger.warning("ryl timed out")
        return yaml_text, []
    finally:
        Path(tf_path).unlink(missing_ok=True)
