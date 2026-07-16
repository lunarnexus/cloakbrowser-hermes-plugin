from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, field
from importlib import metadata

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
MINIMUM_SDK_VERSION = (0, 4, 10)


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


def sdk_version() -> tuple[int, ...] | None:
    try:
        raw = metadata.version("cloakbrowser")
    except metadata.PackageNotFoundError:
        return None
    match = re.match(r"^(\d+(?:\.\d+)*)", raw)
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def check(config_result: ConfigResult) -> PreflightResult:
    errors = list(config_result.errors)
    warnings = list(config_result.warnings)
    if not config_result.valid:
        return PreflightResult(False, errors, warnings)
    if not sdk_available():
        errors.append("cloakbrowser SDK is not importable")
    else:
        version = sdk_version()
        if version is not None and version < MINIMUM_SDK_VERSION:
            required = ".".join(str(part) for part in MINIMUM_SDK_VERSION)
            installed = ".".join(str(part) for part in version)
            errors.append(
                f"cloakbrowser SDK {installed} is too old; install cloakbrowser>={required} "
                "for correct humanized iframe interactions"
            )
    return PreflightResult(not errors, errors, warnings)
