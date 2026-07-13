from __future__ import annotations

import asyncio
import importlib
import inspect
import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from .config import CloakConfig
except ImportError:
    from config import CloakConfig  # type: ignore[no-redef]

SENSITIVE_QUERY_KEYS = re.compile(
    r"(token|secret|key|password|passwd|pwd|auth|session|cookie|credential|code)", re.I
)
SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.I),
    re.compile(r"([?&](?:access_)?token=)[^\s&#]+", re.I),
    re.compile(
        r"([?&](?:api[_-]?key|secret|password|passwd|pwd|session|cookie|code)=)[^\s&#]+",
        re.I,
    ),
    re.compile(
        r"\b((?:(?:access_)?token|api[_-]?key|secret|password|passwd|pwd|session|cookie|code)=)[^\s&#]+",
        re.I,
    ),
    re.compile(r"\b[A-Za-z0-9._%+-]+:[^\s/@]+@"),
]
BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal"}
METADATA_IPS = {"169.254.169.254", "169.254.170.2"}
MAX_REDACTED_TEXT = 20000


class CloakBrowserAdapter:
    """Direct-SDK boundary around CloakBrowser/Playwright-like APIs with Hermes parity guards."""

    def __init__(self, settings: CloakConfig, manager: Any | None = None):
        self.settings = settings
        self.manager = manager

    def run(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(value)
            raise RuntimeError(
                "async CloakBrowser SDK calls are not supported inside an already-running event loop"
            ) from None
        return value

    def create_context(self) -> Any:
        sdk = importlib.import_module("cloakbrowser")
        options = self.settings.to_sdk_options()
        for name in ("create", "launch_persistent_context"):
            factory = getattr(sdk, name, None)
            if callable(factory):
                return self.run(factory(**options))
        launch = getattr(sdk, "launch", None)
        if callable(launch):
            launch_options = {
                key: value for key, value in options.items() if key != "user_data_dir"
            }
            return self.run(launch(**launch_options))
        browser_cls = getattr(sdk, "CloakBrowser", None) or getattr(
            sdk, "Browser", None
        )
        if browser_cls is not None:
            instance = self.run(browser_cls(**options))
            for method in (
                "launch_persistent_context",
                "new_context",
                "context",
                "start",
            ):
                member = getattr(instance, method, None)
                if callable(member):
                    return self.run(member())
            return instance
        raise RuntimeError("cloakbrowser SDK has no supported browser/context factory")

    def call(
        self, tool_name: str, args: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        if self.manager is None:
            return {"error": "adapter has no session manager", "tool": tool_name}
        try:
            page = self.manager.page_for(
                task_id=kwargs.get("task_id"), session_id=kwargs.get("session_id")
            )
            handlers = {
                "browser_navigate": self._navigate,
                "browser_snapshot": self._snapshot,
                "browser_click": self._click,
                "browser_type": self._type,
                "browser_scroll": self._scroll,
                "browser_back": self._back,
                "browser_press": self._press,
                "browser_console": self._console,
                "browser_get_images": self._get_images,
            }
            handler = handlers.get(tool_name)
            if handler is None:
                return {"error": "unsupported browser tool", "tool": tool_name}
            return self._redact_value(handler(page, args or {}))
        except Exception as exc:
            return {"error": self._redact_text(str(exc), limit=1000), "tool": tool_name}

    def _navigate(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        url = args.get("url")
        if not url:
            raise ValueError("url is required")
        self._assert_safe_url(str(url))
        response = self.run(
            page.goto(str(url), wait_until=args.get("wait_until", "load"))
        )
        current_url = getattr(page, "url", str(url))
        self._assert_safe_page_url(current_url)
        self._clear_ref_map(page)
        return {
            "url": current_url,
            "status": getattr(response, "status", None),
            "ok": getattr(response, "ok", None),
        }

    def _snapshot(self, page: Any, _args: dict[str, Any]) -> dict[str, Any]:
        self._assert_safe_page_url(getattr(page, "url", None))
        accessibility = getattr(page, "accessibility", None)
        snapshot_method = getattr(accessibility, "snapshot", None)
        source = "accessibility"
        if callable(snapshot_method):
            snapshot = self.run(snapshot_method())
        else:
            source = "dom-text-fallback"
            snapshot = self.run(
                page.evaluate("() => document.body ? document.body.innerText : ''")
            )
        self._assert_safe_page_url(getattr(page, "url", None))
        ref_map: dict[str, Any] = {}
        text = self._snapshot_text(snapshot, ref_map=ref_map)
        setattr(page, "_cloak_ref_map", ref_map)
        return {
            "snapshot": text,
            "source": source,
            "url": getattr(page, "url", None),
            "refs": sorted(ref_map),
        }

    def _snapshot_text(
        self, snapshot: Any, indent: int = 0, ref_map: dict[str, Any] | None = None
    ) -> str:
        if isinstance(snapshot, str):
            return snapshot
        if isinstance(snapshot, dict):
            label = " ".join(
                str(snapshot.get(key, ""))
                for key in ("role", "name")
                if snapshot.get(key)
            ).strip()
            ref = None
            target = self._target_from_snapshot_node(snapshot)
            if ref_map is not None and target is not None:
                ref = f"@e{len(ref_map) + 1}"
                ref_map[ref] = target
            prefix = f"[{ref}] " if ref else ""
            lines = [("  " * indent) + prefix + label] if label else []
            for child in snapshot.get("children", []) or []:
                text = self._snapshot_text(child, indent + 1, ref_map)
                if text:
                    lines.append(text)
            return "\n".join(lines)
        return json.dumps(snapshot, ensure_ascii=False)

    def _click(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        locator = self._locator(page, self._selector(args))
        self.run(locator.click())
        return {"clicked": True}

    def _type(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        locator = self._locator(page, self._selector(args))
        text = str(args.get("text", ""))
        fill = getattr(locator, "fill", None)
        if callable(fill):
            self.run(fill(text))
        else:
            self.run(locator.type(text))
        return {"typed": True}

    def _scroll(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        direction = str(args.get("direction", "down")).lower()
        amount = int(args.get("amount", 700))
        dy = -amount if direction == "up" else amount
        self.run(page.mouse.wheel(0, dy))
        return {"scrolled": direction, "amount": amount}

    def _back(self, page: Any, _args: dict[str, Any]) -> dict[str, Any]:
        response = self.run(page.go_back())
        self._assert_safe_page_url(getattr(page, "url", None))
        self._clear_ref_map(page)
        return {
            "url": getattr(page, "url", None),
            "status": getattr(response, "status", None),
            "ok": getattr(response, "ok", None),
        }

    def _press(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        key = args.get("key")
        if not key:
            raise ValueError("key is required")
        self.run(page.keyboard.press(key))
        return {"pressed": key}

    def _console(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        self._assert_safe_page_url(getattr(page, "url", None))
        result: dict[str, Any] = {}
        if "expression" in args and args.get("expression") is not None:
            expression = str(args.get("expression"))
            if len(expression) > 4000:
                raise ValueError("expression is too long")
            result["result"] = self.run(page.evaluate(expression))
            self._assert_safe_page_url(getattr(page, "url", None))
        messages = getattr(page, "_cloak_console_messages", None)
        if messages is None or (
            not list(messages) and hasattr(page, "console_messages")
        ):
            messages = getattr(page, "console_messages", [])
        result["messages"] = list(messages)[-200:]
        if args.get("clear") and hasattr(messages, "clear"):
            messages.clear()
        return result

    def _get_images(self, page: Any, _args: dict[str, Any]) -> dict[str, Any]:
        self._assert_safe_page_url(getattr(page, "url", None))
        images = self.run(
            page.evaluate(
                "() => Array.from(document.images).map(img => ({"
                "src: img.currentSrc || img.src || '', alt: img.alt || '', "
                "width: img.naturalWidth || img.width || 0, height: img.naturalHeight || img.height || 0}))"
            )
        )
        self._assert_safe_page_url(getattr(page, "url", None))
        safe_images = []
        for image in images or []:
            src = str(image.get("src", "")) if isinstance(image, dict) else ""
            if not self._is_returnable_url(src):
                continue
            safe_images.append(image)
        return {"images": safe_images}

    def _selector(self, args: dict[str, Any]) -> str:
        selector = args.get("selector") or args.get("ref")
        if not selector:
            raise ValueError("selector or ref is required")
        return str(selector)

    def _locator(self, page: Any, selector_or_ref: str) -> Any:
        target = selector_or_ref
        if selector_or_ref.startswith("@e"):
            ref_map = getattr(page, "_cloak_ref_map", {}) or {}
            if selector_or_ref not in ref_map:
                raise ValueError(f"unknown browser ref: {selector_or_ref}")
            target = ref_map[selector_or_ref]
            if hasattr(target, "click") or hasattr(target, "fill"):
                return target
        locator = getattr(page, "locator", None)
        if callable(locator):
            return locator(str(target))
        query_selector = getattr(page, "query_selector", None)
        if callable(query_selector):
            element = self.run(query_selector(str(target)))
            if element is not None:
                return element
        raise ValueError(
            f"element not found: {self._redact_text(str(selector_or_ref), limit=200)}"
        )

    def _target_from_snapshot_node(self, node: dict[str, Any]) -> Any | None:
        for key in ("element", "handle", "selector", "ref"):
            value = node.get(key)
            if value:
                return value
        role = node.get("role")
        name = node.get("name")
        if role and name:
            safe_name = str(name).replace('"', '\\"')
            return f'internal:role={role}[name="{safe_name}"]'
        return None

    def _clear_ref_map(self, page: Any) -> None:
        setattr(page, "_cloak_ref_map", {})

    def _assert_safe_page_url(self, url: Any) -> None:
        if url:
            self._assert_safe_url(str(url), for_navigation=False)

    def _assert_safe_url(self, url: str, *, for_navigation: bool = True) -> None:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme in {"about"} and url == "about:blank":
            return
        if scheme in {"data", "blob", "file", "ftp", "javascript"}:
            raise ValueError("blocked unsafe browser URL scheme")
        if scheme not in {"http", "https"}:
            if for_navigation:
                raise ValueError("blocked unsupported browser URL scheme")
            return
        if parts.username or parts.password:
            raise ValueError("blocked URL with embedded credentials")
        host = (parts.hostname or "").strip().lower().rstrip(".")
        if not host:
            raise ValueError("blocked URL without host")
        if host in BLOCKED_HOSTS:
            raise ValueError("blocked private or metadata browser URL")
        ips = self._resolve_host_ips(host)
        if host in METADATA_IPS or any(self._is_blocked_ip(ip) for ip in ips):
            raise ValueError("blocked private or metadata browser URL")

    def _resolve_host_ips(self, host: str) -> list[Any]:
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            pass
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError:
            return []
        ips = []
        for info in infos:
            try:
                ips.append(ipaddress.ip_address(info[4][0]))
            except (ValueError, IndexError):
                continue
        return ips

    def _is_blocked_ip(self, ip: Any) -> bool:
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )

    def _is_returnable_url(self, url: str) -> bool:
        if not url:
            return False
        try:
            self._assert_safe_url(url, for_navigation=False)
        except ValueError:
            return False
        return urlsplit(url).scheme.lower() in {"http", "https"}

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact_text(value)
        if isinstance(value, list):
            return [self._redact_value(item) for item in value][-500:]
        if isinstance(value, tuple):
            return [self._redact_value(item) for item in value][-500:]
        if isinstance(value, dict):
            return {str(key): self._redact_value(item) for key, item in value.items()}
        return value

    def _redact_text(self, text: str, *, limit: int = MAX_REDACTED_TEXT) -> str:
        redacted = text
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub(
                lambda m: (m.group(1) if m.groups() else "") + "[REDACTED]", redacted
            )
        redacted = self._redact_urls(redacted)
        if len(redacted) > limit:
            return redacted[:limit] + "…[truncated]"
        return redacted

    def _redact_urls(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            return self._redact_url(match.group(0))

        return re.sub(r"https?://[^\s'\"<>]+", repl, text)

    def _redact_url(self, url: str) -> str:
        parts = urlsplit(url)
        netloc = parts.hostname or ""
        if parts.port:
            netloc += f":{parts.port}"
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            query.append(
                (key, "[REDACTED]" if SENSITIVE_QUERY_KEYS.search(key) else value)
            )
        return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), ""))
