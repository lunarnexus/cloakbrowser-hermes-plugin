# INSTALL

Install the CloakBrowser direct-SDK Hermes plugin foundation.

This installs the Hermes plugin only. It does not configure any external browser server. Browser tool calls launch and reuse a plugin-owned persistent CloakBrowser SDK context when the SDK is importable and config is valid.

## 1) Install CloakBrowser SDK dependency

Install the `cloakbrowser` Python package into the same Python environment that runs Hermes. Use the package/source approved for your deployment.

Example install into the Hermes-managed runtime shown in this repo's docs:

```bash
~/.local/share/uv/tools/hermes-agent/bin/python -m pip install 'cloakbrowser>=0.4.10'
```

If your Hermes install uses a different runtime, run `python -m pip install 'cloakbrowser>=0.4.10'` with that Hermes runtime's Python. Version 0.4.10 is required because it fixes humanized interactions inside iframes, including embedded challenge and authentication UI.

Do not treat a generic `python3` import check as proof that Hermes can import the package. Runtime verification happens later from inside a fresh Hermes session.

## 2) Install the Hermes plugin

Preferred install path:

```bash
hermes plugins install https://github.com/<owner>/cloakbrowser-hermes-plugin.git --enable
hermes plugins enable cloakbrowser-hermes-plugin --allow-tool-override
```

After publication, GitHub shorthand is also supported by Hermes:

```bash
hermes plugins install <owner>/cloakbrowser-hermes-plugin --enable
hermes plugins enable cloakbrowser-hermes-plugin --allow-tool-override
```

Update an installed plugin with:

```bash
hermes plugins update cloakbrowser-hermes-plugin
```

Start a new Hermes session after install or update.

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

`auto_acknowledge_banner` writes a fresh integer Unix timestamp to CloakBrowser's `.welcome_shown` marker in `cloakbrowser.download.get_cache_dir()` before SDK launch. Marker write failures are non-fatal and do not block launch.

`auto_update` controls the SDK auto-update environment only when explicitly disabled. Environment precedence is strict: an existing `CLOAKBROWSER_AUTO_UPDATE` value always wins and is never overwritten. If `auto_update: false` and the env var is absent, the plugin sets `CLOAKBROWSER_AUTO_UPDATE=false` before launch. If `auto_update` is omitted, `null`, or `true`, the plugin leaves SDK defaults and the environment unchanged.

`fingerprint_seed` is supported in this plugin slice via the documented wrapper-equivalent flag form. When set, the plugin appends `--fingerprint=<seed>` to the SDK `args` list unless `args` already contains an explicit `--fingerprint=...` value; in that case the explicit arg wins and the plugin emits a config warning.

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

This is runtime verification for active Hermes/mina session, not proof from arbitrary shell Python.

Important: `/cloak status` is not proof of anti-bot parity or Reddit/login success. In particular, `headless: true` parity with the earlier wrapper setup remains unproven until live verification covers challenge handling, click resilience, and fingerprint coherence.

Also still blocked in this slice: headed viewport auto-derive parity. Current public CloakBrowser Python docs document `viewport` on `launch_context()` / `launch_persistent_context()`, but this plugin routes through runtime-selected `create()` / `launch_persistent_context()` factories and no installed SDK signature/source was available here to prove safe `create()` viewport wiring.

For real mina verification, run the check inside target Hermes/mina runtime:
- start fresh session for profile under test
- run `/cloak status`
- confirm plugin reports ready and browser overrides are registered
- if deployment expects headed use (`headless: false`), run one real browser smoke in that same mina session

## Disable

```bash
hermes plugins disable cloakbrowser-hermes-plugin
```

Then start a new Hermes session.
