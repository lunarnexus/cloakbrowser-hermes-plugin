from __future__ import annotations

import logging
from typing import Any

try:
    from . import config, preflight
    from .commands import handle_slash
    from .schemas import BROWSER_TOOL_NAMES, schema_for
    from .session_manager import SessionManager
    from .tool_handlers import BrowserTools
except (
    ImportError
):  # pytest may import this standalone plugin root as a bare __init__ module.
    import config  # type: ignore[no-redef]
    import preflight  # type: ignore[no-redef]
    from commands import handle_slash  # type: ignore[no-redef]
    from schemas import BROWSER_TOOL_NAMES, schema_for  # type: ignore[no-redef]
    from session_manager import SessionManager  # type: ignore[no-redef]
    from tool_handlers import BrowserTools  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


def register(ctx: Any) -> None:
    config_result = config.load_config(ctx)
    preflight_result = preflight.check(config_result)
    manager = SessionManager(config_result.settings) if preflight_result.ok else None

    ctx.register_command(
        "cloak",
        handler=lambda raw_args: handle_slash(
            raw_args, config_result, preflight_result, manager
        ),
        description="Show CloakBrowser plugin status/help.",
        args_hint="status | help",
    )

    if not preflight_result.ok:
        logger.warning(
            "cloakbrowser-hermes-plugin preflight failed: %s",
            "; ".join(preflight_result.errors),
        )
        return

    assert manager is not None
    browser_tools = BrowserTools(manager)

    for name in BROWSER_TOOL_NAMES:
        ctx.register_tool(
            name=name,
            toolset="cloakbrowser-hermes-plugin",
            schema=schema_for(name),
            handler=lambda args, _name=name, **kw: browser_tools.handle(
                _name, args, **kw
            ),
            check_fn=lambda: preflight.check(config_result).ok,
            requires_env=[],
            emoji="🥷",
            override=True,
        )

    logger.info(
        "cloakbrowser-hermes-plugin registered direct-SDK browser_* foundations"
    )
