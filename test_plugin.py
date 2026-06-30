from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path


class FakeCtx:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def dispatch_tool(self, tool_name, args):
        self.calls.append((tool_name, args))
        if not self.responses:
            raise AssertionError(f"unexpected dispatch: {tool_name} {args}")
        return json.dumps({"result": self.responses.pop(0)})


def load_plugin(monkeypatch, tmp_path):
    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)

    registry = types.SimpleNamespace(_tools={
        "mcp_cloakbrowser_browser_launch": object(),
        "mcp_cloakbrowser_browser_close": object(),
        "mcp_cloakbrowser_browser_list_pages": object(),
        "mcp_cloakbrowser_browser_navigate": object(),
        "mcp_cloakbrowser_browser_snapshot": object(),
        "mcp_cloakbrowser_browser_new_page": object(),
    })
    registry_module = types.ModuleType("tools.registry")
    setattr(registry_module, "registry", registry)

    browser_tool = types.ModuleType("tools.browser_tool")
    setattr(browser_tool, "_BROWSER_SCHEMA_MAP", {})

    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.registry", registry_module)
    monkeypatch.setitem(sys.modules, "tools.browser_tool", browser_tool)

    module_name = "cloakbrowser_hermes_plugin_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        Path(__file__).with_name("__init__.py"),
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_launch_remembers_fresh_page_id(monkeypatch, tmp_path):
    plugin = load_plugin(monkeypatch, tmp_path)
    ctx = FakeCtx([{"status": "launched", "page_id": "page_fresh"}])

    result = plugin._launch(ctx)

    assert result["page_id"] == "page_fresh"
    assert plugin._STATE["page_id"] == "page_fresh"
    assert ctx.calls == [
        ("mcp_cloakbrowser_browser_launch", {
            "headless": False,
            "humanize": True,
            "stealth_args": True,
            "user_data_dir": str(tmp_path / "browser-profiles" / "cloakbrowser"),
        })
    ]


def test_launch_adopts_page_when_already_running_returns_pages(monkeypatch, tmp_path):
    plugin = load_plugin(monkeypatch, tmp_path)
    ctx = FakeCtx([{"status": "already_running", "pages": [{"page_id": "page_existing", "url": "about:blank"}]}])

    result = plugin._launch(ctx)

    assert result["page_id"] == "page_existing"
    assert plugin._STATE["page_id"] == "page_existing"
    assert len(ctx.calls) == 1


def test_launch_creates_page_when_already_running_has_no_pages(monkeypatch, tmp_path):
    plugin = load_plugin(monkeypatch, tmp_path)
    ctx = FakeCtx([
        {"status": "already_running", "pages": []},
        {"page_id": "page_new"},
    ])

    result = plugin._launch(ctx)

    assert result["page_id"] == "page_new"
    assert plugin._STATE["page_id"] == "page_new"
    assert ctx.calls[0][0] == "mcp_cloakbrowser_browser_launch"
    assert ctx.calls[1] == ("mcp_cloakbrowser_browser_new_page", {})


def test_launch_propagates_new_page_error(monkeypatch, tmp_path):
    plugin = load_plugin(monkeypatch, tmp_path)
    ctx = FakeCtx([
        {"status": "already_running", "pages": []},
        {"error": "Browser is not running"},
    ])

    try:
        plugin._launch(ctx)
    except RuntimeError as exc:
        assert "Browser is not running" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
