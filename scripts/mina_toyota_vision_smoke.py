from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional evidence only
    Image = None


def default_profile_home(profile: str) -> Path:
    return Path.home() / ".hermes" / "profiles" / profile


def add_plugin_to_path(profile_home: Path) -> Path:
    plugin_dir = profile_home / "plugins" / "cloakbrowser-hermes-plugin"
    sys.path.insert(0, str(plugin_dir))
    return plugin_dir


def summarize_snapshot(snap: dict) -> dict:
    text = snap.get("snapshot") or ""
    refs = snap.get("refs") or []
    return {
        "ok": "error" not in snap,
        "source": snap.get("source"),
        "url": snap.get("url"),
        "refs_count": len(refs),
        "refs_sample": refs[:20],
        "snapshot_chars": len(text),
        "snapshot_excerpt": text[:1000],
        "error": snap.get("error"),
    }


def file_evidence(path_str: str | None) -> dict:
    if not path_str:
        return {"exists": False}
    path = Path(path_str)
    ev = {"path": str(path), "exists": path.exists(), "parent_exists": path.parent.exists()}
    if path.exists():
        ev["size_bytes"] = path.stat().st_size
        if Image is not None:
            with Image.open(path) as img:
                ev["dimensions"] = list(img.size)
                ev["mode"] = img.mode
    return ev


def run_url(manager, url: str, task_id: str) -> dict:
    out = {"url_attempted": url, "task_id": task_id}
    t0 = time.time()
    out["navigate"] = manager.adapter.call(
        "browser_navigate", {"url": url, "wait_until": "domcontentloaded"}, task_id=task_id
    )
    out["navigate_elapsed_s"] = round(time.time() - t0, 2)
    time.sleep(3)
    snap = manager.adapter.call("browser_snapshot", {}, task_id=task_id)
    out["snapshot_summary"] = summarize_snapshot(snap)
    vision = manager.adapter.call("browser_vision", {"annotate": True}, task_id=task_id)
    out["vision"] = vision
    out["vision_file_before_close"] = file_evidence(
        vision.get("screenshot_path") if isinstance(vision, dict) else None
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Toyota annotation smoke for CloakBrowser Hermes plugin.")
    parser.add_argument("--profile", default="mina")
    parser.add_argument("--url", default="https://www.toyota.com/")
    parser.add_argument("--fallback-url", default="https://www.toyota.com/camry/")
    parser.add_argument("--user-data-suffix", default="cloakbrowser")
    args = parser.parse_args()

    profile_home = default_profile_home(args.profile)
    os.environ["HERMES_HOME"] = str(profile_home)
    plugin_dir = add_plugin_to_path(profile_home)

    from config import CloakConfig  # type: ignore
    from session_manager import SessionManager  # type: ignore

    settings = CloakConfig(
        user_data_dir=str(profile_home / "browser-profiles" / args.user_data_suffix),
        headless=True,
        humanize=True,
        human_preset="default",
        stealth_args=True,
        geoip=False,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    manager = SessionManager(settings)
    result = {
        "settings": {"user_data_dir": settings.user_data_dir, "headless": settings.headless},
        "plugin_dir": str(plugin_dir),
        "python": sys.executable,
        "attempts": [],
    }
    screenshot_paths: list[str] = []
    try:
        for idx, url in enumerate([args.url, args.fallback_url], start=1):
            attempt = run_url(manager, url, f"toyota-live-annotate-{idx}")
            result["attempts"].append(attempt)
            vision = attempt.get("vision") or {}
            if isinstance(vision, dict) and vision.get("screenshot_path"):
                screenshot_paths.append(vision["screenshot_path"])
            if not vision.get("error") and vision.get("ok") and vision.get("annotated") and vision.get("labels"):
                break
    finally:
        before_close = {p: file_evidence(p) for p in screenshot_paths}
        manager.close_all()
        after_close = {p: file_evidence(p) for p in screenshot_paths}
        result["cleanup"] = {"before_close": before_close, "after_close": after_close}

    print(json.dumps(result, indent=2, ensure_ascii=False))
    passed = any(
        (a.get("vision") or {}).get("ok")
        and (a.get("vision") or {}).get("annotated")
        and (a.get("vision") or {}).get("labels")
        and (a.get("vision_file_before_close") or {}).get("exists")
        for a in result["attempts"]
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
