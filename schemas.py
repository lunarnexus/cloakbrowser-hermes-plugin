from __future__ import annotations

try:
    from tools.browser_tool import _BROWSER_SCHEMA_MAP as BROWSER_SCHEMAS
except Exception:
    BROWSER_SCHEMAS = {}

BROWSER_TOOL_NAMES = [
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_scroll",
    "browser_back",
    "browser_press",
    "browser_get_images",
    "browser_console",
]


def schema_for(name: str) -> dict:
    return BROWSER_SCHEMAS.get(name, {"name": name, "parameters": {"type": "object"}})
