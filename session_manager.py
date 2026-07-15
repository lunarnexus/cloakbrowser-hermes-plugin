from __future__ import annotations

import atexit
import shutil
import tempfile
import threading
import time
import weakref
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .adapter import CloakBrowserAdapter, _OwnerThreadRunner
    from .config import CloakConfig
    from .preflight import detect_persistent_profile_collision
except ImportError:
    from adapter import CloakBrowserAdapter, _OwnerThreadRunner  # type: ignore[no-redef]
    from config import CloakConfig  # type: ignore[no-redef]
    from preflight import detect_persistent_profile_collision  # type: ignore[no-redef]

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
    owner: _OwnerThreadRunner | None = None
    initial_page_claimed: bool = False
    ref_count: int = 0
    creating: bool = False
    closing: bool = False


_CONTEXT_REGISTRY: dict[str, SharedBrowserContext] = {}
_CONTEXT_REGISTRY_LOCK = threading.RLock()
_CONTEXT_REGISTRY_CONDITION = threading.Condition(_CONTEXT_REGISTRY_LOCK)
_LIVE_MANAGERS: weakref.WeakSet[SessionManager] = weakref.WeakSet()
_ATEXIT_REGISTERED = False


def _close_live_managers_at_exit() -> None:
    for manager in list(_LIVE_MANAGERS):
        try:
            manager.close_all()
        except Exception:
            pass


def _finalize_manager(
    *,
    contexts: dict[str, SharedBrowserContext],
    sessions: dict[str, BrowserSession],
    creating_sessions: set[str],
    screenshot_temp_dirs: set[Path],
) -> None:
    candidates: set[Path] = set(screenshot_temp_dirs)
    screenshot_temp_dirs.clear()
    contexts_to_close: list[tuple[str, SharedBrowserContext]] = []
    owners_to_close: list[_OwnerThreadRunner] = []

    with _CONTEXT_REGISTRY_CONDITION:
        while creating_sessions:
            _CONTEXT_REGISTRY_CONDITION.wait(timeout=0.05)
        for context_key, shared in list(contexts.items()):
            shared.ref_count = max(0, shared.ref_count - 1)
            if (
                shared.ref_count == 0
                and not shared.closing
                and _CONTEXT_REGISTRY.get(context_key) is shared
            ):
                shared.closing = True
                contexts_to_close.append((context_key, shared))
        sessions.clear()
        creating_sessions.clear()
        contexts.clear()
        _CONTEXT_REGISTRY_CONDITION.notify_all()

    for context_key, shared in contexts_to_close:
        try:
            close = getattr(shared.context, "close", None)
            if callable(close):
                close()
        except Exception:
            pass
        finally:
            owner = shared.owner
            shared.owner = None
            with _CONTEXT_REGISTRY_CONDITION:
                if _CONTEXT_REGISTRY.get(context_key) is shared:
                    _CONTEXT_REGISTRY.pop(context_key, None)
                shared.closing = False
                _CONTEXT_REGISTRY_CONDITION.notify_all()
            if owner is not None:
                owners_to_close.append(owner)

    for owner in owners_to_close:
        owner.close()

    for path in candidates:
        shutil.rmtree(path, ignore_errors=True)


class SessionManager:
    def __init__(self, settings: CloakConfig):
        global _ATEXIT_REGISTERED
        self.settings = settings
        self.adapter = CloakBrowserAdapter(settings, self)
        self._contexts: dict[str, SharedBrowserContext] = {}
        self._sessions: dict[str, BrowserSession] = {}
        self._screenshot_temp_dirs: set[Path] = set()
        self._creating_sessions: set[str] = set()
        self._last_runtime_error: str | None = None
        self._closing = False
        self._closed = False
        self.cleanup_screenshot_temp_dirs(include_active=True)
        self._arm_finalizer()
        _LIVE_MANAGERS.add(self)
        if not _ATEXIT_REGISTERED:
            atexit.register(_close_live_managers_at_exit)
            _ATEXIT_REGISTERED = True

    def _arm_finalizer(self) -> None:
        self._finalizer = weakref.finalize(
            self,
            _finalize_manager,
            contexts=self._contexts,
            sessions=self._sessions,
            creating_sessions=self._creating_sessions,
            screenshot_temp_dirs=self._screenshot_temp_dirs,
        )

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

    def _set_runtime_error(self, message: str | None) -> None:
        with _CONTEXT_REGISTRY_CONDITION:
            self._last_runtime_error = message or None

    def _translate_runtime_error(self, exc: BaseException) -> BaseException:
        collision = detect_persistent_profile_collision(exc)
        if collision is not None:
            self._set_runtime_error(collision)
            return RuntimeError(collision)
        self._set_runtime_error(str(exc).strip() or type(exc).__name__)
        return exc

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
                    if self._session_is_live(session):
                        return session.page
                    self._drop_session_locked(key, session)
                    self._drop_dead_shared_context_locked(context_key)
                if key not in self._creating_sessions:
                    self._creating_sessions.add(key)
                    break
                _CONTEXT_REGISTRY_CONDITION.wait()

        try:
            for attempt in range(2):
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
                try:
                    page = pages[0] if pages else context.new_page()
                except Exception as exc:
                    if not pages and attempt == 0 and self._is_closed_target_error(exc):
                        with _CONTEXT_REGISTRY_CONDITION:
                            self._drop_shared_context_for_context_locked(
                                context_key, context=context, shared=shared
                            )
                        continue
                    raise
                self._attach_console_capture(page)
                self._attach_dialog_capture(page)
                session = BrowserSession(context=context, page=page)

                with _CONTEXT_REGISTRY_CONDITION:
                    existing = self._sessions.get(key)
                    if existing is None:
                        self._sessions[key] = session
                        self._last_runtime_error = None
                        return page
                    self._last_runtime_error = None
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
                if not self._shared_context_is_live(shared):
                    self._drop_dead_shared_context_locked(context_key, shared)
                else:
                    self._closed = False
                    return shared

            while True:
                shared = self._contexts.get(context_key)
                if shared is not None and not shared.closing and not shared.creating:
                    if not self._shared_context_is_live(shared):
                        self._drop_dead_shared_context_locked(context_key, shared)
                        continue
                    self._closed = False
                    return shared
                shared = _CONTEXT_REGISTRY.get(context_key)
                if shared is None:
                    shared = SharedBrowserContext(context=None, creating=True)
                    _CONTEXT_REGISTRY[context_key] = shared
                    create_owner = True
                    break
                if not shared.creating and not shared.closing and not self._shared_context_is_live(shared):
                    self._drop_dead_shared_context_locked(context_key, shared)
                    continue
                if not shared.creating and not shared.closing:
                    shared.ref_count += 1
                    self._contexts[context_key] = shared
                    self._closed = False
                    return shared
                _CONTEXT_REGISTRY_CONDITION.wait()

        if create_owner:
            owner = _OwnerThreadRunner()
            try:
                context = self.adapter.create_context(owner=owner)
            except Exception as exc:
                owner.close()
                translated = self._translate_runtime_error(exc)
                with _CONTEXT_REGISTRY_CONDITION:
                    if _CONTEXT_REGISTRY.get(context_key) is shared:
                        _CONTEXT_REGISTRY.pop(context_key, None)
                    shared.creating = False
                    _CONTEXT_REGISTRY_CONDITION.notify_all()
                raise translated
            with _CONTEXT_REGISTRY_CONDITION:
                shared.context = context
                shared.owner = owner
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
        redact_text = self.adapter._redact_text

        def append_message(msg_type: str, text: str) -> None:
            messages.append({"type": msg_type, "text": redact_text(text, limit=4000)})

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
        redact_text = self.adapter._redact_text

        def attr(dialog: Any, name: str, default: str = "") -> str:
            value = getattr(dialog, name, default)
            if callable(value):
                value = value()
            return str(value or default)

        def scrub(value: str, limit: int) -> str:
            redacted = redact_text(value, limit=limit)
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
        self._finalizer.detach()
        self._arm_finalizer()
        self.cleanup_screenshot_temp_dirs(include_active=True)
        contexts_to_close: list[tuple[str, SharedBrowserContext]] = []
        owners_to_close: list[_OwnerThreadRunner] = []
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
                    close()
            except Exception:
                pass
            finally:
                owner = shared.owner
                shared.owner = None
                with _CONTEXT_REGISTRY_CONDITION:
                    if _CONTEXT_REGISTRY.get(context_key) is shared:
                        _CONTEXT_REGISTRY.pop(context_key, None)
                    shared.closing = False
                    _CONTEXT_REGISTRY_CONDITION.notify_all()
                if owner is not None:
                    owners_to_close.append(owner)
        for owner in owners_to_close:
            owner.close()
        with _CONTEXT_REGISTRY_CONDITION:
            self._closing = False
            _CONTEXT_REGISTRY_CONDITION.notify_all()
        self.cleanup_screenshot_temp_dirs(include_active=True)

    def status(self) -> dict[str, object]:
        with _CONTEXT_REGISTRY_CONDITION:
            for key, session in list(self._sessions.items()):
                if not self._session_is_live(session):
                    self._drop_session_locked(key, session)
            self._drop_dead_shared_context_locked(self._context_key())
        return {
            "ready": True,
            "connected": bool(self._sessions),
            "profile_configured": bool(self.settings.user_data_dir),
            "mode": "direct-sdk",
            "sessions": len(self._sessions),
            "errors": [self._last_runtime_error] if self._last_runtime_error else [],
        }

    def _session_is_live(self, session: BrowserSession) -> bool:
        return self._page_is_live(session.page) and self._context_is_live(session.context)

    def _shared_context_is_live(self, shared: SharedBrowserContext) -> bool:
        if shared.context is None or shared.creating or shared.closing:
            return False
        return self._context_is_live(shared.context)

    def _context_is_live(self, context: Any) -> bool:
        if context is None:
            return False
        is_closed = getattr(context, "is_closed", None)
        if callable(is_closed):
            try:
                if bool(is_closed()):
                    return False
            except Exception:
                return False
        for attr in ("closed", "closed_flag"):
            value = getattr(context, attr, None)
            if isinstance(value, bool) and value:
                return False
        browser = getattr(context, "browser", None)
        if browser is not None and not self._browser_is_live(browser):
            return False
        return True

    def _browser_is_live(self, browser: Any) -> bool:
        is_connected = getattr(browser, "is_connected", None)
        if callable(is_connected):
            try:
                return bool(is_connected())
            except Exception:
                return False
        is_closed = getattr(browser, "is_closed", None)
        if callable(is_closed):
            try:
                return not bool(is_closed())
            except Exception:
                return False
        return True

    def _page_is_live(self, page: Any) -> bool:
        if page is None:
            return False
        is_closed = getattr(page, "is_closed", None)
        if callable(is_closed):
            try:
                return not bool(is_closed())
            except Exception:
                return False
        for attr in ("closed", "closed_flag"):
            value = getattr(page, attr, None)
            if isinstance(value, bool):
                return not value
        return True

    def _is_closed_target_error(self, exc: BaseException) -> bool:
        message = str(exc).strip().lower()
        return message == "target page, context or browser has been closed" or message.endswith(
            ": target page, context or browser has been closed"
        )

    def _drop_session_locked(self, key: str, session: BrowserSession | None = None) -> None:
        current = self._sessions.get(key)
        if current is None:
            return
        if session is not None and current is not session:
            return
        self._sessions.pop(key, None)

    def _drop_dead_shared_context_locked(
        self, context_key: str, shared: SharedBrowserContext | None = None
    ) -> None:
        shared = shared or self._contexts.get(context_key) or _CONTEXT_REGISTRY.get(context_key)
        if shared is None or shared.creating or shared.closing or self._shared_context_is_live(shared):
            return
        owner = shared.owner
        shared.owner = None
        self._contexts.pop(context_key, None)
        if _CONTEXT_REGISTRY.get(context_key) is shared:
            _CONTEXT_REGISTRY.pop(context_key, None)
        if owner is not None:
            owner.close()

    def _drop_shared_context_for_context_locked(
        self,
        context_key: str,
        *,
        context: Any,
        shared: SharedBrowserContext | None = None,
    ) -> None:
        candidate = shared or self._contexts.get(context_key) or _CONTEXT_REGISTRY.get(context_key)
        if candidate is None or candidate.context is not context:
            return
        owner = candidate.owner
        candidate.owner = None
        self._contexts.pop(context_key, None)
        if _CONTEXT_REGISTRY.get(context_key) is candidate:
            _CONTEXT_REGISTRY.pop(context_key, None)
        if owner is not None:
            owner.close()
