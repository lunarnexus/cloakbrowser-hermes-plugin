from __future__ import annotations

import atexit
import shutil
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .adapter import CloakBrowserAdapter
    from .config import CloakConfig
except ImportError:
    from adapter import CloakBrowserAdapter  # type: ignore[no-redef]
    from config import CloakConfig  # type: ignore[no-redef]

MAX_CONSOLE_MESSAGES = 200
MAX_DIALOGS = 20
SCREENSHOT_TEMP_PREFIX = "cloakbrowser-vision-"
SCREENSHOT_MARKER = ".cloakbrowser-hermes-plugin"
OLD_SCREENSHOT_TEMP_MAX_AGE_SECONDS = 60 * 60


@dataclass
class BrowserSession:
    context: Any
    page: Any


@dataclass
class SharedBrowserContext:
    context: Any | None
    initial_page_claimed: bool = False
    ref_count: int = 0
    creating: bool = False
    closing: bool = False


_CONTEXT_REGISTRY: dict[str, SharedBrowserContext] = {}
_CONTEXT_REGISTRY_LOCK = threading.RLock()
_CONTEXT_REGISTRY_CONDITION = threading.Condition(_CONTEXT_REGISTRY_LOCK)


class SessionManager:
    def __init__(self, settings: CloakConfig):
        self.settings = settings
        self.adapter = CloakBrowserAdapter(settings, self)
        self._contexts: dict[str, SharedBrowserContext] = {}
        self._sessions: dict[str, BrowserSession] = {}
        self._screenshot_temp_dirs: set[Path] = set()
        self._creating_sessions: set[str] = set()
        self._closing = False
        self._closed = False
        self.cleanup_screenshot_temp_dirs(include_active=True)
        atexit.register(self.close_all)

    def new_screenshot_path(self) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix=SCREENSHOT_TEMP_PREFIX))
        (temp_dir / SCREENSHOT_MARKER).write_text("cloakbrowser-hermes-plugin\n")
        path = temp_dir / "screenshot.png"
        with _CONTEXT_REGISTRY_CONDITION:
            self._screenshot_temp_dirs.add(temp_dir)
        return path

    def cleanup_screenshot_temp_dirs(self, *, include_active: bool = False) -> None:
        temp_root = Path(tempfile.gettempdir())
        candidates: set[Path] = set()
        with _CONTEXT_REGISTRY_CONDITION:
            if include_active:
                candidates.update(self._screenshot_temp_dirs)
                self._screenshot_temp_dirs.clear()
            candidates.update(
                path
                for path in temp_root.glob(f"{SCREENSHOT_TEMP_PREFIX}*")
                if self._is_old_plugin_screenshot_temp_dir(path)
            )
        for path in candidates:
            shutil.rmtree(path, ignore_errors=True)

    def _is_old_plugin_screenshot_temp_dir(self, path: Path) -> bool:
        if not self._is_plugin_screenshot_temp_dir(path):
            return False
        try:
            return (time.time() - path.stat().st_mtime) >= OLD_SCREENSHOT_TEMP_MAX_AGE_SECONDS
        except OSError:
            return False

    def _is_plugin_screenshot_temp_dir(self, path: Path) -> bool:
        try:
            if not path.is_dir() or not path.name.startswith(SCREENSHOT_TEMP_PREFIX):
                return False
            return (path / SCREENSHOT_MARKER).exists() or (path / "screenshot.png").exists()
        except OSError:
            return False

    def _context_key(self) -> str:
        return str(Path(self.settings.user_data_dir).expanduser().resolve())

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
        context_key = self._context_key()

        while True:
            with _CONTEXT_REGISTRY_CONDITION:
                while self._closing:
                    _CONTEXT_REGISTRY_CONDITION.wait()
                session = self._sessions.get(key)
                if session is not None:
                    return session.page
                if key not in self._creating_sessions:
                    self._creating_sessions.add(key)
                    break
                _CONTEXT_REGISTRY_CONDITION.wait()

        try:
            shared = self._acquire_shared_context(context_key)
            context = shared.context
            if context is None:  # pragma: no cover - guarded by acquire path
                raise RuntimeError("CloakBrowser context creation did not publish a context")

            claim_initial_page = False
            with _CONTEXT_REGISTRY_CONDITION:
                if not shared.initial_page_claimed:
                    shared.initial_page_claimed = True
                    claim_initial_page = True

            pages = list(getattr(context, "pages", []) or []) if claim_initial_page else []
            page = pages[0] if pages else context.new_page()
            self._attach_console_capture(page)
            self._attach_dialog_capture(page)
            session = BrowserSession(context=context, page=page)

            with _CONTEXT_REGISTRY_CONDITION:
                existing = self._sessions.get(key)
                if existing is None:
                    self._sessions[key] = session
                    return page
                return existing.page
        finally:
            with _CONTEXT_REGISTRY_CONDITION:
                self._creating_sessions.discard(key)
                _CONTEXT_REGISTRY_CONDITION.notify_all()

    def _acquire_shared_context(self, context_key: str) -> SharedBrowserContext:
        create_owner = False
        with _CONTEXT_REGISTRY_CONDITION:
            shared = self._contexts.get(context_key)
            if shared is not None and not shared.closing and not shared.creating:
                self._closed = False
                return shared

            while True:
                shared = self._contexts.get(context_key)
                if shared is not None and not shared.closing and not shared.creating:
                    self._closed = False
                    return shared
                shared = _CONTEXT_REGISTRY.get(context_key)
                if shared is None:
                    shared = SharedBrowserContext(context=None, creating=True)
                    _CONTEXT_REGISTRY[context_key] = shared
                    create_owner = True
                    break
                if not shared.creating and not shared.closing:
                    shared.ref_count += 1
                    self._contexts[context_key] = shared
                    self._closed = False
                    return shared
                _CONTEXT_REGISTRY_CONDITION.wait()

        if create_owner:
            try:
                context = self.adapter.create_context()
            except Exception:
                with _CONTEXT_REGISTRY_CONDITION:
                    if _CONTEXT_REGISTRY.get(context_key) is shared:
                        _CONTEXT_REGISTRY.pop(context_key, None)
                    shared.creating = False
                    _CONTEXT_REGISTRY_CONDITION.notify_all()
                raise
            with _CONTEXT_REGISTRY_CONDITION:
                shared.context = context
                shared.creating = False
                shared.ref_count += 1
                self._contexts[context_key] = shared
                self._closed = False
                _CONTEXT_REGISTRY_CONDITION.notify_all()
                return shared

        raise RuntimeError("unreachable shared context acquisition state")

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

    def _attach_dialog_capture(self, page: Any) -> None:
        dialogs: deque[dict[str, Any]] = deque(maxlen=MAX_DIALOGS)
        setattr(page, "_cloak_dialogs", dialogs)
        setattr(page, "_cloak_handled_dialogs", deque(maxlen=MAX_DIALOGS))
        on = getattr(page, "on", None)
        if not callable(on):
            return

        def attr(dialog: Any, name: str, default: str = "") -> str:
            value = getattr(dialog, name, default)
            if callable(value):
                value = value()
            return str(value or default)

        def scrub(value: str, limit: int) -> str:
            redacted = self.adapter._redact_text(value, limit=limit)
            return "[REDACTED]" if "[REDACTED]" in redacted else redacted

        def capture(dialog: Any) -> None:
            dialogs.append(
                {
                    "type": scrub(attr(dialog, "type", "dialog"), 200),
                    "message": scrub(attr(dialog, "message"), 4000),
                    "default_value": scrub(attr(dialog, "default_value"), 1000),
                    "_handle": dialog,
                }
            )

        on("dialog", capture)

    def close_all(self) -> None:
        self.cleanup_screenshot_temp_dirs(include_active=True)
        contexts_to_close: list[tuple[str, SharedBrowserContext]] = []
        with _CONTEXT_REGISTRY_CONDITION:
            if self._closing:
                while self._closing:
                    _CONTEXT_REGISTRY_CONDITION.wait()
                return
            if self._closed and not self._contexts and not self._sessions:
                return
            self._closing = True
            while self._creating_sessions:
                _CONTEXT_REGISTRY_CONDITION.wait()
            for context_key, shared in list(self._contexts.items()):
                shared.ref_count = max(0, shared.ref_count - 1)
                if (
                    shared.ref_count == 0
                    and not shared.closing
                    and _CONTEXT_REGISTRY.get(context_key) is shared
                ):
                    shared.closing = True
                    contexts_to_close.append((context_key, shared))
            self._sessions.clear()
            self._creating_sessions.clear()
            self._contexts.clear()
            self._closed = True
            if not contexts_to_close:
                self._closing = False
                _CONTEXT_REGISTRY_CONDITION.notify_all()
                return
        for context_key, shared in contexts_to_close:
            try:
                close = getattr(shared.context, "close", None)
                if callable(close):
                    self.adapter.run(close())
            except Exception:
                pass
            finally:
                with _CONTEXT_REGISTRY_CONDITION:
                    if _CONTEXT_REGISTRY.get(context_key) is shared:
                        _CONTEXT_REGISTRY.pop(context_key, None)
                    shared.closing = False
                    _CONTEXT_REGISTRY_CONDITION.notify_all()
        with _CONTEXT_REGISTRY_CONDITION:
            self._closing = False
            _CONTEXT_REGISTRY_CONDITION.notify_all()
        self.cleanup_screenshot_temp_dirs(include_active=True)

    def status(self) -> dict[str, object]:
        return {
            "ready": True,
            "connected": bool(self._sessions),
            "profile_configured": bool(self.settings.user_data_dir),
            "mode": "direct-sdk",
            "sessions": len(self._sessions),
        }
