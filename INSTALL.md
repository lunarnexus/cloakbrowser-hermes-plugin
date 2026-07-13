# INSTALL

Install the CloakBrowser direct-SDK Hermes plugin foundation.

This slice installs the Hermes plugin only. It does not configure any external browser server. Browser launch/navigation implementation is intentionally fail-closed until the next implementation slice.

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
```

Safety rules for `user_data_dir`:
- Use a dedicated CloakBrowser profile directory.
- Do not use `/`, the home directory, the repository root, common browser profile directories, symlinked paths, or another Hermes profile directory.
- The default active-profile path is safest: `~/.hermes/profiles/<profile>/browser-profiles/cloakbrowser`.

## 4) First-run check

In a fresh Hermes session:

```text
/cloak status
```

Expected for this foundation slice:
- `/cloak status` returns readiness and high-level state only.
- Status does not expose profile paths, session IDs, cookies, or URLs.
- If `cloakbrowser` is not importable, browser tool overrides are not registered.
- If `cloakbrowser` is importable and config is valid, browser tool overrides register but fail closed with the current safe placeholder error.

## Disable

```bash
hermes plugins disable cloakbrowser-hermes-plugin
```

Then start a new Hermes session.
