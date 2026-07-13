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
