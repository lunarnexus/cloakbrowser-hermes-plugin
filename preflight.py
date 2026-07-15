from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field

try:
    from .config import ConfigResult
except ImportError:
    from config import ConfigResult  # type: ignore[no-redef]


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


PERSISTENT_PROFILE_COLLISION_MESSAGE = (
    "persistent profile already in use by another Hermes process; "
    "same-profile sharing works only inside one Hermes process; "
    "close other Hermes/CloakBrowser sessions for this profile or use a different user_data_dir"
)


def detect_persistent_profile_collision(exc: BaseException) -> str | None:
    message = " ".join(str(part).strip() for part in exc.args if str(part).strip()) or str(exc).strip()
    lowered = message.lower()
    markers = (
        "processsingleton",
        "singletonlock",
        "profile already in use",
        "lock held by another process",
        "user data directory is already in use",
        "opening in existing browser session",
    )
    if any(marker in lowered for marker in markers):
        return PERSISTENT_PROFILE_COLLISION_MESSAGE
    return None


def sdk_available() -> bool:
    if "cloakbrowser" in sys.modules:
        return True
    try:
        return importlib.util.find_spec("cloakbrowser") is not None
    except (ImportError, ValueError):
        return False


def check(config_result: ConfigResult) -> PreflightResult:
    errors = list(config_result.errors)
    warnings = list(config_result.warnings)
    if not config_result.valid:
        return PreflightResult(False, errors, warnings)
    if not sdk_available():
        errors.append("cloakbrowser SDK is not importable")
    return PreflightResult(not errors, errors, warnings)
