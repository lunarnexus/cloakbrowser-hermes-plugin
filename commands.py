from __future__ import annotations

import shlex

try:
    from .config import ConfigResult
    from .preflight import PreflightResult
    from .session_manager import SessionManager
except ImportError:
    from config import ConfigResult  # type: ignore[no-redef]
    from preflight import PreflightResult  # type: ignore[no-redef]
    from session_manager import SessionManager  # type: ignore[no-redef]


def handle_slash(
    raw_args: str,
    config: ConfigResult,
    preflight: PreflightResult,
    manager: SessionManager | None,
) -> str:
    try:
        argv = shlex.split(raw_args or "")
    except ValueError:
        return "Usage: /cloak [status|help]"
    sub = (argv[0] if argv else "status").lower()

    if sub in {"help", "--help", "-h"}:
        return "Usage: /cloak [status|help]"
    if sub not in {"status", "stats"}:
        return "Usage: /cloak [status|help]"

    lines = [
        "CloakBrowser status:",
        f"ready: {preflight.ok}",
        f"profile_configured: {bool(config.settings.user_data_dir)}",
    ]
    if manager is not None:
        status = manager.status()
        lines.extend([f"connected: {status['connected']}", f"mode: {status['mode']}"])
        runtime_errors = status.get("errors")
        if isinstance(runtime_errors, list) and runtime_errors:
            lines.append("errors: " + "; ".join(str(item) for item in runtime_errors))
    if preflight.errors:
        lines.append("errors: " + "; ".join(preflight.errors))
    if preflight.warnings:
        lines.append("warnings: " + "; ".join(preflight.warnings))
    return "\n".join(lines)
