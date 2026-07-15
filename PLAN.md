# CloakBrowser Hermes Plugin Rewrite Plan

> Historical note: this file is the original rewrite plan. It is not the current remaining-work checklist. Current code and tests already cover the implemented browser override set, including `browser_navigate`, `browser_snapshot`, `browser_vision`, and slash-command parsing. Remaining cleanup is tracked in the workspace cleanup plan and is currently doc/install/runtime-smoke focused.

## Goal

Rewrite `cloakbrowser-hermes-plugin` from an MCP-backed browser-tool override plugin into a standalone Hermes plugin that uses the Python `cloakbrowser` SDK directly, while preserving the existing Hermes `browser_*` tool contracts and avoiding Hermes core changes.

## Current Decision

- Target implementation: standalone Hermes plugin using direct Python `cloakbrowser` SDK.
- Explicit non-goals: no MCP runtime, no Hermes core/native backend patch, no direct copy-forward of the paused native-core experiment.
- Current stale `browser.cloakbrowser` config blocks are legacy/native-reference material only. They are not the target plugin configuration surface for this rewrite.
- Preserve current plugin value: override built-in browser tools with `ctx.register_tool(..., override=True)` and expose `/cloak`, but replace `ctx.dispatch_tool()`/MCP transport with plugin-owned direct SDK runtime state.

## Evidence-based Anti-Bot Inventory (2026-07-15 refresh)

This section is the current source-backed inventory of anti-bot / stealth / humanization techniques across:

- old MCP server (`/home/james/workspace/cloakbrowser-mcp`)
- old native integrated Hermes branch (`feat/cloakbrowser-native-browser-backend` in `/home/james/.hermes/hermes-agent`)
- current standalone plugin (`/home/james/workspace/cloakbrowser-hermes-plugin`)

Initial audit fell back to direct reads because CodeGraph was temporarily unavailable; later review confirmed the indexed repo state.

### 1. Verified MCP techniques

#### 1.1 SDK/browser launch options and fingerprint-shaping inputs

The MCP explicitly passed through these CloakBrowser knobs into `SessionConfig` and launch:

- `proxy`
- `humanize`
- `human_preset`
- `stealth_args`
- `timezone`
- `locale`
- `geoip`
- `extra_args`
- `fingerprint_seed`
- `user_data_dir`
- `viewport`
- `color_scheme`
- `user_agent`

Sources:

- `cloakbrowser-mcp/cloakbrowsermcp/server.py:195-210`
- `cloakbrowser-mcp/cloakbrowsermcp/session.py:127-149`

Important note: several of these are SDK pass-throughs, not wrapper-implemented stealth logic. But they still matter because they control fingerprint coherence at launch.

#### 1.2 Persistent profile/session reuse

The MCP supported persistent profile reuse via `user_data_dir`, switching to persistent-context launch when present.

Sources:

- `cloakbrowser-mcp/cloakbrowsermcp/server.py:205-207`
- `cloakbrowser-mcp/cloakbrowsermcp/session.py:144-145`
- `cloakbrowser-mcp/README.md:181-182`

This matters because stored cookies/local storage/account history reduce fresh-profile suspicion.

#### 1.3 Headed viewport realism

In headed mode, the MCP auto-detected usable screen size and derived a bounded viewport rather than blindly using a fixed default.

Sources:

- `cloakbrowser-mcp/cloakbrowsermcp/server.py:180-193`
- `cloakbrowser-mcp/cloakbrowsermcp/session.py:21-108`

This helps cross-signal coherence for screen/viewport/window metrics in headed mode.

#### 1.4 Smart navigation and challenge-aware waiting

The MCP did not use plain `load`. It used:

- `page.goto(..., wait_until="domcontentloaded")`
- DOM settle detection via `MutationObserver`
- special extra pause when title matched challenge-like text (`checking`, `just a moment`)

Sources:

- `cloakbrowser-mcp/cloakbrowsermcp/waiting.py:5-43`
- `cloakbrowser-mcp/cloakbrowsermcp/waiting.py:70-97`
- `cloakbrowser-mcp/cloakbrowsermcp/server.py:224-233`

This is the strongest wrapper-level anti-bot technique missing from the current plugin.

#### 1.5 Click retry / transient-failure recovery

The MCP wrapped clicks in a one-retry helper with a 500ms pause between attempts.

Sources:

- `cloakbrowser-mcp/cloakbrowsermcp/server.py:236-245`
- `cloakbrowser-mcp/cloakbrowsermcp/waiting.py:100-110`

This is not stealth by itself, but it reduces brittle failures during dynamic page/challenge churn.

#### 1.6 Humanized typing for auth-sensitive flows

The MCP implemented richer typing behavior than plain `fill()`:

- click into the field first
- pause before typing
- clear with `Control+A` then `Backspace`
- type one character at a time with uneven delays
- add occasional extra pauses at punctuation and every ~7-14 chars
- optional delayed `Enter` submit

Sources:

- `cloakbrowser-mcp/cloakbrowsermcp/server.py:248-279`
- `cloakbrowser-mcp/cloakbrowsermcp/server.py:282-306`

This was a real wrapper-level humanization technique, not just an SDK flag.

#### 1.7 Humanized drag path

The MCP also had curved, jittered drag behavior with non-center target points, variable timing, and fallback to `drag_to`.

Sources:

- `cloakbrowser-mcp/cloakbrowsermcp/server.py:337-475`

Not directly relevant to Reddit login, but it shows the MCP had additional humanized interaction logic beyond typing.

#### 1.8 Stealth-by-default documented posture

The MCP README explicitly documented these expectations:

- source-patched Chromium
- `humanize=True` by default
- `stealth_args=True` by default
- proxy + GeoIP-based timezone/locale support
- consistent fingerprinting via `fingerprint_seed`

Sources:

- `cloakbrowser-mcp/README.md:99-104`
- `cloakbrowser-mcp/README.md:173-183`

Important doc-drift caveat from the audit:

- README claims smart settle uses `networkidle + MutationObserver`, but main navigation code only does `domcontentloaded + MutationObserver`.
- README claims humanized scroll patterns, but the MCP scroll implementation is plain scroll movement, not a rich humanized scroll path.

Sources:

- `cloakbrowser-mcp/README.md:19`, `cloakbrowser-mcp/README.md:101`, `cloakbrowser-mcp/README.md:208`
- `cloakbrowser-mcp/cloakbrowsermcp/waiting.py:80-97`
- `cloakbrowser-mcp/cloakbrowsermcp/server.py:1027-1045`

These are partly docs and partly config surface, but they reflect the intended anti-bot contract of the old setup while also showing where the docs overstated the MCP Python layer.

### 2. Verified native integrated Hermes branch techniques

Important: the native branch that "worked" had less wrapper-level anti-bot logic than the old MCP. Its strength appears to have come more from native CloakBrowser launch/persistence integration than from richer interaction choreography.

#### 2.1 Native CloakBrowser provider selection and local direct launch

The branch supported a native local CloakBrowser backend selected via:

- `browser.cloud_provider: cloakbrowser`
- nested `browser.cloakbrowser.*` config

Sources:

- `feat/cloakbrowser-native-browser-backend:website/docs/user-guide/features/browser.md:310-347`
- `feat/cloakbrowser-native-browser-backend:hermes_cli/config.py:1204-1217`

#### 2.2 Launch pass-throughs actually implemented by the native branch

The native wrapper passed these options through:

- `headless`
- `humanize`
- `stealth_args`
- `user_data_dir`
- `proxy`
- `geoip`
- `locale`
- `timezone`
- `viewport_width`
- `viewport_height`
- `color_scheme`
- `user_agent`
- `extra_args`

Sources:

- `feat/cloakbrowser-native-browser-backend:tools/browser_cloakbrowser.py:91-118`
- `feat/cloakbrowser-native-browser-backend:tools/browser_cloakbrowser.py:330-359`

Notably absent from the native wrapper surface:

- no `human_preset`
- no `fingerprint_seed`
- no wrapper-level challenge settle logic

Evidence:

- `feat/cloakbrowser-native-browser-backend:tools/browser_cloakbrowser.py:91-118`

#### 2.3 Persistent context/profile reuse

The native branch used `launch_persistent_context_async` whenever `user_data_dir` was present and reused the first existing page or created a new one.

Sources:

- `feat/cloakbrowser-native-browser-backend:tools/browser_cloakbrowser.py:343-352`

#### 2.4 Page/session liveness recovery and timeout hardening

The native branch had stronger runtime hardening than the old MCP or the early plugin rewrite:

- dedicated loop threads
- hard timeouts around launch and operations
- page recreation when `is_closed()` returned true
- teardown of poisoned sessions on timeout

Sources:

- `feat/cloakbrowser-native-browser-backend:tools/browser_cloakbrowser.py:121-171`
- `feat/cloakbrowser-native-browser-backend:tools/browser_cloakbrowser.py:223-307`
- `feat/cloakbrowser-native-browser-backend:tools/browser_cloakbrowser.py:366-377`
- `feat/cloakbrowser-native-browser-backend:tests/tools/test_browser_cloakbrowser_timeout.py:1-260`

This is resilience, not stealth, but it likely improved real-world success by avoiding stale/dead-state weirdness during long browser sessions.

#### 2.5 Native branch navigation and typing were still thin

Despite working better historically, the native branch wrapper itself did not implement old MCP-style auth choreography:

- navigate: plain `page.goto(url, **timeout_only)`
- type: plain `page.fill(selector, text)`
- click: plain `page.click(selector)`

Sources:

- `feat/cloakbrowser-native-browser-backend:tools/browser_cloakbrowser.py:468-480`
- `feat/cloakbrowser-native-browser-backend:tools/browser_cloakbrowser.py:604-676`

So the native branch's prior success cannot be explained by wrapper-level humanized typing or smart settle logic. It was likely benefiting from CloakBrowser itself, persistent profile state, and/or environment/runtime differences.

### 3. Verified current standalone plugin anti-bot techniques

#### 3.1 Current launch/config surface

The current plugin now passes through:

- `user_data_dir`
- `headless`
- `humanize`
- `human_preset`
- `stealth_args`
- `geoip`
- `args`
- optional `proxy`, `locale`, `timezone`, `color_scheme`, `user_agent`

Sources:

- `cloakbrowser-hermes-plugin/config.py:16-47`
- `cloakbrowser-hermes-plugin/config.py:251-279`

#### 3.2 Current profile persistence / same-profile auth reuse

The plugin intentionally shares one persistent profile/login per canonical `user_data_dir` inside one Hermes process, with per-task page/ref/console isolation layered on top.

Sources:

- `cloakbrowser-hermes-plugin/README.md:9-12`
- `cloakbrowser-hermes-plugin/session_manager.py:100-102`

#### 3.3 Current humanized typing

The plugin now has restored MCP-style humanized typing:

- focus or click first
- pause
- select-all + backspace clear
- per-character keyboard typing with uneven pauses
- optional delayed Enter submit

Sources:

- `cloakbrowser-hermes-plugin/adapter.py:448-535`
- `cloakbrowser-hermes-plugin/schemas.py:23-38`

#### 3.4 Current gaps still verified in the plugin

The plugin still lacks several techniques present in the MCP contract:

1. Navigate is still plain `page.goto(... wait_until="load")` with no settle/challenge logic.
   - Source: `cloakbrowser-hermes-plugin/adapter.py:328-357`

2. Click is still plain `locator.click()` with no retry wrapper.
   - Source: `cloakbrowser-hermes-plugin/adapter.py:443-446`

3. No `fingerprint_seed` config surface or pass-through exists.
   - Sources: `cloakbrowser-hermes-plugin/config.py:16-47`, `cloakbrowser-hermes-plugin/config.py:251-279`

4. No headed screen auto-detect / auto-derived viewport behavior equivalent to the MCP is present.
   - Current config has no viewport fields at all.
   - Source: `cloakbrowser-hermes-plugin/config.py:16-31`

### 4. Revised diagnosis after comparing all three implementations

The old MCP had the richest wrapper-level anti-bot behavior.

The old native branch that "worked" did not replicate most of that behavior in wrapper code, which means its success likely came from a combination of:

- native CloakBrowser local mode
- persistent profile reuse
- headed-by-default operation in native config
- stable runtime/session handling
- CloakBrowser's own browser-level stealth features
- possibly older/profile-specific accumulated trust state

The current plugin has now recovered the most important missing interaction behavior (humanized typing), but still lacks two MCP-level techniques that remain high-priority for login pages:

1. smart navigate / settle / challenge-aware waiting
2. click retry / dynamic-page resilience

And it still lacks one important identity-stability input the MCP exposed:

3. `fingerprint_seed`

### 5. Revised anti-bot parity worklist

Priority order for the standalone plugin:

1. Add MCP-style smart navigation parity:
   - `domcontentloaded`
   - settle wait using DOM mutation quiet period
   - challenge-title detection with an extra pause

2. Add retry wrapper around click-sensitive actions.

3. Add `fingerprint_seed` to plugin config parsing, launch pass-through, docs, and tests.

4. Decide whether to add headed viewport auto-detect / auto-derived viewport behavior.

5. Add a live fingerprint audit checklist for headless mode covering:
   - `navigator.webdriver`
   - `window.chrome.runtime`
   - plugins/mimeTypes
   - outer/inner dimensions
   - canvas/WebGL/audio
   - permissions states
   - cross-signal consistency with UA/platform/locale/timezone

6. Treat `headless=true` Reddit login as unproven until the above are verified in real runtime output, not inferred from SDK docs.

### 6. Separate bug now tracked alongside anti-bot work

There is a separate session-exit bug reported by the user after a CloakBrowser session:

- unhandled Node `EPIPE`
- emitted after the Hermes session exits back to shell

This is not an anti-bot issue. Track it separately as CLI/session shutdown plumbing, likely around output piping or subprocess/socket teardown after plugin/browser usage. Do not mix it into browser fingerprint diagnosis.

## Acceptance Criteria

- Existing nine plugin overrides still work through direct SDK, not MCP:
  - `browser_navigate`
  - `browser_snapshot`
  - `browser_click`
  - `browser_type`
  - `browser_scroll`
  - `browser_back`
  - `browser_press`
  - `browser_get_images`
  - `browser_console`
- No `cloakbrowser-mcp` server, MCP discovery gate, MCP envelope adapter, or MCP-owned browser state is required.
- The plugin owns launch/close lifecycle, page registry, snapshot refs, console/error buffers, timeout/fatal cleanup, and task/session routing.
- Root/session work inside the same Hermes profile should share one physical persistent context/login where possible; unrelated profiles should use different `user_data_dir` values.
- Task-local state remains isolated: page, refs, console buffer, and diagnostics must not be shared between task IDs.
- `browser_vision` and `browser_cdp` remain explicitly out of scope unless later planned and contract-tested.
- Verification uses temporary profiles and `about:blank`/`data:` URLs before any real website smoke.

## Correct Plugin Configuration Setup

Configuration must separate host-owned plugin loading keys from plugin-owned runtime options.

### Host-owned keys

These keys belong to Hermes plugin loading/override policy, not to the CloakBrowser runtime adapter:

```yaml
plugins:
  enabled:
    - cloakbrowser-hermes-plugin
  entries:
    cloakbrowser-hermes-plugin:
      allow_tool_override: true
```

Notes:

- `allow_tool_override: true` is required because the plugin intentionally overrides built-in `browser_*` tools.
- Do not use stale native `browser.cloud_provider: cloakbrowser` or `browser.cloakbrowser:*` blocks as the target plugin setup. Those blocks are legacy reference only unless a separate native backend consumes them.

### Plugin-owned runtime config

Runtime options belong under the plugin entry `config` mapping:

```yaml
plugins:
  enabled:
    - cloakbrowser-hermes-plugin
  entries:
    cloakbrowser-hermes-plugin:
      allow_tool_override: true
      config:
        user_data_dir: "${HERMES_HOME}/cloakbrowser_profile"
        headless: true
        humanize: true
        human_preset: "default"
        stealth_args: true
        geoip: false
        args: []
        # Optional strings: omit when unset.
        # Include as empty strings only when set by a legacy-compatible config path.
        # proxy: ""
        # locale: ""
        # timezone: ""
        # color_scheme: ""
        # user_agent: ""
```

Rules:

- Do not emit YAML `null` for plugin runtime options.
- Prefer omitting unset optional strings. Use `""` only if retaining compatibility with a legacy config path that expects empty-string optionals.
- Required/base plugin options to support:
  - `user_data_dir`
  - `headless`
  - `humanize`
  - `human_preset`
  - `stealth_args`
  - `geoip`
  - `args`
- Optional string options:
  - `proxy`
  - `locale`
  - `timezone`
  - `color_scheme`
  - `user_agent`
- `geoip` is only useful with a configured `proxy`; it resolves proxy-exit geolocation and may perform network/database lookups through/for that proxy.
- `human_preset` valid values are exactly `"default"` and `"careful"`.
- `human_config` is deferred until exact accepted fields and runtime behavior are tested in this plugin. Do not expose it in v1 config examples.
- `args` is the plugin-facing list of extra browser/Chromium arguments for this rewrite. If compatibility with historical native code is needed later, explicitly translate between plugin `args` and SDK/native `extra_args`; do not silently rely on stale key names.

## Target Architecture

### Physical shared state

Key one physical browser/context/event-loop bundle by:

```text
canonical(user_data_dir)
```

The intended registry key is the canonical persistent profile directory. Within one Hermes process, all managers using that key share one CloakBrowser profile/login. Root/task/session isolation lives in logical page-scoped state below this physical context; it is not separate auth state.

Responsibilities:

- launch persistent CloakBrowser context with SDK options from plugin config;
- prevent duplicate persistent launches against the same key;
- keep teardown reservations so the same key cannot relaunch until prior context and loop have fully stopped;
- close physical resources exactly once after the final task releases them or after fatal teardown.

### Task-local logical state

Key task/session-local state by logical task or session ID under the shared profile:

```text
task_id -> page, ref map, console buffer, error/diagnostic state
```

Responsibilities:

- create one page per task;
- generate and resolve refs only against that task's page;
- keep console/errors scoped to that task;
- close/release only that task's page on task close;
- clear all aliases on fatal physical teardown.

### Serialization

Start with one active sensitive CloakBrowser operation per shared profile where needed. Separate pages do not fully remove shared-profile risks from cookies, downloads, dialogs, and anti-bot flows. Relax only after deterministic concurrency coverage and review.

## Files to Change

- `__init__.py` — replace MCP dispatch with direct SDK session manager, tool handlers, config parsing, lifecycle cleanup, and `/cloak` commands.
- `test_plugin.py` — replace MCP mock tests with direct-SDK adapter/session-manager tests and browser tool contract tests.
- `README.md` — update install/usage docs from MCP-backed setup to direct-SDK plugin setup and corrected config convention.
- `INSTALL.md` — remove `cloakbrowser-mcp` install/register flow; document SDK/plugin install and corrected `plugins.*` config.
- `plugin.yaml` — update description if needed; keep standalone plugin metadata.
- `PLAN.md` — this plan.

## Task Breakdown

### Phase 0: Fresh discovery

1. Inspect current Hermes plugin API for config access, tool override permission, session/task identity, shutdown hooks, and command registration.
2. Inspect current plugin source and tests; record exact behavior and schemas for all nine overrides.
3. Inspect installed `cloakbrowser` SDK version and direct launch/page APIs.
4. Confirm dependency strategy: plugin dependency metadata, documented manual install, or Hermes-supported plugin environment.
5. Verify how plugin handlers receive task/session identity. Stop if no logical identity is available.

### Phase 1: Config and dependency foundation

1. Add plugin config parser for `plugins.entries.cloakbrowser-hermes-plugin.config`.
2. Apply defaults without producing or requiring YAML `null`.
3. Validate `human_preset` as `default` or `careful`.
4. Treat empty optional strings as unset before SDK launch.
5. Warn or no-op `geoip: true` when `proxy` is unset.
6. Translate plugin config into SDK launch arguments, including `args`.

### Phase 2: Direct SDK runtime

1. Remove MCP server discovery and `ctx.dispatch_tool()` calls.
2. Implement physical context manager keyed by canonical `user_data_dir`.
3. Implement task-local page/ref/console/diagnostic state.
4. Implement launch, close, timeout, fatal cleanup, final teardown, and teardown reservation.
5. Keep browser I/O outside non-reentrant registry locks.

### Phase 3: Tool parity

1. Port `browser_navigate` result/error behavior to direct SDK.
2. Port `browser_snapshot` with task-local accessibility/text snapshot and ref map.
3. Port `browser_click`, `browser_type`, `browser_scroll`, `browser_back`, and `browser_press` using task-local refs/page.
4. Port `browser_get_images` extraction schema.
5. Port `browser_console` with plugin-owned console/error buffers and safe internal evaluation only as needed.
6. Preserve `/cloak status`, `/cloak connect`, and `/cloak disconnect` semantics against the new runtime.

### Phase 4: Lifecycle and race hardening

1. Add tests for first launch, same-root reuse, different-root isolation, task close, final close, timeout, fatal failure, and cleanup.
2. Add deterministic tests for page-close dedupe, teardown/reacquire prevention, acquire-vs-close, and concurrent final close where applicable.
3. Verify no duplicate page/context close and no second persistent launch during teardown.

### Phase 5: Docs and rollout

1. Rewrite `README.md` and `INSTALL.md` to remove MCP setup and show corrected plugin config.
2. Document that stale `browser.cloakbrowser` blocks are legacy references only.
3. Document `geoip` proxy requirement, `human_preset` accepted values, and deferred `human_config`.
4. Add troubleshooting for missing SDK dependency, tool override permission, GUI/headless behavior, and profile locks.

## Tests to Add or Update

- Config parsing:
  - host-owned `allow_tool_override` stays outside runtime config;
  - runtime config is read from `plugins.entries.cloakbrowser-hermes-plugin.config`;
  - omitted optionals and empty strings both become unset;
  - YAML `null` is rejected or normalized deliberately, never required;
  - invalid `human_preset` fails clearly.
- Tool contract tests for all nine overrides using local fixtures.
- Task isolation tests for refs, pages, console buffers, and diagnostics.
- Same-profile sharing test with distinct task pages.
- Cross-profile isolation through distinct `user_data_dir` values.
- Lifecycle/race tests for close, timeout, fatal cleanup, teardown reservation, and final close.
- Live smoke test using temporary `user_data_dir` plus `about:blank`/`data:` only.

## Verification Gates

Do not call the rewrite complete until current code produces real passing output for:

1. Unit tests for config parsing and all retained override schemas.
2. Deterministic lifecycle/race tests.
3. Same-profile/delegate sharing test with distinct task pages.
4. Cross-profile isolation through distinct `user_data_dir` values.
5. Live direct-SDK smoke with a temporary profile and cleanup assertion.
6. Repository formatting/lint/type/compile checks as applicable.
7. Read-only code review and security review before commit/PR.

## Risks

- Security/privacy: profile directories contain cookies, local storage, and authenticated state. Same Hermes profile sessions sharing a `user_data_dir` intentionally share login state; use separate profile directories for isolation boundaries. Avoid logging secrets and profile contents.
- Compatibility: Hermes plugin APIs, config conventions, and browser tool schemas may have changed; Phase 0 must refresh live APIs before implementation.
- Concurrency: persistent Chromium profile locks can still conflict across independent OS processes. V1 only handles same-process lifecycle coordination.
- Fingerprint coherence: proxy, GeoIP, locale, timezone, user agent, color scheme, and extra args can create inconsistent identity signals if misconfigured.
- SDK behavior: `humanize`, `geoip`, and launch argument behavior are owned by CloakBrowser SDK and must be tested against the installed version.
- Migration: existing MCP docs/config will become stale; update docs in the same PR as code.
- Rollback: disable the plugin via `plugins.enabled`/Hermes plugin commands to restore stock Hermes browser behavior.

## Open Decisions

- Exact dependency packaging model for `cloakbrowser` SDK.
- Exact Hermes plugin API for task/session identity.
- Whether downloads/evaluate need user-visible plugin support or remain internal/unsupported.
- Whether `browser_vision` should stay native or later gain screenshot-based CloakBrowser support.
- Whether `browser_cdp` should stay native/unsupported or get a tested CloakBrowser CDP path.
- Whether `human_config` can be safely exposed after field-level tests.

## First Next Action

Run Phase 0 only: live inventory of the current plugin, current Hermes plugin APIs, current browser schemas, and current `cloakbrowser` SDK. Do not port lifecycle code or start broad refactors until task/session identity and SDK launch behavior are confirmed.
