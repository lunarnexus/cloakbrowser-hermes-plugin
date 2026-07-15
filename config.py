from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

PLUGIN_NAME = "cloakbrowser-hermes-plugin"
_VALID_PRESETS = {"default", "careful"}
_OPTIONAL_STRINGS = ("proxy", "locale", "timezone", "color_scheme", "user_agent")
_TRUE_STRINGS = {"1", "true", "yes", "on"}
_FALSE_STRINGS = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class CloakConfig:
    user_data_dir: str
    headless: bool = True
    humanize: bool = True
    human_preset: str = "default"
    stealth_args: bool = True
    geoip: bool = False
    args: list[str] = field(default_factory=list)
    fingerprint_seed: str | None = None
    proxy: str | None = None
    locale: str | None = None
    timezone: str | None = None
    color_scheme: str | None = None
    user_agent: str | None = None
    auto_acknowledge_banner: bool = True
    auto_update: bool | None = None

    def to_sdk_options(self) -> dict[str, Any]:
        args = list(self.args)
        if self.fingerprint_seed is not None and not any(
            arg.startswith("--fingerprint=") for arg in args
        ):
            args.append(f"--fingerprint={self.fingerprint_seed}")
        options: dict[str, Any] = {
            "user_data_dir": self.user_data_dir,
            "headless": self.headless,
            "humanize": self.humanize,
            "human_preset": self.human_preset,
            "stealth_args": self.stealth_args,
            "geoip": self.geoip,
            "args": args,
        }
        for key in _OPTIONAL_STRINGS:
            value = getattr(self, key)
            if value is not None:
                options[key] = value
        return options


@dataclass(frozen=True)
class ConfigResult:
    settings: CloakConfig
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _ctx_config(ctx: Any, errors: list[str]) -> dict[str, Any]:
    for attr in ("config", "plugin_config"):
        value = getattr(ctx, attr, None)
        if isinstance(value, dict):
            return value
    getter = getattr(ctx, "get_config", None)
    if callable(getter):
        value = getter()
        if isinstance(value, dict):
            return value
    try:
        load_hermes_config = import_module("hermes_cli.config").load_config
    except ModuleNotFoundError as exc:
        if exc.name == "hermes_cli" or exc.name == "hermes_cli.config":
            return {}
        errors.append(f"failed to import Hermes config loader: {exc}")
        return {}
    except Exception as exc:
        errors.append(f"failed to import Hermes config loader: {exc}")
        return {}

    try:
        value = load_hermes_config()
    except Exception as exc:
        errors.append(f"failed to load Hermes config: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append("Hermes config loader returned non-dict config")
        return {}
    return value


def _runtime_config(raw: dict[str, Any]) -> dict[str, Any]:
    entries = (
        raw.get("plugins", {}).get("entries", {})
        if isinstance(raw.get("plugins"), dict)
        else {}
    )
    entry = entries.get(PLUGIN_NAME, {}) if isinstance(entries, dict) else {}
    nested = entry.get("config") if isinstance(entry, dict) else None
    if isinstance(nested, dict):
        return nested
    return raw


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _parse_args(raw: Any, errors: list[str]) -> list[str]:
    if raw is None:
        return []

    value = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw.strip())
        except json.JSONDecodeError:
            errors.append(
                "args must be a list of strings; string values must decode to a JSON/YAML list of strings"
            )
            return []

    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        errors.append(
            "args must be a list of strings; string values must decode to a JSON/YAML list of strings"
        )
        return []

    return list(value)


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home()).expanduser().resolve()
    except Exception:
        return (Path.home() / ".hermes").resolve()


def _default_user_data_dir() -> str:
    return str((_hermes_home() / "browser-profiles" / "cloakbrowser").resolve())


def _parse_bool(raw: Any, default: bool, name: str, errors: list[str]) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
    errors.append(f"{name} must be a boolean")
    return default


def _parse_optional_bool(raw: Any, name: str, errors: list[str]) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
    errors.append(f"{name} must be a boolean or null")
    return None


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path.cwd()
    for part in path.parts[1:] if path.is_absolute() else path.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            return True
    return False


def _validate_user_data_dir(raw_value: Any, errors: list[str]) -> str:
    configured = raw_value not in (None, "")
    path = Path(str(raw_value or _default_user_data_dir())).expanduser()
    resolved = path.resolve()
    home = Path.home().resolve()
    hermes_home = _hermes_home()
    repo_root = Path(__file__).resolve().parent
    allowed_current_profile_roots = [
        (hermes_home / "browser-profiles" / "cloakbrowser").resolve(),
        (hermes_home / "plugins" / PLUGIN_NAME).resolve(),
    ]

    dangerous_exact = {Path(resolved.anchor).resolve(), home, repo_root}
    if resolved in dangerous_exact:
        errors.append(
            "user_data_dir must be a dedicated CloakBrowser profile directory, not root, home, or repo root"
        )

    if _has_symlink_component(path):
        errors.append("user_data_dir must not include symlink components")

    common_browser_roots = [
        home / ".config" / "google-chrome",
        home / ".config" / "chromium",
        home / ".mozilla" / "firefox",
        home / "Library" / "Application Support" / "Google" / "Chrome",
        home / "Library" / "Application Support" / "Chromium",
    ]
    if any(
        resolved == root.resolve() or _is_relative_to(resolved, root.resolve())
        for root in common_browser_roots
    ):
        errors.append(
            "user_data_dir must not point at an existing browser profile directory"
        )

    hermes_profiles = home / ".hermes" / "profiles"
    if _is_relative_to(resolved, hermes_profiles.resolve()) and not any(
        resolved == allowed or _is_relative_to(resolved, allowed)
        for allowed in allowed_current_profile_roots
    ):
        errors.append(
            "user_data_dir must not point at another Hermes profile directory"
        )

    if configured and resolved == hermes_home:
        errors.append("user_data_dir must not be the Hermes profile root")

    return str(resolved)


def load_config(ctx: Any) -> ConfigResult:
    errors: list[str] = []
    raw = _runtime_config(_ctx_config(ctx, errors))
    warnings: list[str] = []

    preset = str(raw.get("human_preset", "default"))
    if preset not in _VALID_PRESETS:
        errors.append("human_preset must be one of: careful, default")
        preset = "default"

    args = _parse_args(raw.get("args", []), errors)
    fingerprint_seed = _optional_string(raw.get("fingerprint_seed"))
    if fingerprint_seed and any(arg.startswith("--fingerprint=") for arg in args):
        warnings.append(
            "fingerprint_seed ignored because args already include --fingerprint=..."
        )
        fingerprint_seed = None

    optional_values = {key: _optional_string(raw.get(key)) for key in _OPTIONAL_STRINGS}
    geoip = _parse_bool(raw.get("geoip"), False, "geoip", errors)
    if geoip and not optional_values["proxy"]:
        warnings.append("geoip requires proxy; disabling geoip")
        geoip = False

    settings = CloakConfig(
        user_data_dir=_validate_user_data_dir(raw.get("user_data_dir"), errors),
        headless=_parse_bool(raw.get("headless"), True, "headless", errors),
        humanize=_parse_bool(raw.get("humanize"), True, "humanize", errors),
        human_preset=preset,
        stealth_args=_parse_bool(raw.get("stealth_args"), True, "stealth_args", errors),
        geoip=geoip,
        args=list(args),
        fingerprint_seed=fingerprint_seed,
        auto_acknowledge_banner=_parse_bool(
            raw.get("auto_acknowledge_banner"),
            True,
            "auto_acknowledge_banner",
            errors,
        ),
        auto_update=_parse_optional_bool(raw.get("auto_update"), "auto_update", errors),
        **optional_values,
    )
    return ConfigResult(
        settings=settings, valid=not errors, errors=errors, warnings=warnings
    )
