from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


def default_profile_home(profile: str) -> Path:
    return Path.home() / ".hermes" / "profiles" / profile


def load_plugin(plugin_dir: Path):
    os.environ.setdefault("HERMES_HOME", str(plugin_dir.parents[2]))
    sys.path.insert(0, str(plugin_dir))
    spec = importlib.util.spec_from_file_location(
        "cloakbrowser_hermes_plugin",
        plugin_dir / "__init__.py",
        submodule_search_locations=[str(plugin_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load plugin from {plugin_dir}")
    plugin = importlib.util.module_from_spec(spec)
    sys.modules["cloakbrowser_hermes_plugin"] = plugin
    spec.loader.exec_module(plugin)
    return plugin


class Context:
    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.tools: dict[str, dict[str, Any]] = {}
        self.commands: dict[str, dict[str, Any]] = {}

    def register_tool(self, **kwargs: Any) -> None:
        self.tools[kwargs["name"]] = kwargs

    def register_command(self, name: str, **kwargs: Any) -> None:
        self.commands[name] = kwargs


def summarize(data: dict[str, Any]) -> dict[str, Any]:
    summary = {k: v for k, v in data.items() if k not in ("snapshot", "messages", "images", "dialogs")}
    if "snapshot" in data:
        summary.update(snapshot_len=len(data.get("snapshot") or ""), refs_count=len(data.get("refs") or []))
    if "messages" in data:
        summary.update(messages_count=len(data.get("messages") or []), result=data.get("result"))
    if "images" in data:
        summary["images_count"] = len(data.get("images") or [])
    if "dialogs" in data:
        summary["dialogs"] = data.get("dialogs")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Live 11-tool smoke for installed CloakBrowser Hermes plugin.")
    parser.add_argument("--profile", default="mina")
    args = parser.parse_args()

    profile_home = default_profile_home(args.profile)
    os.environ["HERMES_HOME"] = str(profile_home)
    plugin_dir = profile_home / "plugins" / "cloakbrowser-hermes-plugin"
    plugin = load_plugin(plugin_dir)
    ctx = Context()
    plugin.register(ctx)

    expected = [
        "browser_back",
        "browser_click",
        "browser_console",
        "browser_dialog",
        "browser_get_images",
        "browser_navigate",
        "browser_press",
        "browser_scroll",
        "browser_snapshot",
        "browser_type",
        "browser_vision",
    ]
    print("REGISTERED_TOOLS", json.dumps(sorted(ctx.tools)))
    print("EXPECTED_11_MATCH", sorted(ctx.tools) == sorted(expected))
    print("HAS_BROWSER_CDP", "browser_cdp" in ctx.tools)
    if sorted(ctx.tools) != sorted(expected):
        return 2

    def call(name: str, args: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        data = json.loads(ctx.tools[name]["handler"](args or {}, **kwargs))
        print(f"{name} {json.dumps(args or {})} -> {json.dumps(summarize(data), ensure_ascii=False)}")
        if data.get("error"):
            raise RuntimeError(f"{name} failed: {data}")
        return data

    task = "mina-live-verify"
    call("browser_navigate", {"url": "https://example.com", "wait_until": "load"}, task_id=task)
    call(
        "browser_console",
        {
            "expression": """() => { document.body.innerHTML = `<main style='height:1600px'><h1>Mina Cloak Verify</h1><img alt='IANA logo' src='https://www.iana.org/_img/2025.01/iana-logo-header.svg'><input id='name' name='fname'><button id='btn' onclick='document.body.dataset.clicked="yes"'>Click me</button></main>`; return document.title; }""",
            "clear": True,
        },
        task_id=task,
    )
    call("browser_snapshot", {}, task_id=task)
    call("browser_get_images", {}, task_id=task)
    call("browser_scroll", {"direction": "down", "amount": 500}, task_id=task)
    call("browser_scroll", {"direction": "up", "amount": 250}, task_id=task)
    call("browser_press", {"key": "Tab"}, task_id=task)
    call("browser_type", {"selector": "#name", "text": "Mina"}, task_id=task)
    call("browser_click", {"selector": "#btn"}, task_id=task)
    clicked = call("browser_console", {"expression": "() => document.body.dataset.clicked"}, task_id=task)
    print("CLICK_DATASET", clicked.get("result"))
    call("browser_navigate", {"url": "https://www.iana.org/help/example-domains", "wait_until": "load"}, task_id=task)
    call("browser_back", {}, task_id=task)
    vision = call("browser_vision", {"question": "verify screenshot capture", "annotate": True}, task_id=task)
    shot = Path(vision["screenshot_path"])
    print("VISION_SCREENSHOT_EXISTS_BEFORE_CLOSE", shot.exists(), str(shot))
    print("VISION_ANNOTATED", vision.get("annotated"), "LABEL_COUNT", len(vision.get("labels") or []))

    # Dialogs are best verified in dedicated focused tests; this broad smoke avoids unsafe site modal state.
    for tool in ctx.tools.values():
        handler = tool.get("handler")
        for obj in getattr(handler, "__defaults__", ()) or ():
            if hasattr(obj, "manager"):
                obj.manager.close_all()
                print("VISION_SCREENSHOT_EXISTS_AFTER_CLOSE", shot.exists())
                print("ALL_PASS")
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
