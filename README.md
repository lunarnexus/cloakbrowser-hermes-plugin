# cloakbrowser-hermes-plugin

Cloak Browser support for Hermes Agent, as a plugin.  
This plugin overrides the built-in `browser_*` tool family and routes through the CloakBrowser Python SDK.

Current foundation behavior:
- Registers `/cloak status` and `/cloak help`.
- Overrides `browser_*` tools only when config is valid and the `cloakbrowser` Python package is importable.
- Launches and reuses a persistent CloakBrowser context for browser tool calls.
- Redacts local profile paths from status output.
- Uses a dedicated persistent profile directory by default under the active Hermes profile.
- Shares one persistent CloakBrowser profile/login per canonical `user_data_dir` within the current Hermes process, so same-profile root sessions and delegated work can reuse auth state. Task/session isolation is per-page state, refs, and console buffers, not separate login profiles. Cross-process profile locking is left to CloakBrowser/Chromium.  This means only one concurrent CloakBrowser instance per profile.  I may fix this in the future, but it causes security problems. 

## Requirements

1. Hermes Agent, obviously.
2. The CloakBrowser Python SDK installed in the Hermes venv: `python -m pip install cloakbrowser`.
   Package reference: https://pypi.org/project/cloakbrowser/ (`CloakHQ/CloakBrowser`).
3. A local desktop session for future browser sessions (headless=false).

## Install

Use the official Hermes plugin workflow:

```bash
hermes plugins install https://github.com/<owner>/cloakbrowser-hermes-plugin.git --enable
```

Or, after the repository is published under GitHub shorthand:

```bash
hermes plugins install <owner>/cloakbrowser-hermes-plugin --enable
```

Start a new Hermes session after enabling the plugin.

## Local development install

For a workspace checkout, install or link the plugin using the Hermes plugin workflow for your active profile. Example development layout:

```bash
hermes plugins install /absolute/path/to/cloakbrowser-hermes-plugin --enable
```

If your Hermes version does not support local path installs, place the checkout under the active profile plugin directory and enable it:

```bash
mkdir -p ~/.hermes/profiles/<profile>/plugins
ln -sfn /absolute/path/to/cloakbrowser-hermes-plugin \
  ~/.hermes/profiles/<profile>/plugins/cloakbrowser-hermes-plugin
hermes plugins enable cloakbrowser-hermes-plugin
```

Replace `<profile>` with the Hermes profile you intend to use. Plugin changes take effect in a new session.

## Configuration

Configure runtime options under the plugin entry:

```yaml
plugins:
  entries:
    cloakbrowser-hermes-plugin:
      enabled: true
      config:
        user_data_dir: ~/.hermes/profiles/<profile>/browser-profiles/cloakbrowser
        headless: false
        humanize: true
        human_preset: default
        stealth_args: true
        geoip: false
        proxy: null
        locale: null
        timezone: null
        color_scheme: null
        user_agent: null
        args: []
        # Write CloakBrowser SDK banner marker before launch. Default: true.
        auto_acknowledge_banner: true
        # Optional tri-state. Omit/null or true leaves SDK/env behavior unchanged.
        # false sets CLOAKBROWSER_AUTO_UPDATE=false only when the env var is absent.
        auto_update: null
```

Install the CloakBrowser SDK into the Hermes virtualenv used by the target profile:

```bash
~/.local/share/uv/tools/hermes-agent/bin/python -m pip install cloakbrowser
```

If your Hermes install uses a different venv, run `python -m pip install cloakbrowser` with that Hermes venv's Python.

`auto_acknowledge_banner` writes a fresh integer Unix timestamp to CloakBrowser's `.welcome_shown` marker in `cloakbrowser.download.get_cache_dir()` before SDK launch. Marker write failures are ignored so launch is not blocked.

`auto_update` respects environment precedence. If `CLOAKBROWSER_AUTO_UPDATE` is already set, the plugin never overwrites it. If `auto_update` is omitted, `null`, or `true`, the plugin leaves SDK/env behavior unchanged. If `auto_update: false` and the env var is absent, the plugin sets `CLOAKBROWSER_AUTO_UPDATE=false` before launch.

`user_data_dir` must be a dedicated CloakBrowser profile directory. The plugin rejects dangerous locations such as `/`, the home directory, the repository root, common browser profile directories, symlinked paths, and other Hermes profile directories outside the current profile-owned CloakBrowser path.

## Usage

Slash commands in this foundation slice:

```text
/cloak status
/cloak help
```

`/cloak status` reports readiness and high-level state only. It does not print profile paths, session IDs, cookies, or URLs.

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
