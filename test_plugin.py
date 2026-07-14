from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import types
from io import BytesIO
from pathlib import Path

import pytest


BROWSER_NAMES = [
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_scroll",
    "browser_back",
    "browser_press",
    "browser_get_images",
    "browser_console",
    "browser_dialog",
    "browser_vision",
]


class FakeCtx:
    def __init__(self, config=None):
        self.config = config
        self.registered_tools = []
        self.registered_commands = []

    def register_tool(self, **kwargs):
        self.registered_tools.append(kwargs)

    def register_command(self, name, handler, description="", args_hint=""):
        self.registered_commands.append(
            {
                "name": name,
                "handler": handler,
                "description": description,
                "args_hint": args_hint,
            }
        )


class RuntimeCtx:
    """Hermes-like plugin context: registration API, no preloaded config attrs."""

    def __init__(self):
        self.registered_tools = []
        self.registered_commands = []

    def register_tool(self, **kwargs):
        self.registered_tools.append(kwargs)

    def register_command(self, name, handler, description="", args_hint=""):
        self.registered_commands.append(
            {
                "name": name,
                "handler": handler,
                "description": description,
                "args_hint": args_hint,
            }
        )


def _install_hermes_config_loader(monkeypatch, runtime_config):
    hermes_cli = types.ModuleType("hermes_cli")
    hermes_config = types.ModuleType("hermes_cli.config")
    load_config = runtime_config if callable(runtime_config) else lambda: runtime_config
    setattr(hermes_config, "load_config", load_config)
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", hermes_config)


@pytest.fixture()
def plugin(monkeypatch, tmp_path):
    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)

    browser_tool = types.ModuleType("tools.browser_tool")
    setattr(
        browser_tool,
        "_BROWSER_SCHEMA_MAP",
        {
            name: {"name": name, "parameters": {"type": "object"}}
            for name in BROWSER_NAMES
        },
    )

    tools_pkg = types.ModuleType("tools")
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)
    monkeypatch.setitem(sys.modules, "tools", tools_pkg)
    monkeypatch.setitem(sys.modules, "tools.browser_tool", browser_tool)

    for name in list(sys.modules):
        if name == "cloakbrowser_hermes_plugin_under_test" or name.startswith(
            "cloakbrowser_hermes_plugin_under_test."
        ):
            monkeypatch.delitem(sys.modules, name, raising=False)

    spec = importlib.util.spec_from_file_location(
        "cloakbrowser_hermes_plugin_under_test",
        Path(__file__).with_name("__init__.py"),
        submodule_search_locations=[str(Path(__file__).parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_config_parses_plugin_entry_runtime_options(plugin, tmp_path):
    raw = {
        "plugins": {
            "entries": {
                "cloakbrowser-hermes-plugin": {
                    "allow_tool_override": True,
                    "config": {
                        "user_data_dir": str(tmp_path / "profile"),
                        "headless": False,
                        "humanize": False,
                        "human_preset": "careful",
                        "stealth_args": False,
                        "geoip": True,
                        "proxy": "",
                        "locale": None,
                        "timezone": "UTC",
                        "args": ["--disable-gpu"],
                        "auto_acknowledge_banner": False,
                        "auto_update": False,
                    },
                }
            }
        }
    }

    parsed = plugin.config.load_config(FakeCtx(raw))

    assert parsed.valid is True
    assert parsed.settings.user_data_dir == str((tmp_path / "profile").resolve())
    assert parsed.settings.headless is False
    assert parsed.settings.humanize is False
    assert parsed.settings.human_preset == "careful"
    assert parsed.settings.stealth_args is False
    assert parsed.settings.geoip is False
    assert parsed.settings.proxy is None
    assert parsed.settings.locale is None
    assert parsed.settings.timezone == "UTC"
    assert parsed.settings.args == ["--disable-gpu"]
    assert parsed.settings.auto_acknowledge_banner is False
    assert parsed.settings.auto_update is False
    assert "allow_tool_override" not in parsed.settings.to_sdk_options()
    assert "geoip requires proxy" in "; ".join(parsed.warnings)


def test_runtime_hermes_config_loader_exception_fails_closed(plugin, monkeypatch):
    def broken_loader():
        raise RuntimeError("boom")

    _install_hermes_config_loader(monkeypatch, broken_loader)

    parsed = plugin.config.load_config(RuntimeCtx())

    assert parsed.valid is False
    assert any("failed to load Hermes config: boom" in error for error in parsed.errors)


def test_runtime_hermes_config_loader_non_dict_fails_closed(plugin, monkeypatch):
    _install_hermes_config_loader(monkeypatch, ["not", "a", "dict"])

    parsed = plugin.config.load_config(RuntimeCtx())

    assert parsed.valid is False
    assert any("non-dict config" in error for error in parsed.errors)


def test_missing_hermes_config_loader_allows_standalone_defaults(plugin, monkeypatch):
    monkeypatch.delitem(sys.modules, "hermes_cli", raising=False)
    monkeypatch.delitem(sys.modules, "hermes_cli.config", raising=False)

    parsed = plugin.config.load_config(RuntimeCtx())

    assert parsed.valid is True
    assert parsed.errors == []


def test_invalid_human_preset_fails_clearly(plugin):
    ctx = FakeCtx({"human_preset": "fast"})

    parsed = plugin.config.load_config(ctx)

    assert parsed.valid is False
    assert any("human_preset" in error for error in parsed.errors)


def test_register_adds_only_readonly_command_when_sdk_missing(plugin, monkeypatch):
    monkeypatch.setattr(plugin.preflight, "sdk_available", lambda: False)
    ctx = FakeCtx({"user_data_dir": "/tmp/profile"})

    plugin.register(ctx)

    assert [command["name"] for command in ctx.registered_commands] == ["cloak"]
    assert ctx.registered_tools == []
    output = ctx.registered_commands[0]["handler"]("connect")
    assert "Usage: /cloak [status|help]" in output


def test_register_overrides_tools_when_sdk_and_config_valid(
    plugin, monkeypatch, tmp_path
):
    fake_sdk = types.ModuleType("cloakbrowser")
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    ctx = FakeCtx({"user_data_dir": str(tmp_path / "profile")})

    plugin.register(ctx)

    assert [command["name"] for command in ctx.registered_commands] == ["cloak"]
    assert [tool["name"] for tool in ctx.registered_tools] == BROWSER_NAMES
    assert all(tool["override"] is True for tool in ctx.registered_tools)
    assert all(tool["check_fn"]() is True for tool in ctx.registered_tools)
    assert ctx.registered_commands[0]["handler"]("status").startswith(
        "CloakBrowser status:"
    )


def test_registered_handlers_use_fake_sdk_without_real_browser(
    plugin, monkeypatch, tmp_path
):
    fake_sdk = types.ModuleType("cloakbrowser")
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    ctx = FakeCtx({"user_data_dir": str(tmp_path / "profile")})
    plugin.register(ctx)

    fake_sdk.create = lambda **options: FakeBrowserContext(**options)

    result = json.loads(
        ctx.registered_tools[0]["handler"](
            {"url": "about:blank"}, task_id="task-secret"
        )
    )

    assert result["url"] == "about:blank"
    assert "task-secret" not in json.dumps(result)


def _install_fake_cloakbrowser(monkeypatch, cache_dir, create):
    fake_sdk = types.ModuleType("cloakbrowser")
    setattr(fake_sdk, "create", create)
    fake_download = types.ModuleType("cloakbrowser.download")
    setattr(fake_download, "get_cache_dir", lambda: str(cache_dir))
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    monkeypatch.setitem(sys.modules, "cloakbrowser.download", fake_download)
    return fake_sdk


def test_sdk_banner_marker_written_when_enabled(plugin, monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    _install_fake_cloakbrowser(
        monkeypatch,
        cache_dir,
        lambda **options: FakeBrowserContext(**options),
    )
    ctx = FakeCtx({"user_data_dir": str(tmp_path / "profile")})
    plugin.register(ctx)

    result = json.loads(
        ctx.registered_tools[0]["handler"]({"url": "about:blank"}, task_id="banner-on")
    )

    marker = cache_dir / ".welcome_shown"
    assert result["url"] == "about:blank"
    assert marker.exists()
    assert int(marker.read_text()) <= int(time.time())


def test_sdk_banner_marker_not_written_when_disabled(plugin, monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    _install_fake_cloakbrowser(
        monkeypatch,
        cache_dir,
        lambda **options: FakeBrowserContext(**options),
    )
    ctx = FakeCtx(
        {
            "plugins": {
                "entries": {
                    "cloakbrowser-hermes-plugin": {
                        "config": {
                            "user_data_dir": str(tmp_path / "profile"),
                            "auto_acknowledge_banner": False,
                        }
                    }
                }
            }
        }
    )
    plugin.register(ctx)

    result = json.loads(
        ctx.registered_tools[0]["handler"]({"url": "about:blank"}, task_id="banner-off")
    )

    assert result["url"] == "about:blank"
    assert not (cache_dir / ".welcome_shown").exists()


def test_sdk_banner_marker_write_failure_does_not_block_launch(plugin, monkeypatch, tmp_path):
    cache_path = tmp_path / "cache-is-file"
    cache_path.write_text("not a directory")
    _install_fake_cloakbrowser(
        monkeypatch,
        cache_path,
        lambda **options: FakeBrowserContext(**options),
    )
    ctx = FakeCtx({"user_data_dir": str(tmp_path / "profile")})
    plugin.register(ctx)

    result = json.loads(
        ctx.registered_tools[0]["handler"]({"url": "about:blank"}, task_id="banner-fail")
    )

    assert result["url"] == "about:blank"
    assert FakeBrowserContext.created[-1].options["user_data_dir"] == str(
        (tmp_path / "profile").resolve()
    )


def test_auto_update_false_sets_env_only_when_absent(plugin, monkeypatch, tmp_path):
    monkeypatch.delenv("CLOAKBROWSER_AUTO_UPDATE", raising=False)
    _install_fake_cloakbrowser(
        monkeypatch,
        tmp_path / "cache",
        lambda **options: FakeBrowserContext(**options),
    )
    ctx = FakeCtx(
        {
            "plugins": {
                "entries": {
                    "cloakbrowser-hermes-plugin": {
                        "config": {
                            "user_data_dir": str(tmp_path / "profile"),
                            "auto_update": False,
                        }
                    }
                }
            }
        }
    )
    plugin.register(ctx)

    result = json.loads(
        ctx.registered_tools[0]["handler"]({"url": "about:blank"}, task_id="auto-update-off")
    )

    assert result["url"] == "about:blank"
    assert os.environ["CLOAKBROWSER_AUTO_UPDATE"] == "false"


def test_auto_update_env_var_wins(plugin, monkeypatch, tmp_path):
    monkeypatch.setenv("CLOAKBROWSER_AUTO_UPDATE", "true")
    _install_fake_cloakbrowser(
        monkeypatch,
        tmp_path / "cache",
        lambda **options: FakeBrowserContext(**options),
    )
    ctx = FakeCtx(
        {
            "plugins": {
                "entries": {
                    "cloakbrowser-hermes-plugin": {
                        "config": {
                            "user_data_dir": str(tmp_path / "profile"),
                            "auto_update": False,
                        }
                    }
                }
            }
        }
    )
    plugin.register(ctx)

    result = json.loads(
        ctx.registered_tools[0]["handler"]({"url": "about:blank"}, task_id="auto-update-env")
    )

    assert result["url"] == "about:blank"
    assert os.environ["CLOAKBROWSER_AUTO_UPDATE"] == "true"


def test_auto_update_true_leaves_env_absent(plugin, monkeypatch, tmp_path):
    monkeypatch.delenv("CLOAKBROWSER_AUTO_UPDATE", raising=False)
    _install_fake_cloakbrowser(
        monkeypatch,
        tmp_path / "cache",
        lambda **options: FakeBrowserContext(**options),
    )
    ctx = FakeCtx(
        {
            "plugins": {
                "entries": {
                    "cloakbrowser-hermes-plugin": {
                        "config": {
                            "user_data_dir": str(tmp_path / "profile"),
                            "auto_update": True,
                        }
                    }
                }
            }
        }
    )
    plugin.register(ctx)

    result = json.loads(
        ctx.registered_tools[0]["handler"]({"url": "about:blank"}, task_id="auto-update-on")
    )

    assert result["url"] == "about:blank"
    assert "CLOAKBROWSER_AUTO_UPDATE" not in os.environ


def test_auto_update_string_values_parse_as_optional_bool(plugin, tmp_path):
    true_result = plugin.config.load_config(
        FakeCtx({"user_data_dir": str(tmp_path / "profile-true"), "auto_update": "yes"})
    )
    false_result = plugin.config.load_config(
        FakeCtx({"user_data_dir": str(tmp_path / "profile-false"), "auto_update": "off"})
    )

    assert true_result.valid is True
    assert true_result.settings.auto_update is True
    assert false_result.valid is True
    assert false_result.settings.auto_update is False


def test_invalid_auto_update_value_fails_config_and_blocks_tool_override(plugin, monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "cloakbrowser", types.ModuleType("cloakbrowser"))
    ctx = FakeCtx({"user_data_dir": str(tmp_path / "profile"), "auto_update": "sometimes"})

    parsed = plugin.config.load_config(ctx)
    plugin.register(ctx)

    assert parsed.valid is False
    assert parsed.settings.auto_update is None
    assert parsed.errors == ["auto_update must be a boolean or null"]
    assert [command["name"] for command in ctx.registered_commands] == ["cloak"]
    assert ctx.registered_tools == []
    assert "auto_update must be a boolean or null" in ctx.registered_commands[0]["handler"]("status")


def test_sdk_startup_stderr_not_swallowed_on_failure(plugin, monkeypatch, tmp_path, capsys):
    def create(**_options):
        print("useful SDK failure detail", file=sys.stderr)
        raise RuntimeError("launch failed")

    _install_fake_cloakbrowser(monkeypatch, tmp_path / "cache", create)
    ctx = FakeCtx({"user_data_dir": str(tmp_path / "profile")})
    plugin.register(ctx)

    result = json.loads(
        ctx.registered_tools[0]["handler"]({"url": "about:blank"}, task_id="fail")
    )

    captured = capsys.readouterr()
    assert result["error"] == "launch failed"
    assert "useful SDK failure detail" in captured.err


class FakeElement:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def click(self):
        self.page.events.append(("click", self.selector))

    def fill(self, text):
        self.page.events.append(("fill", self.selector, text))


class FakeMouse:
    def __init__(self, page):
        self.page = page

    def wheel(self, x, y):
        self.page.events.append(("wheel", x, y))


class FakeKeyboard:
    def __init__(self, page):
        self.page = page

    def press(self, key):
        self.page.events.append(("press", key))


class FakeAccessibility:
    def __init__(self, page):
        self.page = page

    def snapshot(self):
        return {
            "role": "WebArea",
            "name": "Fake page",
            "children": [{"role": "button", "name": "Go", "selector": "#go"}],
        }


class FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.title_value = "Fake"
        self.events = []
        self.mouse = FakeMouse(self)
        self.keyboard = FakeKeyboard(self)
        self.accessibility = FakeAccessibility(self)
        self.console_messages = [{"type": "log", "text": "hello"}]
        self.images = [
            {
                "src": "https://example.test/a.png?token=secret",
                "alt": "A",
                "width": 10,
                "height": 20,
            },
            {"src": "data:image/png;base64,redacted", "alt": "inline"},
            {"src": "blob:https://example.test/id", "alt": "blob"},
            {"src": "http://127.0.0.1/a.png", "alt": "private"},
        ]
        self.listeners = {}
        self.screenshots = []
        self.evaluate_scripts = []
        self.dom_fallback_elements = [
            {"ref": "@e1", "selector": "#dom-go", "text": "DOM Go", "role": "button"},
            {"ref": "@e2", "selector": "#dom-input", "text": "", "role": "input"},
        ]

    def on(self, event, handler):
        self.listeners.setdefault(event, []).append(handler)

    def emit(self, event, payload):
        for handler in self.listeners.get(event, []):
            handler(payload)

    def screenshot(self, **kwargs):
        self.screenshots.append(kwargs)
        path = kwargs.get("path")
        from PIL import Image

        image = Image.new("RGB", (100, 100), "white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        data = buffer.getvalue()
        if path:
            Path(path).write_bytes(data)
        return data

    def goto(self, url, wait_until="load"):
        self.url = url
        self.events.append(("goto", url, wait_until))
        return types.SimpleNamespace(status=204, ok=True)

    def title(self):
        return self.title_value

    def locator(self, selector):
        return FakeElement(self, selector)

    def query_selector(self, selector):
        return FakeElement(self, selector)

    def go_back(self):
        self.events.append(("back",))
        self.url = "about:previous"
        return types.SimpleNamespace(status=200, ok=True)

    def evaluate(self, script, *args):
        self.evaluate_scripts.append(script)
        if args and "getBoundingClientRect" in script:
            selectors = args[0]
            boxes = {
                "#go": {"x": 12, "y": 18, "width": 44, "height": 24},
                'internal:role=WebArea[name="Fake page"]': {"x": 0, "y": 0, "width": 100, "height": 100},
                'internal:role=button[name="Go"]': {"x": 12, "y": 18, "width": 44, "height": 24},
                "#dom-go": {"x": 8, "y": 10, "width": 50, "height": 20, "text": "DOM Go", "role": "button", "selector": "#dom-go"},
                "#dom-input": {"x": 8, "y": 40, "width": 70, "height": 20, "text": "", "role": "input", "selector": "#dom-input"},
                "#unique-button": {"x": 8, "y": 10, "width": 50, "height": 20, "text": "Unique", "role": "button", "selector": "#unique-button"},
            }
            return [boxes.get(selector) for selector in selectors]
        if "uniqueSelectorFor" in script:
            return self.dom_fallback_elements
        if "document.body.innerText" in script:
            return "Fake text"
        if "document.images" in script:
            return self.images
        if script == "() => location.href":
            return self.url
        if script == "() => 'token=secret'":
            return "token=secret"
        return None


class FakeDialog:
    def __init__(self, message="token=secret", dialog_type="prompt", default_value="secret-default"):
        self.message = message
        self.type = dialog_type
        self.default_value = default_value
        self.accepted = []
        self.dismissed = False

    def accept(self, prompt_text=None):
        self.accepted.append(prompt_text)

    def dismiss(self):
        self.dismissed = True


class FakeBrowserContext:
    created = []
    closed = []

    def __init__(self, **options):
        self.options = options
        self.pages = [FakePage()]
        self.closed_flag = False
        self.created.append(self)

    def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page

    def close(self):
        self.closed_flag = True
        self.closed.append(self)


def test_register_loads_falsey_runtime_config_from_hermes_config(plugin, monkeypatch, tmp_path):
    FakeBrowserContext.created.clear()
    monkeypatch.delenv("CLOAKBROWSER_AUTO_UPDATE", raising=False)
    profile = tmp_path / "runtime-profile"
    runtime_config = {
        "plugins": {
            "entries": {
                "cloakbrowser-hermes-plugin": {
                    "allow_tool_override": True,
                    "config": {
                        "user_data_dir": str(profile),
                        "headless": False,
                        "humanize": False,
                        "stealth_args": False,
                        "args": [],
                        "auto_acknowledge_banner": False,
                        "auto_update": False,
                    },
                }
            }
        }
    }
    _install_hermes_config_loader(monkeypatch, runtime_config)
    _install_fake_cloakbrowser(
        monkeypatch,
        tmp_path / "cache",
        lambda **options: FakeBrowserContext(**options),
    )
    ctx = RuntimeCtx()

    parsed = plugin.config.load_config(ctx)
    plugin.register(ctx)
    result = json.loads(
        ctx.registered_tools[0]["handler"]({"url": "about:blank"}, task_id="runtime-config")
    )

    assert parsed.valid is True
    assert parsed.settings.headless is False
    assert parsed.settings.humanize is False
    assert parsed.settings.stealth_args is False
    assert parsed.settings.args == []
    assert parsed.settings.auto_acknowledge_banner is False
    assert parsed.settings.auto_update is False
    assert parsed.settings.user_data_dir == str(profile.resolve())
    assert result["url"] == "about:blank"
    assert FakeBrowserContext.created[-1].options["headless"] is False
    assert FakeBrowserContext.created[-1].options["humanize"] is False
    assert FakeBrowserContext.created[-1].options["stealth_args"] is False
    assert FakeBrowserContext.created[-1].options["user_data_dir"] == str(profile.resolve())
    assert FakeBrowserContext.created[-1].options["args"] == []
    assert os.environ["CLOAKBROWSER_AUTO_UPDATE"] == "false"


def test_runtime_auto_update_env_var_wins(plugin, monkeypatch, tmp_path):
    monkeypatch.setenv("CLOAKBROWSER_AUTO_UPDATE", "true")
    runtime_config = {
        "plugins": {
            "entries": {
                "cloakbrowser-hermes-plugin": {
                    "config": {
                        "user_data_dir": str(tmp_path / "profile"),
                        "auto_update": False,
                    }
                }
            }
        }
    }
    _install_hermes_config_loader(monkeypatch, runtime_config)
    _install_fake_cloakbrowser(
        monkeypatch,
        tmp_path / "cache",
        lambda **options: FakeBrowserContext(**options),
    )
    ctx = RuntimeCtx()

    plugin.register(ctx)
    result = json.loads(
        ctx.registered_tools[0]["handler"]({"url": "about:blank"}, task_id="auto-update-env")
    )

    assert result["url"] == "about:blank"
    assert os.environ["CLOAKBROWSER_AUTO_UPDATE"] == "true"


def test_invalid_runtime_config_from_hermes_loader_blocks_tool_override(plugin, monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "cloakbrowser", types.ModuleType("cloakbrowser"))
    runtime_config = {
        "plugins": {
            "entries": {
                "cloakbrowser-hermes-plugin": {
                    "config": {
                        "user_data_dir": str(tmp_path / "profile"),
                        "headless": "sometimes",
                        "args": ["--ok", 123],
                    }
                }
            }
        }
    }
    _install_hermes_config_loader(monkeypatch, runtime_config)
    ctx = RuntimeCtx()

    parsed = plugin.config.load_config(ctx)
    plugin.register(ctx)

    assert parsed.valid is False
    assert "headless must be a boolean" in parsed.errors
    assert "args must be a list of strings" in parsed.errors
    assert [command["name"] for command in ctx.registered_commands] == ["cloak"]
    assert ctx.registered_tools == []
    status = ctx.registered_commands[0]["handler"]("status")
    assert "headless must be a boolean" in status
    assert "args must be a list of strings" in status


def _registered_browser_tools(plugin, monkeypatch, tmp_path):
    FakeBrowserContext.created.clear()
    FakeBrowserContext.closed.clear()
    fake_sdk = types.ModuleType("cloakbrowser")
    fake_sdk.create = lambda **options: FakeBrowserContext(**options)
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    ctx = FakeCtx({"user_data_dir": str(tmp_path / "profile")})
    plugin.register(ctx)
    return {tool["name"]: tool["handler"] for tool in ctx.registered_tools}


def test_browser_handlers_perform_direct_sdk_operations(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)

    assert (
        json.loads(
            handlers["browser_navigate"](
                {"url": "https://example.test"}, task_id="task-a"
            )
        )["url"]
        == "https://example.test"
    )
    snapshot = json.loads(handlers["browser_snapshot"]({}, task_id="task-a"))
    assert "Fake page" in snapshot["snapshot"]
    assert "@e" in snapshot["snapshot"]
    assert (
        json.loads(handlers["browser_click"]({"ref": "@e2"}, task_id="task-a"))[
            "clicked"
        ]
        is True
    )
    assert (
        json.loads(
            handlers["browser_type"](
                {"selector": "#q", "text": "abc"}, task_id="task-a"
            )
        )["typed"]
        is True
    )
    assert (
        json.loads(handlers["browser_scroll"]({"direction": "down"}, task_id="task-a"))[
            "scrolled"
        ]
        == "down"
    )
    assert (
        json.loads(handlers["browser_press"]({"key": "Enter"}, task_id="task-a"))[
            "pressed"
        ]
        == "Enter"
    )
    assert (
        json.loads(handlers["browser_back"]({}, task_id="task-a"))["url"]
        == "about:previous"
    )
    assert json.loads(handlers["browser_console"]({}, task_id="task-a"))[
        "messages"
    ] == [{"type": "log", "text": "hello"}]
    images = json.loads(handlers["browser_get_images"]({}, task_id="task-a"))["images"]
    assert images == [
        {
            "src": "https://example.test/a.png?token=%5BREDACTED%5D",
            "alt": "A",
            "width": 10,
            "height": 20,
        }
    ]


def test_browser_dialog_captures_bounded_dialogs_and_actions(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_navigate"]({"url": "https://example.test"}, task_id="dialog-task")
    page = FakeBrowserContext.created[0].pages[0]
    first = FakeDialog(message="first token=secret", dialog_type="alert")
    last = FakeDialog(message="last token=secret", dialog_type="prompt")

    for idx in range(25):
        page.emit("dialog", FakeDialog(message=f"old-{idx}"))
    page.emit("dialog", first)
    page.emit("dialog", last)

    listing = json.loads(handlers["browser_dialog"]({}, task_id="dialog-task"))
    assert listing["count"] == 20
    assert listing["latest"]["message"] == "[REDACTED]"
    assert "secret" not in json.dumps(listing)

    accepted = json.loads(
        handlers["browser_dialog"](
            {"action": "accept", "prompt_text": "typed secret", "index": -1},
            task_id="dialog-task",
        )
    )
    assert accepted["handled"] is True
    assert last.accepted == ["typed secret"]

    dismissed = json.loads(
        handlers["browser_dialog"]({"action": "dismiss", "index": -1}, task_id="dialog-task")
    )
    assert dismissed["handled"] is True
    assert first.dismissed is True


def test_browser_dialog_accept_handles_once_and_removes_from_pending(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_navigate"]({"url": "https://example.test"}, task_id="dialog-accept")
    page = FakeBrowserContext.created[0].pages[0]
    dialog = FakeDialog(message="prompt token=secret", dialog_type="prompt", default_value="secret-default")
    page.emit("dialog", dialog)

    accepted = json.loads(
        handlers["browser_dialog"](
            {"action": "accept", "prompt_text": "typed secret", "index": -1},
            task_id="dialog-accept",
        )
    )
    second_accept = json.loads(
        handlers["browser_dialog"]({"action": "accept", "index": -1}, task_id="dialog-accept")
    )
    listing = json.loads(handlers["browser_dialog"]({}, task_id="dialog-accept"))

    assert accepted["handled"] is True
    assert accepted["count"] == 0
    assert dialog.accepted == ["typed secret"]
    assert second_accept == {"handled": False, "count": 0, "dialogs": []}
    assert dialog.accepted == ["typed secret"]
    assert listing["count"] == 0
    assert listing["latest"] is None
    assert listing["dialogs"] == []


def test_browser_dialog_dismiss_handles_once_and_removes_from_pending(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_navigate"]({"url": "https://example.test"}, task_id="dialog-dismiss")
    page = FakeBrowserContext.created[0].pages[0]
    dialog = FakeDialog(message="alert token=secret", dialog_type="alert")
    page.emit("dialog", dialog)

    dismissed = json.loads(
        handlers["browser_dialog"]({"action": "dismiss", "index": -1}, task_id="dialog-dismiss")
    )
    second_dismiss = json.loads(
        handlers["browser_dialog"]({"action": "dismiss", "index": -1}, task_id="dialog-dismiss")
    )

    assert dismissed["handled"] is True
    assert dismissed["count"] == 0
    assert dialog.dismissed is True
    assert second_dismiss == {"handled": False, "count": 0, "dialogs": []}


def test_browser_dialog_listing_redacts_pending_values_after_handling(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_navigate"]({"url": "https://example.test"}, task_id="dialog-list")
    page = FakeBrowserContext.created[0].pages[0]
    handled = FakeDialog(message="handled token=secret", default_value="secret-default")
    pending = FakeDialog(message="pending token=secret", default_value="secret-default")
    page.emit("dialog", handled)
    page.emit("dialog", pending)

    handlers["browser_dialog"]({"action": "accept", "index": 0}, task_id="dialog-list")
    listing = json.loads(handlers["browser_dialog"]({}, task_id="dialog-list"))

    assert listing["count"] == 1
    assert listing["latest"]["message"] == "[REDACTED]"
    assert listing["latest"]["default_value"] == "[REDACTED]"
    assert "secret" not in json.dumps(listing)


def test_browser_vision_screenshots_to_safe_temp_file_and_redacts(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_navigate"]({"url": "https://example.test"}, task_id="vision-task")

    result = json.loads(handlers["browser_vision"]({"annotate": True}, task_id="vision-task"))

    assert result["ok"] is True
    assert result["mime_type"] == "image/png"
    assert result["annotated"] is True
    assert result["labels"]
    screenshot_path = Path(result["screenshot_path"])
    assert screenshot_path.exists()
    assert screenshot_path.read_bytes().startswith(b"\x89PNG")
    assert str(tmp_path / "profile") not in json.dumps(result)
    assert "token=secret" not in json.dumps(result)


def test_browser_vision_annotation_badges_follow_ref_numbers_when_earlier_ref_not_drawable(
    plugin, monkeypatch, tmp_path
):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_navigate"]({"url": "https://example.test"}, task_id="vision-badges")
    page = FakeBrowserContext.created[0].pages[0]
    page._cloak_ref_map = {"@e1": "#missing", "@e2": "#go"}

    result = json.loads(handlers["browser_vision"]({"annotate": True}, task_id="vision-badges"))

    assert result["annotated"] is True
    assert result["labels"] == ["@e2"]
    assert result["badge_to_ref"] == {"2": "@e2"}


def test_browser_vision_annotation_derives_dom_refs_when_snapshot_has_no_drawable_refs(
    plugin, monkeypatch, tmp_path
):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_navigate"]({"url": "https://example.test"}, task_id="vision-dom")
    page = FakeBrowserContext.created[0].pages[0]
    page.accessibility = None
    page._cloak_ref_map = {}

    result = json.loads(handlers["browser_vision"]({"annotate": True}, task_id="vision-dom"))

    assert result["annotated"] is True
    assert result["labels"] == ["@e1", "@e2"]
    assert result["badge_to_ref"] == {"1": "@e1", "2": "@e2"}
    assert page._cloak_ref_map == {"@e1": "#dom-go", "@e2": "#dom-input"}
    assert page._cloak_ref_metadata["@e1"] == {"text": "DOM Go", "role": "button"}
    dom_scripts = [script for script in page.evaluate_scripts if "uniqueSelectorFor" in script]
    assert dom_scripts
    assert all("setAttribute" not in script for script in dom_scripts)
    assert all("data-cloak-ref" not in script for script in dom_scripts)
    assert all("document.querySelectorAll(selector).length === 1" in script for script in dom_scripts)
    assert all("if (!selector) continue" in script for script in dom_scripts)


def test_browser_vision_dom_fallback_stores_only_unique_generated_selectors(
    plugin, monkeypatch, tmp_path
):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_navigate"]({"url": "https://example.test"}, task_id="vision-unique")
    page = FakeBrowserContext.created[0].pages[0]
    page.accessibility = None
    page._cloak_ref_map = {}
    page.dom_fallback_elements = [
        {"ref": "@e1", "selector": "#unique-button", "text": "Unique", "role": "button"}
    ]

    result = json.loads(handlers["browser_vision"]({"annotate": True}, task_id="vision-unique"))

    assert result["labels"] == ["@e1"]
    assert page._cloak_ref_map == {"@e1": "#unique-button"}
    assert "#duplicate" not in json.dumps(page._cloak_ref_map)


def test_browser_click_and_type_use_generated_dom_fallback_refs(
    plugin, monkeypatch, tmp_path
):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_navigate"]({"url": "https://example.test"}, task_id="vision-dom-actions")
    page = FakeBrowserContext.created[0].pages[0]
    page.accessibility = None
    page._cloak_ref_map = {}

    handlers["browser_vision"]({"annotate": True}, task_id="vision-dom-actions")
    clicked = json.loads(handlers["browser_click"]({"ref": "@e1"}, task_id="vision-dom-actions"))
    typed = json.loads(
        handlers["browser_type"]({"ref": "@e2", "text": "abc"}, task_id="vision-dom-actions")
    )

    assert clicked["clicked"] is True
    assert typed["typed"] is True
    assert ("click", "#dom-go") in page.events
    assert ("fill", "#dom-input", "abc") in page.events


def test_browser_vision_dom_fallback_blocks_private_page_before_dom_read(
    plugin, monkeypatch, tmp_path
):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_navigate"]({"url": "about:blank"}, task_id="vision-dom-private")
    page = FakeBrowserContext.created[0].pages[0]
    page.url = "http://127.0.0.1/private?token=secret"
    page.accessibility = None

    result = json.loads(handlers["browser_vision"]({"annotate": True}, task_id="vision-dom-private"))

    assert "blocked private or metadata browser URL" in result["error"]
    assert "secret" not in json.dumps(result)
    assert page.screenshots == []


def test_browser_vision_screenshot_temp_files_cleaned_on_close_all(plugin, monkeypatch, tmp_path):
    fake_sdk = types.ModuleType("cloakbrowser")
    fake_sdk.create = lambda **options: FakeBrowserContext(**options)
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    manager = plugin.session_manager.SessionManager(
        plugin.config.load_config(
            FakeCtx({"user_data_dir": str(tmp_path / "profile")})
        ).settings
    )
    manager.adapter.call(
        "browser_navigate", {"url": "https://example.test"}, task_id="vision-cleanup"
    )

    result = manager.adapter.call("browser_vision", {}, task_id="vision-cleanup")
    screenshot_path = Path(result["screenshot_path"])
    temp_dir = screenshot_path.parent

    assert screenshot_path.exists()
    manager.close_all()

    assert not temp_dir.exists()


def test_session_manager_cleans_old_plugin_screenshot_dirs_on_init(plugin, monkeypatch, tmp_path):
    temp_root = Path(tempfile.gettempdir())
    plugin_dir = Path(tempfile.mkdtemp(prefix="cloakbrowser-vision-"))
    unrelated_dir = Path(tempfile.mkdtemp(prefix="cloakbrowser-vision-"))
    try:
        (plugin_dir / ".cloakbrowser-hermes-plugin").write_text("marker")
        (plugin_dir / "screenshot.png").write_bytes(b"old")
        old_mtime = time.time() - 7200
        os.utime(plugin_dir, (old_mtime, old_mtime))
        (unrelated_dir / "other.txt").write_text("keep")

        manager = plugin.session_manager.SessionManager(
            plugin.config.load_config(
                FakeCtx({"user_data_dir": str(tmp_path / "profile")})
            ).settings
        )

        assert not plugin_dir.exists()
        assert unrelated_dir.exists()
        manager.close_all()
    finally:
        if unrelated_dir.exists() and unrelated_dir.parent == temp_root:
            for child in unrelated_dir.iterdir():
                child.unlink()
            unrelated_dir.rmdir()


def test_browser_vision_blocks_private_page_reads(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_navigate"]({"url": "about:blank"}, task_id="private-vision")
    page = FakeBrowserContext.created[0].pages[0]
    page.url = "http://127.0.0.1/private"

    result = json.loads(handlers["browser_vision"]({}, task_id="private-vision"))

    assert "blocked private or metadata browser URL" in result["error"]
    assert page.screenshots == []


def test_session_manager_shares_context_by_profile_and_closes_lifecycle(
    plugin, monkeypatch, tmp_path
):
    fake_sdk = types.ModuleType("cloakbrowser")
    fake_sdk.create = lambda **options: FakeBrowserContext(**options)
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    FakeBrowserContext.created.clear()
    FakeBrowserContext.closed.clear()
    manager = plugin.session_manager.SessionManager(
        plugin.config.load_config(
            FakeCtx({"user_data_dir": str(tmp_path / "profile")})
        ).settings
    )

    first = manager.page_for(task_id="same-task")
    second = manager.page_for(task_id="same-task")
    other = manager.page_for(task_id="other-task")
    manager.close_all()

    assert first is second
    assert other is not first
    assert len(FakeBrowserContext.created) == 1
    assert len(FakeBrowserContext.created[0].pages) == 2
    assert FakeBrowserContext.closed == FakeBrowserContext.created

    reacquired = manager.page_for(task_id="after-close")
    assert reacquired is not first
    assert len(FakeBrowserContext.created) == 2
    manager.close_all()


def test_session_manager_races_single_context_for_same_profile(
    plugin, monkeypatch, tmp_path
):
    fake_sdk = types.ModuleType("cloakbrowser")

    def create(**options):
        time.sleep(0.05)
        return FakeBrowserContext(**options)

    fake_sdk.create = create
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    FakeBrowserContext.created.clear()
    FakeBrowserContext.closed.clear()
    manager = plugin.session_manager.SessionManager(
        plugin.config.load_config(
            FakeCtx({"user_data_dir": str(tmp_path / "profile")})
        ).settings
    )
    barrier = threading.Barrier(2)
    pages = []
    errors = []

    def get_page(task_id):
        try:
            barrier.wait(timeout=2)
            pages.append(manager.page_for(task_id=task_id))
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [
        threading.Thread(target=get_page, args=("task-a",)),
        threading.Thread(target=get_page, args=("task-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    manager.close_all()

    assert errors == []
    assert len(pages) == 2
    assert pages[0] is not pages[1]
    assert len(FakeBrowserContext.created) == 1
    assert len(FakeBrowserContext.created[0].pages) == 2
    assert FakeBrowserContext.closed == FakeBrowserContext.created


def test_session_manager_slow_create_does_not_block_unrelated_profile(
    plugin, monkeypatch, tmp_path
):
    slow_profile = str((tmp_path / "slow-profile").resolve())
    slow_started = threading.Event()
    release_slow = threading.Event()

    class ProfileAwareContext(FakeBrowserContext):
        pass

    def create(**options):
        if options["user_data_dir"] == slow_profile:
            slow_started.set()
            assert release_slow.wait(timeout=2)
        return ProfileAwareContext(**options)

    fake_sdk = types.ModuleType("cloakbrowser")
    fake_sdk.create = create
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    ProfileAwareContext.created.clear()
    ProfileAwareContext.closed.clear()
    slow_manager = plugin.session_manager.SessionManager(
        plugin.config.load_config(FakeCtx({"user_data_dir": slow_profile})).settings
    )
    fast_manager = plugin.session_manager.SessionManager(
        plugin.config.load_config(
            FakeCtx({"user_data_dir": str(tmp_path / "fast-profile")})
        ).settings
    )
    slow_pages = []
    slow_thread = threading.Thread(
        target=lambda: slow_pages.append(slow_manager.page_for(task_id="slow"))
    )

    slow_thread.start()
    assert slow_started.wait(timeout=2)
    fast_page = fast_manager.page_for(task_id="fast")

    assert fast_page is not None
    assert len(ProfileAwareContext.created) == 1
    assert ProfileAwareContext.created[0].options["user_data_dir"] != slow_profile

    release_slow.set()
    slow_thread.join(timeout=2)
    fast_manager.close_all()
    slow_manager.close_all()

    assert not slow_thread.is_alive()
    assert len(slow_pages) == 1
    assert len(ProfileAwareContext.created) == 2
    assert ProfileAwareContext.closed == ProfileAwareContext.created


def test_session_manager_same_session_concurrent_acquire_single_create(
    plugin, monkeypatch, tmp_path
):
    fake_sdk = types.ModuleType("cloakbrowser")
    create_calls = 0

    def create(**options):
        nonlocal create_calls
        create_calls += 1
        time.sleep(0.05)
        return FakeBrowserContext(**options)

    fake_sdk.create = create
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    FakeBrowserContext.created.clear()
    FakeBrowserContext.closed.clear()
    manager = plugin.session_manager.SessionManager(
        plugin.config.load_config(
            FakeCtx({"user_data_dir": str(tmp_path / "profile")})
        ).settings
    )
    barrier = threading.Barrier(2)
    pages = []
    errors = []

    def get_page():
        try:
            barrier.wait(timeout=2)
            pages.append(manager.page_for(session_id="same-session"))
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=get_page), threading.Thread(target=get_page)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    manager.close_all()

    assert errors == []
    assert len(pages) == 2
    assert pages[0] is pages[1]
    assert create_calls == 1
    assert len(FakeBrowserContext.created) == 1
    assert len(FakeBrowserContext.created[0].pages) == 1


def test_session_manager_close_all_waits_for_in_flight_page_creation(
    plugin, monkeypatch, tmp_path
):
    new_page_started = threading.Event()
    release_new_page = threading.Event()
    close_started = threading.Event()
    close_finished = threading.Event()

    class BlockingNewPageContext(FakeBrowserContext):
        def __init__(self, **options):
            super().__init__(**options)
            self.pages = []
            self.closed_before_returned_page = False

        def new_page(self):
            new_page_started.set()
            assert release_new_page.wait(timeout=2)
            page = super().new_page()
            self.closed_before_returned_page = self.closed_flag
            return page

        def close(self):
            close_started.set()
            super().close()
            close_finished.set()

    fake_sdk = types.ModuleType("cloakbrowser")
    fake_sdk.create = lambda **options: BlockingNewPageContext(**options)
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    BlockingNewPageContext.created.clear()
    BlockingNewPageContext.closed.clear()
    manager = plugin.session_manager.SessionManager(
        plugin.config.load_config(
            FakeCtx({"user_data_dir": str(tmp_path / "profile")})
        ).settings
    )
    pages = []
    errors = []

    def get_page():
        try:
            pages.append(manager.page_for(task_id="blocked-new-page"))
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    page_thread = threading.Thread(target=get_page)
    page_thread.start()
    assert new_page_started.wait(timeout=2)

    close_thread = threading.Thread(target=manager.close_all)
    close_thread.start()
    time.sleep(0.05)

    assert close_started.is_set() is False
    assert close_finished.is_set() is False

    release_new_page.set()
    page_thread.join(timeout=2)
    close_thread.join(timeout=2)

    assert errors == []
    assert len(pages) == 1
    assert not page_thread.is_alive()
    assert not close_thread.is_alive()
    assert len(BlockingNewPageContext.created) == 1
    assert BlockingNewPageContext.closed == BlockingNewPageContext.created
    assert BlockingNewPageContext.created[0].closed_before_returned_page is False


def test_session_manager_same_session_concurrent_new_page_single_page(
    plugin, monkeypatch, tmp_path
):
    class SlowNewPageContext(FakeBrowserContext):
        def __init__(self, **options):
            super().__init__(**options)
            self.pages = []
            self.new_page_calls = 0

        def new_page(self):
            self.new_page_calls += 1
            time.sleep(0.05)
            return super().new_page()

    fake_sdk = types.ModuleType("cloakbrowser")
    fake_sdk.create = lambda **options: SlowNewPageContext(**options)
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    SlowNewPageContext.created.clear()
    SlowNewPageContext.closed.clear()
    manager = plugin.session_manager.SessionManager(
        plugin.config.load_config(
            FakeCtx({"user_data_dir": str(tmp_path / "profile")})
        ).settings
    )
    barrier = threading.Barrier(2)
    pages = []
    errors = []

    def get_page():
        try:
            barrier.wait(timeout=2)
            pages.append(manager.page_for(task_id="same-task"))
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=get_page), threading.Thread(target=get_page)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    manager.close_all()

    assert errors == []
    assert len(pages) == 2
    assert pages[0] is pages[1]
    assert len(SlowNewPageContext.created) == 1
    assert SlowNewPageContext.created[0].new_page_calls == 1


def test_session_manager_process_registry_shares_context_across_managers(
    plugin, monkeypatch, tmp_path
):
    fake_sdk = types.ModuleType("cloakbrowser")
    fake_sdk.create = lambda **options: FakeBrowserContext(**options)
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    FakeBrowserContext.created.clear()
    FakeBrowserContext.closed.clear()
    settings = plugin.config.load_config(
        FakeCtx({"user_data_dir": str(tmp_path / "profile")})
    ).settings
    first_manager = plugin.session_manager.SessionManager(settings)
    second_manager = plugin.session_manager.SessionManager(settings)

    first_page = first_manager.page_for(task_id="task-a")
    second_page = second_manager.page_for(task_id="task-b")
    first_manager.close_all()

    assert first_page is not second_page
    assert len(FakeBrowserContext.created) == 1
    assert len(FakeBrowserContext.created[0].pages) == 2
    assert FakeBrowserContext.closed == []

    second_manager.close_all()

    assert FakeBrowserContext.closed == FakeBrowserContext.created
    reacquired = first_manager.page_for(task_id="task-c")
    assert reacquired is not first_page
    assert len(FakeBrowserContext.created) == 2
    first_manager.close_all()


def test_session_manager_acquire_waits_for_final_close_teardown(
    plugin, monkeypatch, tmp_path
):
    close_started = threading.Event()
    release_close = threading.Event()

    class BlockingCloseContext(FakeBrowserContext):
        def close(self):
            close_started.set()
            assert release_close.wait(timeout=2)
            super().close()

    fake_sdk = types.ModuleType("cloakbrowser")
    fake_sdk.create = lambda **options: BlockingCloseContext(**options)
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    BlockingCloseContext.created.clear()
    BlockingCloseContext.closed.clear()
    settings = plugin.config.load_config(
        FakeCtx({"user_data_dir": str(tmp_path / "profile")})
    ).settings
    closing_manager = plugin.session_manager.SessionManager(settings)
    acquiring_manager = plugin.session_manager.SessionManager(settings)
    first_page = closing_manager.page_for(task_id="task-a")
    acquired_pages = []

    close_thread = threading.Thread(target=closing_manager.close_all)
    close_thread.start()
    assert close_started.wait(timeout=2)

    acquire_thread = threading.Thread(
        target=lambda: acquired_pages.append(
            acquiring_manager.page_for(task_id="task-b")
        )
    )
    acquire_thread.start()
    time.sleep(0.05)

    assert acquire_thread.is_alive()
    assert acquired_pages == []
    assert len(BlockingCloseContext.created) == 1

    release_close.set()
    close_thread.join(timeout=2)
    acquire_thread.join(timeout=2)
    acquiring_manager.close_all()

    assert not close_thread.is_alive()
    assert not acquire_thread.is_alive()
    assert acquired_pages and acquired_pages[0] is not first_page
    assert len(BlockingCloseContext.created) == 2
    assert BlockingCloseContext.closed == BlockingCloseContext.created


def test_status_redacts_profile_path(plugin, monkeypatch, tmp_path):
    fake_sdk = types.ModuleType("cloakbrowser")
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    profile = tmp_path / "private-profile"
    ctx = FakeCtx({"user_data_dir": str(profile)})

    plugin.register(ctx)
    output = ctx.registered_commands[0]["handler"]("status")
    manager_status = plugin.session_manager.SessionManager(
        plugin.config.load_config(ctx).settings
    ).status()

    assert str(profile.resolve()) not in output
    assert "profile_dir" not in output
    assert "profile_configured: True" in output
    assert "profile_dir" not in manager_status
    assert manager_status["profile_configured"] is True


def test_docs_do_not_contain_mcp_residue():
    doc_text = "\n".join(
        [
            Path(__file__).with_name("README.md").read_text(),
            Path(__file__).with_name("INSTALL.md").read_text(),
        ]
    ).lower()

    assert "mcp" not in doc_text
    assert "cloakbrowser-mcp" not in doc_text
    assert "reload-mcp" not in doc_text
    assert "hermes mcp" not in doc_text


@pytest.mark.parametrize(
    "unsafe_path, expected_error",
    [
        ("/", "dedicated CloakBrowser profile"),
        (str(Path.home()), "dedicated CloakBrowser profile"),
        (str(Path.home() / ".config" / "google-chrome" / "Default"), "browser profile"),
        (
            str(
                Path.home()
                / ".hermes"
                / "profiles"
                / "other"
                / "browser-profiles"
                / "cloakbrowser"
            ),
            "another Hermes profile",
        ),
        (str(Path(__file__).resolve().parent), "dedicated CloakBrowser profile"),
    ],
)
def test_user_data_dir_rejects_dangerous_paths(plugin, unsafe_path, expected_error):
    parsed = plugin.config.load_config(FakeCtx({"user_data_dir": unsafe_path}))

    assert parsed.valid is False
    assert any(expected_error in error for error in parsed.errors)


def test_user_data_dir_rejects_symlink_components(plugin, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)

    parsed = plugin.config.load_config(
        FakeCtx({"user_data_dir": str(link / "profile")})
    )

    assert parsed.valid is False
    assert any("symlink" in error for error in parsed.errors)


def test_string_booleans_parse_strictly(plugin, tmp_path):
    parsed = plugin.config.load_config(
        FakeCtx(
            {
                "user_data_dir": str(tmp_path / "profile"),
                "headless": "false",
                "humanize": "0",
                "stealth_args": "off",
                "geoip": "no",
            }
        )
    )

    assert parsed.valid is True
    assert parsed.settings.headless is False
    assert parsed.settings.humanize is False
    assert parsed.settings.stealth_args is False
    assert parsed.settings.geoip is False


def test_navigation_blocks_metadata_and_private_urls(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)

    for url in [
        "http://169.254.169.254/latest/meta-data",
        "http://127.0.0.1:8080",
        "file:///etc/passwd",
        "data:text/html,hi",
    ]:
        result = json.loads(
            handlers["browser_navigate"]({"url": url}, task_id=f"task-{url}")
        )
        assert "blocked" in result["error"]
        assert "169.254.169.254" not in json.dumps(result)
        assert "/etc/passwd" not in json.dumps(result)


def test_browser_outputs_are_redacted(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)

    result = json.loads(
        handlers["browser_navigate"](
            {"url": "https://example.test/path?token=secret"}, task_id="redact"
        )
    )
    assert result["url"] == "https://example.test/path?token=%5BREDACTED%5D"
    console = json.loads(
        handlers["browser_console"](
            {"expression": "() => 'token=secret'"}, task_id="redact"
        )
    )
    assert console["result"] == "token=[REDACTED]"


def test_console_expression_clear_and_bounded_capture(plugin, monkeypatch, tmp_path):
    fake_sdk = types.ModuleType("cloakbrowser")
    fake_sdk.create = lambda **options: FakeBrowserContext(**options)
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    manager = plugin.session_manager.SessionManager(
        plugin.config.load_config(
            FakeCtx({"user_data_dir": str(tmp_path / "profile")})
        ).settings
    )
    page = manager.page_for(task_id="console")
    captured = page._cloak_console_messages
    for index in range(250):
        captured.append({"type": "log", "text": f"msg-{index}?token=secret"})

    console = manager.adapter.call(
        "browser_console",
        {"expression": "() => location.href", "clear": True},
        task_id="console",
    )

    assert console["result"] == "about:blank"
    assert len(console["messages"]) == 200
    assert console["messages"][0]["text"].startswith("msg-50")
    assert "secret" not in json.dumps(console)
    assert list(captured) == []


def test_private_page_after_eval_fails_closed(plugin, monkeypatch, tmp_path):
    fake_sdk = types.ModuleType("cloakbrowser")
    fake_sdk.create = lambda **options: FakeBrowserContext(**options)
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    manager = plugin.session_manager.SessionManager(
        plugin.config.load_config(
            FakeCtx({"user_data_dir": str(tmp_path / "profile")})
        ).settings
    )
    page = manager.page_for(task_id="eval-private")

    def redirecting_evaluate(_script):
        page.url = "http://127.0.0.1/private"
        return "private-data"

    page.evaluate = redirecting_evaluate
    result = manager.adapter.call(
        "browser_console", {"expression": "() => location.href"}, task_id="eval-private"
    )

    assert "blocked" in result["error"]
    assert "127.0.0.1" not in json.dumps(result)
    assert "private-data" not in json.dumps(result)


def test_session_key_namespaces_task_and_session(plugin, tmp_path):
    manager = plugin.session_manager.SessionManager(
        plugin.config.load_config(
            FakeCtx({"user_data_dir": str(tmp_path / "profile")})
        ).settings
    )

    assert manager._session_key(task_id="same") == "task:same"
    assert manager._session_key(session_id="same") == "session:same"


def test_session_id_and_task_id_pages_are_isolated(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)

    handlers["browser_navigate"]({"url": "https://example.test/task"}, task_id="same")
    handlers["browser_navigate"]({"url": "https://example.test/session"}, session_id="same")
    handlers["browser_type"]({"selector": "#q", "text": "task-text"}, task_id="same")
    handlers["browser_type"]({"selector": "#q", "text": "session-text"}, session_id="same")

    assert len(FakeBrowserContext.created) == 1
    task_page = FakeBrowserContext.created[0].pages[0]
    session_page = FakeBrowserContext.created[0].pages[1]
    assert task_page.url == "https://example.test/task"
    assert session_page.url == "https://example.test/session"
    assert ("fill", "#q", "task-text") in task_page.events
    assert ("fill", "#q", "session-text") in session_page.events
    assert "session-text" not in json.dumps(task_page.events)
    assert "task-text" not in json.dumps(session_page.events)

    task_page.console_messages = [{"type": "log", "text": "task-only"}]
    session_page.console_messages = [{"type": "log", "text": "session-only"}]
    assert json.loads(handlers["browser_console"]({}, task_id="same"))["messages"] == [
        {"type": "log", "text": "task-only"}
    ]
    assert json.loads(handlers["browser_console"]({}, session_id="same"))["messages"] == [
        {"type": "log", "text": "session-only"}
    ]


def test_ref_maps_are_per_page_and_cleared_on_navigation(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)

    handlers["browser_snapshot"]({}, task_id="task-a")
    handlers["browser_snapshot"]({}, task_id="task-b")
    assert json.loads(handlers["browser_click"]({"ref": "@e2"}, task_id="task-a"))["clicked"] is True

    assert len(FakeBrowserContext.created) == 1
    page_a = FakeBrowserContext.created[0].pages[0]
    page_b = FakeBrowserContext.created[0].pages[1]
    assert page_a.events == [("click", "#go")]
    assert page_b.events == []

    handlers["browser_navigate"]({"url": "https://example.test/new"}, task_id="task-a")
    stale = json.loads(handlers["browser_click"]({"ref": "@e2"}, task_id="task-a"))
    assert "unknown browser ref" in stale["error"]


def test_console_output_is_bounded_and_redacts_nested_secrets(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_snapshot"]({}, task_id="console-bounds")
    page = FakeBrowserContext.created[0].pages[0]
    page.console_messages = [
        {"type": "log", "text": f"line-{index} Bearer secret-token-{index}"}
        for index in range(250)
    ]

    output = json.loads(handlers["browser_console"]({}, task_id="console-bounds"))

    assert len(output["messages"]) == 200
    assert output["messages"][0]["text"].startswith("line-50")
    assert "secret-token" not in json.dumps(output)
    assert "Bearer [REDACTED]" in json.dumps(output)


def test_console_messages_method_is_called(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_snapshot"]({}, task_id="console-method")
    page = FakeBrowserContext.created[0].pages[0]
    method_messages = [{"type": "log", "text": "method-token=secret"}]

    def console_messages():
        return method_messages

    page.console_messages = console_messages

    output = json.loads(handlers["browser_console"]({}, task_id="console-method"))

    assert output["messages"] == [{"type": "log", "text": "method-token=[REDACTED]"}]


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://localhost.localdomain/admin",
        "http://metadata.google.internal/computeMetadata/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://169.254.170.2/v2/credentials",
        "http://127.0.0.1:9222/json",
        "http://[::1]/",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "file:///etc/passwd",
        "data:text/html,secret",
        "blob:https://example.test/id",
        "javascript:alert(1)",
        "ftp://example.test/file",
        "https://user:password@example.test/",
    ],
)
def test_url_guard_blocks_private_metadata_credentials_and_unsafe_schemes(
    plugin, monkeypatch, tmp_path, url
):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)

    result = json.loads(handlers["browser_navigate"]({"url": url}, task_id="guard"))

    assert "blocked" in result["error"]
    serialized = json.dumps(result)
    assert "password" not in serialized
    assert "/etc/passwd" not in serialized
    assert "secret" not in serialized


def test_url_guard_blocks_dns_rebinding_to_private_ip(plugin, monkeypatch, tmp_path):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)

    monkeypatch.setattr(
        plugin.adapter.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 0))],
    )

    result = json.loads(
        handlers["browser_navigate"]({"url": "https://rebind.test"}, task_id="guard"),
    )
    assert "blocked private or metadata browser URL" in result["error"]


def test_get_images_filters_unreturnable_and_redacts_sensitive_urls(
    plugin, monkeypatch, tmp_path
):
    handlers = _registered_browser_tools(plugin, monkeypatch, tmp_path)
    handlers["browser_snapshot"]({}, task_id="images")
    page = FakeBrowserContext.created[0].pages[0]
    page.images.extend(
        [
            {"src": "https://example.test/ok.jpg?api_key=secret", "alt": "ok"},
            {"src": "https://user:pass@example.test/creds.jpg", "alt": "creds"},
            {"src": "http://localhost/private.jpg", "alt": "local"},
            {"src": "file:///tmp/private.jpg", "alt": "file"},
        ]
    )

    result = json.loads(handlers["browser_get_images"]({}, task_id="images"))

    assert [image["alt"] for image in result["images"]] == ["A", "ok"]
    serialized = json.dumps(result)
    assert "secret" not in serialized
    assert "pass" not in serialized
    assert "localhost" not in serialized
    assert "file:///" not in serialized


def test_preflight_fails_closed_for_invalid_config_even_when_sdk_exists(
    plugin, monkeypatch
):
    fake_sdk = types.ModuleType("cloakbrowser")
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
    ctx = FakeCtx({"user_data_dir": "/"})

    plugin.register(ctx)

    assert [command["name"] for command in ctx.registered_commands] == ["cloak"]
    assert ctx.registered_tools == []
    status = ctx.registered_commands[0]["handler"]("status")
    assert "ready: False" in status
    assert "dedicated CloakBrowser profile" in status
