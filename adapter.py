from __future__ import annotations

import asyncio
import importlib
import inspect
import ipaddress
import json
import os
import re
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from .config import CloakConfig
except ImportError:
    from config import CloakConfig  # type: ignore[no-redef]

SENSITIVE_QUERY_KEYS = re.compile(
    r"(token|secret|key|password|passwd|pwd|auth|session|cookie|credential|code)", re.I
)
SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.I),
    re.compile(r"([?&](?:access_)?token=)[^\s&#]+", re.I),
    re.compile(
        r"([?&](?:api[_-]?key|secret|password|passwd|pwd|session|cookie|code)=)[^\s&#]+",
        re.I,
    ),
    re.compile(
        r"\b((?:(?:access_)?token|api[_-]?key|secret|password|passwd|pwd|session|cookie|code)=)[^\s&#]+",
        re.I,
    ),
    re.compile(r"\b(secret|password|passwd|pwd|cookie)[-_][A-Za-z0-9._~+/=-]+", re.I),
    re.compile(r"\b[A-Za-z0-9._%+-]+:[^\s/@]+@"),
]
BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal"}
METADATA_IPS = {"169.254.169.254", "169.254.170.2"}
MAX_REDACTED_TEXT = 20000


class CloakBrowserAdapter:
    """Direct-SDK boundary around CloakBrowser/Playwright-like APIs with Hermes parity guards."""

    def __init__(self, settings: CloakConfig, manager: Any | None = None):
        self.settings = settings
        self.manager = manager

    def run(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(value)
            raise RuntimeError(
                "async CloakBrowser SDK calls are not supported inside an already-running event loop"
            ) from None
        return value

    def create_context(self) -> Any:
        self._configure_sdk_environment()
        self._acknowledge_sdk_banner()
        sdk = importlib.import_module("cloakbrowser")
        options = self.settings.to_sdk_options()
        for name in ("create", "launch_persistent_context"):
            factory = getattr(sdk, name, None)
            if callable(factory):
                return self.run(factory(**options))
        launch = getattr(sdk, "launch", None)
        if callable(launch):
            launch_options = {
                key: value for key, value in options.items() if key != "user_data_dir"
            }
            return self.run(launch(**launch_options))
        browser_cls = getattr(sdk, "CloakBrowser", None) or getattr(
            sdk, "Browser", None
        )
        if browser_cls is not None:
            instance = self.run(browser_cls(**options))
            for method in (
                "launch_persistent_context",
                "new_context",
                "context",
                "start",
            ):
                member = getattr(instance, method, None)
                if callable(member):
                    return self.run(member())
            return instance
        raise RuntimeError("cloakbrowser SDK has no supported browser/context factory")

    def _configure_sdk_environment(self) -> None:
        if (
            self.settings.auto_update is False
            and "CLOAKBROWSER_AUTO_UPDATE" not in os.environ
        ):
            os.environ["CLOAKBROWSER_AUTO_UPDATE"] = "false"

    def _acknowledge_sdk_banner(self) -> None:
        if not self.settings.auto_acknowledge_banner:
            return
        try:
            download = importlib.import_module("cloakbrowser.download")
            cache_dir = Path(download.get_cache_dir()).expanduser()
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / ".welcome_shown").write_text(str(int(time.time())))
        except Exception:
            return

    def call(
        self, tool_name: str, args: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        if self.manager is None:
            return {"error": "adapter has no session manager", "tool": tool_name}
        try:
            page = self.manager.page_for(
                task_id=kwargs.get("task_id"), session_id=kwargs.get("session_id")
            )
            handlers = {
                "browser_navigate": self._navigate,
                "browser_snapshot": self._snapshot,
                "browser_click": self._click,
                "browser_type": self._type,
                "browser_scroll": self._scroll,
                "browser_back": self._back,
                "browser_press": self._press,
                "browser_console": self._console,
                "browser_get_images": self._get_images,
                "browser_dialog": self._dialog,
                "browser_vision": self._vision,
            }
            handler = handlers.get(tool_name)
            if handler is None:
                return {"error": "unsupported browser tool", "tool": tool_name}
            return self._redact_value(handler(page, args or {}))
        except Exception as exc:
            return {"error": self._redact_text(str(exc), limit=1000), "tool": tool_name}

    def _navigate(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        url = args.get("url")
        if not url:
            raise ValueError("url is required")
        self._assert_safe_url(str(url))
        response = self.run(
            page.goto(str(url), wait_until=args.get("wait_until", "load"))
        )
        current_url = getattr(page, "url", str(url))
        self._assert_safe_page_url(current_url)
        self._clear_ref_map(page)
        title = ""
        page_title = getattr(page, "title", None)
        if callable(page_title):
            try:
                title = str(self.run(page_title()) or "")
            except Exception:
                title = ""
        snapshot_result = self._snapshot(page, {"full": False})
        result = {
            "success": True,
            "url": current_url,
            "title": title,
            "status": getattr(response, "status", None),
            "ok": getattr(response, "ok", None),
        }
        for key in ("snapshot", "element_count", "pending_dialogs", "frame_tree"):
            if key in snapshot_result:
                result[key] = snapshot_result[key]
        return result

    def _snapshot(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        self._assert_safe_page_url(getattr(page, "url", None))
        accessibility = getattr(page, "accessibility", None)
        snapshot_method = getattr(accessibility, "snapshot", None)
        source = "accessibility"
        full = bool(args.get("full", False))
        if callable(snapshot_method):
            try:
                snapshot = self.run(snapshot_method(interesting_only=not full))
            except TypeError:
                snapshot = self.run(snapshot_method())
        else:
            source = "dom-text-fallback"
            snapshot = self.run(
                page.evaluate("() => document.body ? document.body.innerText : ''")
            )
        self._assert_safe_page_url(getattr(page, "url", None))
        ref_map: dict[str, Any] = {}
        text = self._snapshot_text(snapshot, ref_map=ref_map)
        if source == "dom-text-fallback" and not ref_map:
            ref_map = self._dom_fallback_ref_map(page)
            if ref_map:
                text = self._merge_dom_fallback_snapshot_text(page, text, ref_map)
        setattr(page, "_cloak_ref_map", ref_map)
        result = {
            "success": True,
            "snapshot": text,
            "source": source,
            "url": getattr(page, "url", None),
            "refs": sorted(ref_map),
            "element_count": len(ref_map),
        }
        dialogs = self._public_dialogs(list(getattr(page, "_cloak_pending_dialogs", []) or []))
        if dialogs:
            result["pending_dialogs"] = dialogs
        return result

    def _snapshot_text(
        self, snapshot: Any, indent: int = 0, ref_map: dict[str, Any] | None = None
    ) -> str:
        if isinstance(snapshot, str):
            return snapshot
        if isinstance(snapshot, dict):
            label = " ".join(
                str(snapshot.get(key, ""))
                for key in ("role", "name")
                if snapshot.get(key)
            ).strip()
            ref = None
            target = self._target_from_snapshot_node(snapshot)
            if ref_map is not None and target is not None:
                ref = f"@e{len(ref_map) + 1}"
                ref_map[ref] = target
            prefix = f"[{ref}] " if ref else ""
            lines = [("  " * indent) + prefix + label] if label else []
            for child in snapshot.get("children", []) or []:
                text = self._snapshot_text(child, indent + 1, ref_map)
                if text:
                    lines.append(text)
            return "\n".join(lines)
        return json.dumps(snapshot, ensure_ascii=False)

    def _merge_dom_fallback_snapshot_text(
        self, page: Any, text: str, ref_map: dict[str, Any]
    ) -> str:
        metadata = getattr(page, "_cloak_ref_metadata", {}) or {}
        lines = [text.strip()] if text and text.strip() else []
        interactive_lines: list[str] = []
        for ref in sorted(ref_map, key=lambda item: self._annotation_badge_number(item, 0)):
            label = ""
            if isinstance(metadata, dict) and isinstance(metadata.get(ref), dict):
                role = str(metadata[ref].get("role") or "").strip()
                name = str(metadata[ref].get("text") or "").strip()
                label = " ".join(part for part in (role, name) if part).strip()
            if not label:
                label = "interactive element"
            interactive_lines.append(f"[{ref}] {label}")
        if interactive_lines:
            if lines:
                lines.append("")
            lines.append("Interactive elements:")
            lines.extend(interactive_lines)
        return "\n".join(lines)

    def _click(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        locator = self._locator(page, self._selector(args))
        self.run(locator.click())
        return {"clicked": True}

    def _type(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        locator = self._locator(page, self._selector(args))
        text = str(args.get("text", ""))
        fill = getattr(locator, "fill", None)
        if callable(fill):
            self.run(fill(text))
        else:
            self.run(locator.type(text))
        return {"typed": True}

    def _scroll(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        direction = str(args.get("direction", "down")).lower()
        amount = int(args.get("amount", 700))
        dy = -amount if direction == "up" else amount
        self.run(page.mouse.wheel(0, dy))
        return {"scrolled": direction, "amount": amount}

    def _back(self, page: Any, _args: dict[str, Any]) -> dict[str, Any]:
        response = self.run(page.go_back())
        self._assert_safe_page_url(getattr(page, "url", None))
        self._clear_ref_map(page)
        return {
            "url": getattr(page, "url", None),
            "status": getattr(response, "status", None),
            "ok": getattr(response, "ok", None),
        }

    def _press(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        key = args.get("key")
        if not key:
            raise ValueError("key is required")
        self.run(page.keyboard.press(key))
        return {"pressed": key}

    def _console(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        self._assert_safe_page_url(getattr(page, "url", None))
        result: dict[str, Any] = {}
        if "expression" in args and args.get("expression") is not None:
            expression = str(args.get("expression"))
            if len(expression) > 4000:
                raise ValueError("expression is too long")
            result["result"] = self.run(page.evaluate(expression))
            self._assert_safe_page_url(getattr(page, "url", None))
        messages = getattr(page, "_cloak_console_messages", None)
        if messages is None or (
            not self._console_messages_list(messages) and hasattr(page, "console_messages")
        ):
            messages = self._page_console_messages(page)
        result["messages"] = self._console_messages_list(messages)[-200:]
        if args.get("clear") and hasattr(messages, "clear"):
            messages.clear()
        return result

    def _page_console_messages(self, page: Any) -> Any:
        messages = getattr(page, "console_messages", [])
        if callable(messages):
            return self.run(messages())
        return messages

    def _console_messages_list(self, messages: Any) -> list[Any]:
        if messages is None:
            return []
        return list(messages)

    def _get_images(self, page: Any, _args: dict[str, Any]) -> dict[str, Any]:
        self._assert_safe_page_url(getattr(page, "url", None))
        images = self.run(
            page.evaluate(
                "() => Array.from(document.images).map(img => ({"
                "src: img.currentSrc || img.src || '', alt: img.alt || '', "
                "width: img.naturalWidth || img.width || 0, height: img.naturalHeight || img.height || 0}))"
            )
        )
        self._assert_safe_page_url(getattr(page, "url", None))
        safe_images = []
        for image in images or []:
            src = str(image.get("src", "")) if isinstance(image, dict) else ""
            if not self._is_returnable_url(src):
                continue
            safe_images.append(image)
        return {"images": safe_images}

    def _dialog(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        self._assert_safe_page_url(getattr(page, "url", None))
        dialog_store = getattr(page, "_cloak_dialogs", None)
        dialogs = list(dialog_store or [])[-20:]
        action = args.get("action")
        if action:
            if action not in {"accept", "dismiss"}:
                raise ValueError("action must be accept or dismiss")
            if not dialogs:
                return {"handled": False, "count": 0, "dialogs": []}
            index = int(args.get("index", -1))
            dialog = dialogs[index]
            handle = dialog.get("_handle") if isinstance(dialog, dict) else None
            if handle is None:
                return {"handled": False, "count": len(dialogs), "dialogs": self._public_dialogs(dialogs)}
            if action == "accept":
                accept = getattr(handle, "accept", None)
                if not callable(accept):
                    raise ValueError("dialog cannot be accepted")
                prompt_text = args.get("prompt_text")
                if prompt_text is None:
                    self.run(accept())
                else:
                    self.run(accept(str(prompt_text)))
            else:
                dismiss = getattr(handle, "dismiss", None)
                if not callable(dismiss):
                    raise ValueError("dialog cannot be dismissed")
                self.run(dismiss())
            if isinstance(dialog, dict):
                dialog["handled"] = True
                dialog.pop("_handle", None)
                handled_store = getattr(page, "_cloak_handled_dialogs", None)
                append_handled = getattr(handled_store, "append", None)
                if callable(append_handled):
                    append_handled(dict(dialog))
            remove_dialog = getattr(dialog_store, "remove", None)
            if callable(remove_dialog):
                try:
                    remove_dialog(dialog)
                except ValueError:
                    pass
            remaining = list(dialog_store or [])[-20:]
            return {"handled": True, "action": action, "count": len(remaining)}
        public = self._public_dialogs(dialogs)
        return {
            "count": len(public),
            "latest": public[-1] if public else None,
            "dialogs": public,
        }

    def _public_dialogs(self, dialogs: list[Any]) -> list[dict[str, Any]]:
        public = []
        for idx, dialog in enumerate(dialogs):
            if not isinstance(dialog, dict):
                continue
            public.append(
                {
                    "index": idx,
                    "type": dialog.get("type", "dialog"),
                    "message": dialog.get("message", ""),
                    "default_value": dialog.get("default_value", ""),
                }
            )
        return public

    def _vision(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        self._assert_safe_page_url(getattr(page, "url", None))
        screenshot = getattr(page, "screenshot", None)
        if not callable(screenshot):
            raise ValueError("page does not support screenshots")
        path = self._new_screenshot_path()
        options = {
            "path": str(path),
            "type": "png",
            "full_page": bool(args.get("full_page", False)),
        }
        self.run(screenshot(**options))
        self._assert_safe_page_url(getattr(page, "url", None))
        if not path.exists():
            data = self.run(screenshot(type="png"))
            if isinstance(data, bytes):
                path.write_bytes(data)
        annotated = False
        labels: list[dict[str, Any]] = []
        if args.get("annotate"):
            labels = self._annotation_labels(page)
            annotated = self._write_annotated_screenshot(path, labels)
        question = str(args.get("question") or "Describe what is visible in this browser screenshot.")
        result: dict[str, Any] = self._vision_analysis(path, question)
        result.update(
            {
                "success": True,
                "screenshot_path": str(path),
                "mime_type": "image/png",
                "annotated": annotated,
            }
        )
        if args.get("annotate"):
            result["labels"] = [label["ref"] for label in labels]
            result["badge_to_ref"] = {str(label["badge"]): label["ref"] for label in labels}
            if not annotated:
                result["note"] = "No drawable interactive element bounds were available for annotation."
        return result

    def _vision_analysis(self, path: Path, question: str) -> dict[str, Any]:
        import base64

        from tools.vision_tools import (
            _build_native_vision_tool_result,
            _should_use_native_vision_fast_path,
            vision_analyze_tool,
        )

        image_bytes = path.read_bytes()
        data_url = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"

        if _should_use_native_vision_fast_path():
            native_result = _build_native_vision_tool_result(
                image_url=str(path),
                question=question,
                image_data_url=data_url,
                image_size_bytes=len(image_bytes),
            )
            meta = native_result.setdefault("meta", {})
            meta["screenshot_path"] = str(path)
            return native_result

        analysis = self.run(vision_analyze_tool(str(path), question))
        if isinstance(analysis, str):
            parsed = json.loads(analysis)
            if isinstance(parsed, dict):
                parsed.setdefault(
                    "analysis", parsed.get("analysis") or "Vision analysis returned no content."
                )
                return parsed
        if isinstance(analysis, dict):
            analysis.setdefault(
                "analysis", analysis.get("analysis") or "Vision analysis returned no content."
            )
            return analysis
        return {"analysis": str(analysis) or "Vision analysis returned no content."}

    def _new_screenshot_path(self) -> Path:
        if self.manager is not None:
            new_path = getattr(self.manager, "new_screenshot_path", None)
            if callable(new_path):
                path = new_path()
                if isinstance(path, Path):
                    return path
                return Path(str(path))
        raise RuntimeError("adapter has no screenshot temp lifecycle manager")

    def _annotation_labels(self, page: Any) -> list[dict[str, Any]]:
        ref_map = getattr(page, "_cloak_ref_map", {}) or {}
        if not ref_map:
            self._snapshot(page, {})
            ref_map = getattr(page, "_cloak_ref_map", {}) or {}
        labels = self._labels_from_ref_map(page, ref_map)
        if labels:
            return labels
        dom_refs = self._dom_fallback_ref_map(page)
        if dom_refs:
            setattr(page, "_cloak_ref_map", dom_refs)
            return self._labels_from_ref_map(page, dom_refs)
        return []

    def _labels_from_ref_map(
        self, page: Any, ref_map: dict[str, Any]
    ) -> list[dict[str, Any]]:
        refs = list(ref_map)[:99]
        selectors = [str(ref_map[ref]) for ref in refs]
        boxes = self._dom_bounding_boxes(page, selectors)
        labels: list[dict[str, Any]] = []
        for ref, box in zip(refs, boxes, strict=False):
            if not isinstance(box, dict):
                continue
            width = float(box.get("width") or 0)
            height = float(box.get("height") or 0)
            if width <= 0 or height <= 0:
                continue
            label = {
                "ref": ref,
                "badge": self._annotation_badge_number(ref, len(labels) + 1),
                "x": max(0.0, float(box.get("x") or 0)),
                "y": max(0.0, float(box.get("y") or 0)),
                "width": width,
                "height": height,
            }
            for key in ("text", "role", "selector"):
                if box.get(key):
                    label[key] = box[key]
            metadata = getattr(page, "_cloak_ref_metadata", {}) or {}
            if isinstance(metadata, dict) and isinstance(metadata.get(ref), dict):
                for key in ("text", "role"):
                    if metadata[ref].get(key) and key not in label:
                        label[key] = metadata[ref][key]
            labels.append(label)
        return labels

    def _annotation_badge_number(self, ref: str, fallback: int) -> int:
        match = re.fullmatch(r"@e(\d+)", str(ref))
        if match:
            return int(match.group(1))
        return fallback

    def _dom_fallback_ref_map(self, page: Any) -> dict[str, str]:
        script = r"""
        () => {
          const uniqueSelectorFor = (el) => {
            const isUnique = (selector) => {
              try {
                return document.querySelectorAll(selector).length === 1;
              } catch (_error) {
                return false;
              }
            };
            if (el.id) {
              const selector = `#${CSS.escape(el.id)}`;
              if (isUnique(selector)) return selector;
            }
            const parts = [];
            let node = el;
            while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.body) {
              const tag = node.tagName.toLowerCase();
              const parent = node.parentElement;
              if (!parent) break;
              const siblings = Array.from(parent.children).filter((child) => child.tagName === node.tagName);
              const index = siblings.indexOf(node) + 1;
              parts.unshift(`${tag}:nth-of-type(${index})`);
              const selector = parts.join(' > ');
              if (selector && isUnique(selector)) return selector;
              node = parent;
            }
            const selector = parts.length ? parts.join(' > ') : el.tagName.toLowerCase();
            return selector && isUnique(selector) ? selector : null;
          };
          const visible = (el) => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 && rect.bottom >= 0 && rect.right >= 0 &&
              rect.top <= window.innerHeight && rect.left <= window.innerWidth &&
              style.visibility !== 'hidden' && style.display !== 'none' && style.pointerEvents !== 'none';
          };
          const candidates = Array.from(document.querySelectorAll(
            'a[href], button, input, select, textarea, [role="button"], [role="link"], [role="menuitem"], [role="tab"], summary, label'
          ));
          const refs = [];
          for (const el of candidates) {
            if (refs.length >= 99) break;
            if (!visible(el)) continue;
            const selector = uniqueSelectorFor(el);
            if (!selector) continue;
            const ref = `@e${refs.length + 1}`;
            const text = (el.getAttribute('aria-label') || el.innerText || el.value || el.alt || '').trim().slice(0, 120);
            refs.push({ref, selector, text, role: el.getAttribute('role') || el.tagName.toLowerCase()});
          }
          return refs;
        }
        """
        evaluate = getattr(page, "evaluate", None)
        if not callable(evaluate):
            return {}
        try:
            elements = self.run(evaluate(script)) or []
        except Exception:
            return {}
        ref_map: dict[str, str] = {}
        metadata: dict[str, dict[str, Any]] = {}
        for item in elements:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("ref") or "")
            selector = str(item.get("selector") or "")
            if not re.fullmatch(r"@e\d+", ref) or not selector:
                continue
            ref_map[ref] = selector
            metadata[ref] = {
                key: item[key] for key in ("text", "role") if item.get(key)
            }
        setattr(page, "_cloak_ref_metadata", metadata)
        return ref_map

    def _dom_bounding_boxes(self, page: Any, selectors: list[str]) -> list[Any]:
        if not selectors:
            return []
        script = """
        (selectors) => selectors.map((selector) => {
          try {
            const node = document.querySelector(selector);
            if (!node) return null;
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            if (style.visibility === 'hidden' || style.display === 'none') return null;
            return {
              x: rect.left,
              y: rect.top,
              width: rect.width,
              height: rect.height,
              selector,
              role: node.getAttribute('role') || node.tagName.toLowerCase(),
              text: (node.getAttribute('aria-label') || node.innerText || node.value || node.alt || '').trim().slice(0, 120),
            };
          } catch (_error) {
            return null;
          }
        })
        """
        evaluate = getattr(page, "evaluate", None)
        if not callable(evaluate):
            return []
        try:
            return list(self.run(evaluate(script, selectors)) or [])
        except TypeError:
            selector_json = json.dumps(selectors)
            fallback_script = f"""
            () => {selector_json}.map((selector) => {{
              try {{
                const node = document.querySelector(selector);
                if (!node) return null;
                const rect = node.getBoundingClientRect();
                return {{x: rect.left, y: rect.top, width: rect.width, height: rect.height}};
              }} catch (_error) {{
                return null;
              }}
            }})
            """
            return list(self.run(evaluate(fallback_script)) or [])

    def _write_annotated_screenshot(self, path: Path, labels: list[dict[str, Any]]) -> bool:
        if not labels:
            return False
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return False
        try:
            image = Image.open(path).convert("RGBA")
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default()
            for label in labels:
                x = int(label["x"])
                y = int(label["y"])
                width = int(label["width"])
                height = int(label["height"])
                draw.rectangle((x, y, x + width, y + height), outline=(255, 80, 0, 255), width=3)
                text = str(label.get("badge") or "")
                text_box = draw.textbbox((0, 0), text, font=font)
                text_width = text_box[2] - text_box[0]
                text_height = text_box[3] - text_box[1]
                badge = (x, y, x + text_width + 8, y + text_height + 6)
                draw.rounded_rectangle(badge, radius=4, fill=(255, 80, 0, 230))
                draw.text((x + 4, y + 3), text, fill=(255, 255, 255, 255), font=font)
            image.convert("RGB").save(path, format="PNG")
            return True
        except Exception:
            return False

    def _selector(self, args: dict[str, Any]) -> str:
        selector = args.get("selector") or args.get("ref")
        if not selector:
            raise ValueError("selector or ref is required")
        return str(selector)

    def _locator(self, page: Any, selector_or_ref: str) -> Any:
        target = selector_or_ref
        if selector_or_ref.startswith("@e"):
            ref_map = getattr(page, "_cloak_ref_map", {}) or {}
            if selector_or_ref not in ref_map:
                raise ValueError(f"unknown browser ref: {selector_or_ref}")
            target = ref_map[selector_or_ref]
            if hasattr(target, "click") or hasattr(target, "fill"):
                return target
        locator = getattr(page, "locator", None)
        if callable(locator):
            return locator(str(target))
        query_selector = getattr(page, "query_selector", None)
        if callable(query_selector):
            element = self.run(query_selector(str(target)))
            if element is not None:
                return element
        raise ValueError(
            f"element not found: {self._redact_text(str(selector_or_ref), limit=200)}"
        )

    def _target_from_snapshot_node(self, node: dict[str, Any]) -> Any | None:
        for key in ("element", "handle", "selector", "ref"):
            value = node.get(key)
            if value:
                return value
        role = node.get("role")
        name = node.get("name")
        if role and name:
            safe_name = str(name).replace('"', '\\"')
            return f'internal:role={role}[name="{safe_name}"]'
        return None

    def _clear_ref_map(self, page: Any) -> None:
        setattr(page, "_cloak_ref_map", {})

    def _assert_safe_page_url(self, url: Any) -> None:
        if url:
            self._assert_safe_url(str(url), for_navigation=False)

    def _assert_safe_url(self, url: str, *, for_navigation: bool = True) -> None:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme in {"about"} and url == "about:blank":
            return
        if scheme in {"data", "blob", "file", "ftp", "javascript"}:
            raise ValueError("blocked unsafe browser URL scheme")
        if scheme not in {"http", "https"}:
            if for_navigation:
                raise ValueError("blocked unsupported browser URL scheme")
            return
        if parts.username or parts.password:
            raise ValueError("blocked URL with embedded credentials")
        host = (parts.hostname or "").strip().lower().rstrip(".")
        if not host:
            raise ValueError("blocked URL without host")
        if host in BLOCKED_HOSTS:
            raise ValueError("blocked private or metadata browser URL")
        ips = self._resolve_host_ips(host)
        if host in METADATA_IPS or any(self._is_blocked_ip(ip) for ip in ips):
            raise ValueError("blocked private or metadata browser URL")

    def _resolve_host_ips(self, host: str) -> list[Any]:
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            pass
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError:
            return []
        ips = []
        for info in infos:
            try:
                ips.append(ipaddress.ip_address(info[4][0]))
            except (ValueError, IndexError):
                continue
        return ips

    def _is_blocked_ip(self, ip: Any) -> bool:
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )

    def _is_returnable_url(self, url: str) -> bool:
        if not url:
            return False
        try:
            self._assert_safe_url(url, for_navigation=False)
        except ValueError:
            return False
        return urlsplit(url).scheme.lower() in {"http", "https"}

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact_text(value)
        if isinstance(value, list):
            return [self._redact_value(item) for item in value][-500:]
        if isinstance(value, tuple):
            return [self._redact_value(item) for item in value][-500:]
        if isinstance(value, dict):
            return {str(key): self._redact_value(item) for key, item in value.items()}
        return value

    def _redact_text(self, text: str, *, limit: int = MAX_REDACTED_TEXT) -> str:
        redacted = text
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub(
                lambda m: (m.group(1) if m.groups() else "") + "[REDACTED]", redacted
            )
        redacted = self._redact_urls(redacted)
        if len(redacted) > limit:
            return redacted[:limit] + "…[truncated]"
        return redacted

    def _redact_urls(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            return self._redact_url(match.group(0))

        return re.sub(r"https?://[^\s'\"<>]+", repl, text)

    def _redact_url(self, url: str) -> str:
        parts = urlsplit(url)
        netloc = parts.hostname or ""
        if parts.port:
            netloc += f":{parts.port}"
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            query.append(
                (key, "[REDACTED]" if SENSITIVE_QUERY_KEYS.search(key) else value)
            )
        return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), ""))
