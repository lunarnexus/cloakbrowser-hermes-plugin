from __future__ import annotations

import atexit
from collections import deque
from dataclasses import dataclass
from typing import Any

try:
    from .adapter import CloakBrowserAdapter
    from .config import CloakConfig
except ImportError:
    from adapter import CloakBrowserAdapter  # type: ignore[no-redef]
    from config import CloakConfig  # type: ignore[no-redef]

MAX_CONSOLE_MESSAGES = 200


@dataclass
class BrowserSession:
    context: Any
    page: Any


class SessionManager:
    def __init__(self, settings: CloakConfig):
        self.settings = settings
        self.adapter = CloakBrowserAdapter(settings, self)
        self._sessions: dict[str, BrowserSession] = {}
        atexit.register(self.close_all)

    def _session_key(
        self, *, task_id: str | None = None, session_id: str | None = None
    ) -> str:
        if session_id:
            return f"session:{session_id}"
        if task_id:
            return f"task:{task_id}"
        return "root:default-task"

    def page_for(
        self, *, task_id: str | None = None, session_id: str | None = None
    ) -> Any:
        key = self._session_key(task_id=task_id, session_id=session_id)
        session = self._sessions.get(key)
        if session is None:
            context = self.adapter.create_context()
            pages = list(getattr(context, "pages", []) or [])
            page = pages[0] if pages else context.new_page()
            self._attach_console_capture(page)
            session = BrowserSession(context=context, page=page)
            self._sessions[key] = session
        return session.page

    def _attach_console_capture(self, page: Any) -> None:
        messages: deque[dict[str, str]] = deque(maxlen=MAX_CONSOLE_MESSAGES)
        setattr(page, "_cloak_console_messages", messages)
        on = getattr(page, "on", None)
        if not callable(on):
            return

        def append_message(msg_type: str, text: str) -> None:
            messages.append(
                {"type": msg_type, "text": self.adapter._redact_text(text, limit=4000)}
            )

        def capture(message: Any) -> None:
            msg_type = getattr(message, "type", None)
            if callable(msg_type):
                msg_type = msg_type()
            text = getattr(message, "text", None)
            if callable(text):
                text = text()
            append_message(str(msg_type or "log"), str(text or ""))

        def capture_page_error(error: Any) -> None:
            append_message("pageerror", str(error or ""))

        on("console", capture)
        on("pageerror", capture_page_error)

    def close_all(self) -> None:
        for session in list(self._sessions.values()):
            close = getattr(session.context, "close", None)
            if callable(close):
                try:
                    self.adapter.run(close())
                except Exception:
                    pass
        self._sessions.clear()

    def status(self) -> dict[str, object]:
        return {
            "ready": True,
            "connected": bool(self._sessions),
            "profile_configured": bool(self.settings.user_data_dir),
            "mode": "direct-sdk",
            "sessions": len(self._sessions),
        }
