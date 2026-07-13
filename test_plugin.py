from __future__ import annotations

import importlib.util
import json
import sys
import types
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
    assert "allow_tool_override" not in parsed.settings.to_sdk_options()
    assert "geoip requires proxy" in "; ".join(parsed.warnings)


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

    def evaluate(self, script):
        if "document.body.innerText" in script:
            return "Fake text"
        if "document.images" in script:
            return self.images
        if script == "() => location.href":
            return self.url
        if script == "() => 'token=secret'":
            return "token=secret"
        return None


class FakeBrowserContext:
    closed = []

    def __init__(self, **options):
        self.options = options
        self.pages = [FakePage()]
        self.closed_flag = False

    def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page

    def close(self):
        self.closed_flag = True
        self.closed.append(self)


def _registered_browser_tools(plugin, monkeypatch, tmp_path):
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


def test_session_manager_reuses_by_task_and_closes_lifecycle(
    plugin, monkeypatch, tmp_path
):
    fake_sdk = types.ModuleType("cloakbrowser")
    fake_sdk.create = lambda **options: FakeBrowserContext(**options)
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_sdk)
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
    assert len(FakeBrowserContext.closed) >= 2


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
