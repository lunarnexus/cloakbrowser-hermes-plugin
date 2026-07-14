# INSTALL

Install the CloakBrowser direct-SDK Hermes plugin foundation.

This installs the Hermes plugin only. It does not configure any external browser server. Browser tool calls launch and reuse a plugin-owned persistent CloakBrowser SDK context when the SDK is importable and config is valid.

## 1) Install CloakBrowser SDK dependency

Install the `cloakbrowser` Python package into the same Python environment that runs Hermes. Use the package/source approved for your deployment.

Example editable source install:

```bash
python3 -m pip install -e /absolute/path/to/cloakbrowser-sdk
```

Verify importability from the Hermes runtime environment:

```bash
python3 - <<'PY'
import importlib.util
print(importlib.util.find_spec("cloakbrowser") is not None)
PY
```

Expected output: `True`.

## 2) Install the Hermes plugin

Preferred install path:

```bash
hermes plugins install https://github.com/<owner>/cloakbrowser-hermes-plugin.git --enable
```

After publication, GitHub shorthand is also supported by Hermes:

```bash
hermes plugins install <owner>/cloakbrowser-hermes-plugin --enable
```

For local development from this checkout:

```bash
hermes plugins install /absolute/path/to/cloakbrowser-hermes-plugin --enable
```

If local path installs are unavailable in your Hermes version, link the checkout into the active profile plugin directory:

```bash
mkdir -p ~/.hermes/profiles/<profile>/plugins
ln -sfn /absolute/path/to/cloakbrowser-hermes-plugin \
  ~/.hermes/profiles/<profile>/plugins/cloakbrowser-hermes-plugin
hermes plugins enable cloakbrowser-hermes-plugin
```

Replace `<profile>` with the profile being tested. Start a new Hermes session after enabling.

## 3) Configure plugin options

Configure under `plugins.entries.cloakbrowser-hermes-plugin.config`:

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

`auto_acknowledge_banner` writes a fresh integer Unix timestamp to CloakBrowser's `.welcome_shown` marker in `cloakbrowser.download.get_cache_dir()` before SDK launch. Marker write failures are non-fatal and do not block launch.

`auto_update` controls the SDK auto-update environment only when explicitly disabled. Environment precedence is strict: an existing `CLOAKBROWSER_AUTO_UPDATE` value always wins and is never overwritten. If `auto_update: false` and the env var is absent, the plugin sets `CLOAKBROWSER_AUTO_UPDATE=false` before launch. If `auto_update` is omitted, `null`, or `true`, the plugin leaves SDK defaults and the environment unchanged.

Safety rules for `user_data_dir`:
- Use a dedicated CloakBrowser profile directory.
- Do not use `/`, the home directory, the repository root, common browser profile directories, symlinked paths, or another Hermes profile directory.
- The default active-profile path is safest: `~/.hermes/profiles/<profile>/browser-profiles/cloakbrowser`.
- Within one Hermes process, the canonical `user_data_dir` is the persistent context registry key. Same-profile sessions using this path intentionally share one CloakBrowser profile/login; task/session isolation is separate pages, refs, and console buffers.

## 4) First-run check

In a fresh Hermes session:

```text
/cloak status
```

Expected for this foundation slice:
- `/cloak status` returns readiness and high-level state only.
- Status does not expose profile paths, session IDs, cookies, or URLs.
- If `cloakbrowser` is not importable, browser tool overrides are not registered.
- If `cloakbrowser` is importable and config is valid, browser tool overrides register and route calls through the direct SDK context.

## Disable

```bash
hermes plugins disable cloakbrowser-hermes-plugin
```

Then start a new Hermes session.
