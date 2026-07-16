# cloakbrowser-hermes-plugin

Cloak Browser support for Hermes Agent, as a plugin.  
This plugin overrides the built-in `browser_*` tool family and routes through the CloakBrowser Python SDK.

Current foundation behavior:
- Registers `/cloak status` and `/cloak help`.
- Overrides `browser_*` tools only when config is valid and the `cloakbrowser` Python package is importable.
- Launches and reuses a CloakBrowser persistent-profile context within the current Hermes process when the profile key remains live.
- Redacts local profile paths from status output.
- Uses a dedicated persistent profile directory by default under the active Hermes profile.
- Shares one persistent CloakBrowser profile/login per canonical `user_data_dir` within the current Hermes process, so same-profile root sessions and delegated work can reuse auth state. Task/session isolation is per-page state, refs, and console buffers, not separate login profiles. Cross-process profile locking is left to CloakBrowser/Chromium. This means only one concurrent CloakBrowser instance per profile.
- `browser_type` now supports humanized field entry: focus/click, keyboard clear, uneven per-character delays, and optional Enter submit.

## Current anti-bot status and limits

What is implemented now:
- CloakBrowser SDK launch with `humanize`, `human_preset`, `stealth_args`, persistent `user_data_dir`, and optional `proxy` / `locale` / `timezone` / `color_scheme` / `user_agent` config.
- `fingerprint_seed` config, wired through the currently documented Python wrapper equivalent: injected `args += ["--fingerprint=<seed>"]` when no explicit `--fingerprint=...` arg is already present.
- Humanized auth-sensitive typing behavior in `browser_type`.
- Same-profile persistent login reuse through shared `user_data_dir`.

What is still missing versus the earlier wrapper behavior:
- headed screen auto-detect / auto-derived viewport parity
- humanized mouse choreography beyond the current retrying click path

Practical implication:
- `browser_navigate` now uses `domcontentloaded`, a DOM-settle wait, and a short challenge-title pause when titles such as `Checking...` or `Just a moment...` appear.
- `browser_click` now retries once after a short pause, but full Reddit/login success still remains unproven.
- `headless: true` Reddit/login remains unproven and should not be treated as equivalent to the earlier wrapper setup until live verification covers fingerprint coherence and full challenge completion behavior.
- A Chrome-like user agent alone is not enough; cross-signal fingerprint coherence still has to be validated in live runtime behavior.
- Headed viewport parity is still blocked in this plugin slice: current public CloakBrowser Python docs document `viewport` on `launch_context()` / `launch_persistent_context()`, but this plugin routes through runtime-selected `create()` / `launch_persistent_context()` factories and no installed SDK/signature evidence was available here to prove safe `create()` viewport wiring.
- Historically successful native Hermes integration likely benefited more from persistent headed continuity and no per-turn teardown than from richer wrapper-side click/type/wait choreography.

For the detailed evidence-backed comparison, see `PLAN.md`, section `Evidence-based Anti-Bot Inventory (2026-07-15 refresh)`.

## Requirements

1. Hermes Agent, obviously.
2. CloakBrowser 0.4.10 or newer installed in the Hermes venv: `python -m pip install 'cloakbrowser>=0.4.10'`.
   Package reference: https://pypi.org/project/cloakbrowser/ (`CloakHQ/CloakBrowser`).
3. A local desktop session for future browser sessions (headless=false).

## Install

Use the official Hermes plugin workflow. `hermes plugins install` accepts a Git URL or GitHub `owner/repo` shorthand.

```bash
hermes plugins install https://github.com/<owner>/cloakbrowser-hermes-plugin.git --enable
hermes plugins enable cloakbrowser-hermes-plugin --allow-tool-override
```

Or:

```bash
hermes plugins install <owner>/cloakbrowser-hermes-plugin --enable
hermes plugins enable cloakbrowser-hermes-plugin --allow-tool-override
```

Update an installed plugin with:

```bash
hermes plugins update cloakbrowser-hermes-plugin
```

Start a new Hermes session after install or update.

## Configuration

Configure runtime options under the plugin entry:

```yaml
plugins:
  entries:
    cloakbrowser-hermes-plugin:
      enabled: true
      allow_tool_override: true
      config:
        user_data_dir: ~/.hermes/profiles/<profile>/browser-profiles/cloakbrowser
        headless: false
        humanize: true
        human_preset: default
        stealth_args: true
        geoip: false
        # Optional fingerprint identity seed. Current plugin maps this to
        # args: ["--fingerprint=<seed>"] because current public Python docs do
        # not document a first-class fingerprint_seed launch kwarg.
        # fingerprint_seed: "stable-profile-a"
        args: []
        # Optional strings: omit when unset.
        # proxy: ""
        # locale: ""
        # timezone: ""
        # color_scheme: ""
        # user_agent: ""
        # Write CloakBrowser SDK banner marker before launch. Default: true.
        auto_acknowledge_banner: true
        # Optional tri-state: omit when unset.
        # auto_update: false
```

Install the CloakBrowser SDK into the Hermes runtime environment used by the target profile:

```bash
~/.local/share/uv/tools/hermes-agent/bin/python -m pip install 'cloakbrowser>=0.4.10'
```

If your Hermes install uses a different venv, run `python -m pip install 'cloakbrowser>=0.4.10'` with that Hermes runtime's Python.

`auto_acknowledge_banner` writes a fresh integer Unix timestamp to CloakBrowser's `.welcome_shown` marker in `cloakbrowser.download.get_cache_dir()` before SDK launch. Marker write failures are ignored so launch is not blocked.

`auto_update` respects environment precedence. If `CLOAKBROWSER_AUTO_UPDATE` is already set, the plugin never overwrites it. If `auto_update` is omitted, `null`, or `true`, the plugin leaves SDK/env behavior unchanged. If `auto_update: false` and the env var is absent, the plugin sets `CLOAKBROWSER_AUTO_UPDATE=false` before launch.

`fingerprint_seed` is supported in this plugin slice through the documented wrapper-equivalent flag form. When set, the plugin appends `--fingerprint=<seed>` to the SDK `args` list unless `args` already contains an explicit `--fingerprint=...` value, in which case the explicit arg wins and the plugin emits a config warning.

`user_data_dir` must be a dedicated CloakBrowser profile directory. The plugin rejects dangerous locations such as `/`, the home directory, the repository root, common browser profile directories, symlinked paths, and other Hermes profile directories outside the current profile-owned CloakBrowser path.

## Usage

Slash commands in this foundation slice:

```text
/cloak status
/cloak help
```

`/cloak status` reports readiness and high-level state only. It does not print profile paths, session IDs, cookies, or URLs.

Use `/cloak status` as runtime verification that the plugin loaded in the active Hermes session. It is not a substitute for a real headed desktop smoke test when `headless: false` is part of the target deployment.

When enabled and ready, the plugin registers these built-in browser tool overrides:

- `browser_navigate`
- `browser_snapshot`
- `browser_click`
- `browser_type`
- `browser_scroll`
- `browser_back`
- `browser_press`
- `browser_get_images`
- `browser_console`
- `browser_dialog`
- `browser_vision`

It intentionally does not override:

- `web_search`
- `web_extract`
- `browser_cdp`

## Disable

```bash
hermes plugins disable cloakbrowser-hermes-plugin
```

Then start a new Hermes session.
