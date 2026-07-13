from __future__ import annotations

import json
from typing import Any

try:
    from .session_manager import SessionManager
except ImportError:
    from session_manager import SessionManager  # type: ignore[no-redef]


def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


class BrowserTools:
    def __init__(self, manager: SessionManager):
        self.manager = manager

    def handle(self, name: str, args: dict[str, Any], **kwargs: Any) -> str:
        return to_json(self.manager.adapter.call(name, args or {}, **kwargs))
