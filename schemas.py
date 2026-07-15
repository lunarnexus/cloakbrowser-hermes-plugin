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
    "browser_type": {
        "name": "browser_type",
        "description": "Type text into an input or editable element. Accepts either a snapshot ref like '@e2' or a CSS selector. In humanized mode it focuses the field, clears via keyboard, types with uneven delays, and can optionally submit with Enter.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Snapshot ref such as '@e2'."},
                "selector": {"type": "string", "description": "CSS selector when no snapshot ref is available."},
                "text": {"type": "string", "description": "The text to type into the field."},
                "submit": {"type": "boolean", "default": False, "description": "Press Enter after typing."},
                "clear": {"type": "boolean", "default": True, "description": "Clear existing text before typing."},
                "humanize": {"type": "boolean", "description": "Override config and force humanized or direct typing for this call."},
                "min_delay_ms": {"type": "integer", "description": "Minimum per-character delay for humanized typing."},
                "max_delay_ms": {"type": "integer", "description": "Maximum per-character delay for humanized typing."},
            },
            "required": ["text"],
            "anyOf": [{"required": ["ref"]}, {"required": ["selector"]}],
        },
    },
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
    if name in FALLBACK_SCHEMAS:
        return FALLBACK_SCHEMAS[name]
    return BROWSER_SCHEMAS.get(name, {"name": name, "parameters": {"type": "object"}})
