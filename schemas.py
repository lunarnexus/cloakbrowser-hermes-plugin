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
    "browser_dialog",
    "browser_vision",
]

FALLBACK_SCHEMAS = {
    "browser_dialog": {
        "name": "browser_dialog",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["accept", "dismiss"]},
                "index": {"type": "integer", "description": "Dialog index; -1 selects latest."},
                "prompt_text": {"type": "string"},
            },
        },
    },
    "browser_vision": {
        "name": "browser_vision",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "annotate": {"type": "boolean", "default": False},
                "full_page": {"type": "boolean", "default": False},
            },
        },
    },
}


def schema_for(name: str) -> dict:
    return BROWSER_SCHEMAS.get(name, FALLBACK_SCHEMAS.get(name, {"name": name, "parameters": {"type": "object"}}))
