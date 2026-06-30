from __future__ import annotations

import sys
import types
from pathlib import Path


def pytest_configure(config):
    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: Path("/tmp/hermes-test-home"))

    registry_module = types.ModuleType("tools.registry")
    setattr(registry_module, "registry", types.SimpleNamespace(_tools={
        "mcp_cloakbrowser_browser_launch": object(),
        "mcp_cloakbrowser_browser_close": object(),
        "mcp_cloakbrowser_browser_list_pages": object(),
        "mcp_cloakbrowser_browser_navigate": object(),
        "mcp_cloakbrowser_browser_snapshot": object(),
        "mcp_cloakbrowser_browser_new_page": object(),
    }))

    browser_tool = types.ModuleType("tools.browser_tool")
    setattr(browser_tool, "_BROWSER_SCHEMA_MAP", {})

    sys.modules.setdefault("hermes_constants", hermes_constants)
    sys.modules.setdefault("tools", types.ModuleType("tools"))
    sys.modules.setdefault("tools.registry", registry_module)
    sys.modules.setdefault("tools.browser_tool", browser_tool)
