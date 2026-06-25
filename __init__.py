from __future__ import annotations

import json
import logging
import shlex
import threading
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home
from tools.browser_tool import _BROWSER_SCHEMA_MAP

logger = logging.getLogger(__name__)

_PROFILE_DIR = str(get_hermes_home() / "browser-profiles" / "cloakbrowser")
_STATE_LOCK = threading.RLock()
_STATE: dict[str, Any] = {
    "connected": False,
    "page_id": None,
    "profile_dir": _PROFILE_DIR,
}


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _parse_tool_result(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except Exception:
        return {"error": f"Unexpected non-JSON tool result: {raw[:300]}"}

    if isinstance(parsed, dict) and "error" in parsed:
        return {"error": parsed.get("error")}

    if isinstance(parsed, dict) and isinstance(parsed.get("structuredContent"), dict):
        return parsed["structuredContent"]

    result = parsed.get("result") if isinstance(parsed, dict) else parsed
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            nested = json.loads(result)
            if isinstance(nested, dict):
                return nested
        except Exception:
            return {"result": result}
    return {"result": result}


def _dispatch(ctx, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    return _parse_tool_result(ctx.dispatch_tool(tool_name, args))


def _tool_available(ctx, tool_name: str) -> bool:
    from tools.registry import registry

    return tool_name in getattr(registry, "_tools", {})


def _require_mcp(ctx) -> None:
    needed = [
        "mcp_cloakbrowser_browser_launch",
        "mcp_cloakbrowser_browser_close",
        "mcp_cloakbrowser_browser_list_pages",
        "mcp_cloakbrowser_browser_navigate",
        "mcp_cloakbrowser_browser_snapshot",
    ]
    missing = [name for name in needed if not _tool_available(ctx, name)]
    if missing:
        raise RuntimeError(
            "CloakBrowser MCP tools are unavailable. Configure the 'cloakbrowser' MCP server and reload MCP. "
            f"Missing: {', '.join(missing)}"
        )


def _remember(page_id: str | None, connected: bool = True) -> None:
    with _STATE_LOCK:
        _STATE["connected"] = connected
        _STATE["page_id"] = page_id


def _clear_state() -> None:
    _remember(None, connected=False)


def _launch(ctx) -> dict[str, Any]:
    _require_mcp(ctx)
    Path(_PROFILE_DIR).mkdir(parents=True, exist_ok=True)
    launched = _dispatch(
        ctx,
        "mcp_cloakbrowser_browser_launch",
        {
            "headless": False,
            "humanize": True,
            "stealth_args": True,
            "user_data_dir": _PROFILE_DIR,
        },
    )
    if launched.get("error"):
        raise RuntimeError(str(launched["error"]))
    page_id = launched.get("page_id")
    if not page_id:
        raise RuntimeError(f"Launch succeeded but returned no page_id: {launched}")
    _remember(page_id, connected=True)
    return launched


def _list_pages(ctx) -> dict[str, Any]:
    _require_mcp(ctx)
    return _dispatch(ctx, "mcp_cloakbrowser_browser_list_pages", {})


def _ensure_page(ctx) -> str:
    with _STATE_LOCK:
        page_id = _STATE.get("page_id")
        connected = bool(_STATE.get("connected"))

    pages = _list_pages(ctx)
    if pages.get("error"):
        launched = _launch(ctx)
        return str(launched["page_id"])

    page_rows = pages.get("pages") or pages.get("result") or []
    if page_id and any(isinstance(p, dict) and p.get("page_id") == page_id for p in page_rows):
        return str(page_id)

    if page_rows:
        adopted = page_rows[0].get("page_id") if isinstance(page_rows[0], dict) else None
        if adopted:
            _remember(str(adopted), connected=True)
            return str(adopted)

    if connected:
        _clear_state()
    launched = _launch(ctx)
    return str(launched["page_id"])


def _close(ctx) -> dict[str, Any]:
    _require_mcp(ctx)
    result = _dispatch(ctx, "mcp_cloakbrowser_browser_close", {})
    _clear_state()
    return result


def _recoverable_error(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.lower()
    needles = [
        "page",
        "closed",
        "browser session lost",
        "browser is not running",
        "not found",
        "disconnected",
        "closedresourceerror",
    ]
    return any(n in lowered for n in needles)


def _call_page_tool(ctx, tool_name: str, payload: dict[str, Any], *, retry_once: bool = True) -> dict[str, Any]:
    page_id = _ensure_page(ctx)
    result = _dispatch(ctx, tool_name, {"page_id": page_id, **payload})
    if retry_once and result.get("error") and _recoverable_error(str(result.get("error"))):
        _clear_state()
        page_id = _ensure_page(ctx)
        result = _dispatch(ctx, tool_name, {"page_id": page_id, **payload})
    return result


def _handle_browser_navigate(ctx, args: dict[str, Any], **_kw) -> str:
    result = _call_page_tool(
        ctx,
        "mcp_cloakbrowser_browser_navigate",
        {"url": args.get("url", ""), "timeout": 60000},
    )
    return _json(result)


def _handle_browser_snapshot(ctx, args: dict[str, Any], **_kw) -> str:
    result = _call_page_tool(
        ctx,
        "mcp_cloakbrowser_browser_snapshot",
        {"full": bool(args.get("full", False)), "max_length": 12000},
    )
    return _json(result)


def _handle_browser_click(ctx, args: dict[str, Any], **_kw) -> str:
    return _json(_call_page_tool(ctx, "mcp_cloakbrowser_browser_click", {"ref": args.get("ref", "")}))


def _handle_browser_type(ctx, args: dict[str, Any], **_kw) -> str:
    return _json(
        _call_page_tool(
            ctx,
            "mcp_cloakbrowser_browser_type",
            {"ref": args.get("ref", ""), "text": args.get("text", "")},
        )
    )


def _handle_browser_scroll(ctx, args: dict[str, Any], **_kw) -> str:
    return _json(
        _call_page_tool(
            ctx,
            "mcp_cloakbrowser_browser_scroll",
            {"direction": args.get("direction", "down"), "amount": 500},
        )
    )


def _handle_browser_back(ctx, _args: dict[str, Any], **_kw) -> str:
    return _json(_call_page_tool(ctx, "mcp_cloakbrowser_browser_back", {}))


def _handle_browser_press(ctx, args: dict[str, Any], **_kw) -> str:
    return _json(
        _call_page_tool(
            ctx,
            "mcp_cloakbrowser_browser_press_key",
            {"key": args.get("key", "")},
        )
    )


def _handle_browser_get_images(ctx, _args: dict[str, Any], **_kw) -> str:
    return _json(_call_page_tool(ctx, "mcp_cloakbrowser_browser_get_images", {}))


def _handle_browser_console(ctx, args: dict[str, Any], **_kw) -> str:
    expression = args.get("expression")
    if expression:
        return _json(_call_page_tool(ctx, "mcp_cloakbrowser_browser_evaluate", {"expression": expression}))
    return _json(
        _call_page_tool(
            ctx,
            "mcp_cloakbrowser_browser_console",
            {"clear": bool(args.get("clear", False))},
        )
    )


def _status(ctx) -> str:
    try:
        pages = _list_pages(ctx)
    except Exception as exc:
        with _STATE_LOCK:
            page_id = _STATE.get("page_id")
        return (
            "CloakBrowser status: MCP unavailable or disconnected\n"
            f"profile_dir: {_PROFILE_DIR}\n"
            f"remembered_page_id: {page_id}\n"
            f"error: {exc}"
        )

    with _STATE_LOCK:
        page_id = _STATE.get("page_id")
        connected = _STATE.get("connected")

    page_rows = pages.get("pages") or []
    return (
        "CloakBrowser status:\n"
        f"connected_flag: {connected}\n"
        f"profile_dir: {_PROFILE_DIR}\n"
        f"remembered_page_id: {page_id}\n"
        f"open_pages: {len(page_rows)}\n"
        "mode: browser_* tools auto-launch headed CloakBrowser when needed"
    )


def _handle_slash(ctx, raw_args: str) -> str:
    argv = shlex.split(raw_args or "")
    sub = (argv[0] if argv else "status").lower()

    if sub in {"status", "stats"}:
        return _status(ctx)
    if sub == "connect":
        launched = _launch(ctx)
        return (
            "CloakBrowser connected\n"
            f"page_id: {launched.get('page_id')}\n"
            f"profile_dir: {_PROFILE_DIR}"
        )
    if sub == "disconnect":
        closed = _close(ctx)
        if closed.get("error"):
            return f"CloakBrowser disconnect failed: {closed['error']}"
        return "CloakBrowser disconnected. Next browser_* call will auto-launch it again."
    return "Usage: /cloak [status|connect|disconnect]"


def register(ctx) -> None:
    def wrap(fn):
        return lambda args, **kw: fn(ctx, args, **kw)

    ctx.register_command(
        "cloak",
        handler=lambda raw_args: _handle_slash(ctx, raw_args),
        description="Manage the default CloakBrowser-backed browser overrides.",
        args_hint="status | connect | disconnect",
    )

    override_names = [
        ("browser_navigate", _handle_browser_navigate),
        ("browser_snapshot", _handle_browser_snapshot),
        ("browser_click", _handle_browser_click),
        ("browser_type", _handle_browser_type),
        ("browser_scroll", _handle_browser_scroll),
        ("browser_back", _handle_browser_back),
        ("browser_press", _handle_browser_press),
        ("browser_get_images", _handle_browser_get_images),
        ("browser_console", _handle_browser_console),
    ]

    for name, handler in override_names:
        ctx.register_tool(
            name=name,
            toolset="cloakbrowser-hermes-plugin",
            schema=_BROWSER_SCHEMA_MAP[name],
            handler=wrap(handler),
            emoji="🥷",
            override=True,
        )

    logger.info("cloakbrowser-hermes-plugin registered browser_* overrides")
