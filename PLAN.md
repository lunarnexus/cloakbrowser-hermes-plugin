# CloakBrowser Hermes Plugin Rewrite Plan

## Goal

Rewrite `cloakbrowser-hermes-plugin` from an MCP-backed browser-tool override plugin into a standalone Hermes plugin that uses the Python `cloakbrowser` SDK directly, while preserving the existing Hermes `browser_*` tool contracts and avoiding Hermes core changes.

## Current Decision

- Target implementation: standalone Hermes plugin using direct Python `cloakbrowser` SDK.
- Explicit non-goals: no MCP runtime, no Hermes core/native backend patch, no direct copy-forward of the paused native-core experiment.
- Current stale `browser.cloakbrowser` config blocks are legacy/native-reference material only. They are not the target plugin configuration surface for this rewrite.
- Preserve current plugin value: override built-in browser tools with `ctx.register_tool(..., override=True)` and expose `/cloak`, but replace `ctx.dispatch_tool()`/MCP transport with plugin-owned direct SDK runtime state.

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
