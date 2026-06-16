"""OpenCode harness — option building, server management, and execution."""

from .options import build_opencode_options
from .executor import (
    execute_query,
    parse_response,
    shutdown_project_server,
    shutdown_all_servers,
)
from .skill_utils import normalize_project_skill_frontmatter, ensure_skill_frontmatter

__all__ = [
    "build_opencode_options",
    "execute_query",
    "parse_response",
    "shutdown_project_server",
    "shutdown_all_servers",
    "normalize_project_skill_frontmatter",
    "ensure_skill_frontmatter",
]
