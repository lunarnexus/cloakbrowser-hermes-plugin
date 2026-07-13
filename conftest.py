from __future__ import annotations

import sys
import types
from pathlib import Path


def pytest_configure(config):
    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: Path("/tmp/hermes-test-home"))

    browser_tool = types.ModuleType("tools.browser_tool")
    setattr(browser_tool, "_BROWSER_SCHEMA_MAP", {})

    sys.modules.setdefault("hermes_constants", hermes_constants)
    sys.modules.setdefault("tools", types.ModuleType("tools"))
    sys.modules.setdefault("tools.browser_tool", browser_tool)
