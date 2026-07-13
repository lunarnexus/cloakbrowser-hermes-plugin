# CloakBrowser Hermes Plugin Status / Handoff

_Last updated: 2026-07-12 by Hermes subagent. Scope: `/home/james/workspace/cloakbrowser-hermes-plugin` only._

## Goal

Rewrite `cloakbrowser-hermes-plugin` from an MCP-backed browser-tool override plugin into a standalone Hermes plugin that uses the Python `cloakbrowser` SDK directly, while preserving the existing Hermes `browser_*` tool contracts and avoiding Hermes core changes.

## Safety constraints

- Do not touch Hermes config, `sera`, or other profile state while working this repo handoff.
- Do not treat stale `browser.cloud_provider: cloakbrowser` / `browser.cloakbrowser:*` config as the target plugin setup; those are legacy/native-reference material only.
- Do not use MCP runtime, `cloakbrowser-mcp`, MCP discovery gates, MCP envelope adapters, or MCP-owned browser state in the target rewrite.
- Do not copy-forward the paused native-core experiment as the implementation.
- Do not claim direct-SDK migration, packaging, feature parity, or verification is complete until current-code tests and smoke checks produce real output.
- Same-profile persistent profile/login state is intentionally shared by canonical `user_data_dir` inside one Hermes process. Isolation boundary is a distinct `user_data_dir` (normally one per Hermes profile), while root/task/session work under the same profile gets distinct pages, refs, console buffers, and diagnostics.
- Automated smoke should use temporary profiles and `about:blank` / `data:` URLs before any real website.

## Current completed research

- Target direction is selected: standalone direct-SDK Hermes plugin, no MCP, no Hermes core/native backend patch.
- Existing plugin inventory from transition evidence: nine built-in browser tools are overridden via `ctx.register_tool(..., override=True)` and `/cloak` is registered with `ctx.register_command()`.
- Existing plugin state is MCP-backed in docs/source history: handlers dispatch into MCP via `ctx.dispatch_tool()`; MCP owns launch/close, page registry, snapshot refs, console/download buffers, and cleanup.
- Required target architecture is documented in `PLAN.md`:
  - physical shared state keyed by canonical `user_data_dir` inside one process;
  - task-local logical state keyed by `task_id -> page, ref map, console buffer, diagnostics`;
  - start with one active sensitive CloakBrowser operation per shared profile where needed.
- Historical native-core research found lifecycle hazards relevant to plugin design: registry-lock deadlock around browser I/O, duplicate physical page close, relaunch during teardown, acquire/final-close races, and unintended cross-profile sharing. These are evidence for design, not plugin readiness.
- Official Hermes plugin docs were checked as the current authoritative plugin surface reference.

## Key sources

- Repo plan: `/home/james/workspace/cloakbrowser-hermes-plugin/PLAN.md`
- Transition/evidence doc: `/home/james/workspace/cloakbrowser-plugin-transition.md`
- Current repo docs still describing old MCP-backed behavior:
  - `/home/james/workspace/cloakbrowser-hermes-plugin/README.md`
  - `/home/james/workspace/cloakbrowser-hermes-plugin/INSTALL.md`
- Plugin metadata: `/home/james/workspace/cloakbrowser-hermes-plugin/plugin.yaml`
- Official Hermes plugin docs: `https://hermes-agent.nousresearch.com/docs/developer-guide/plugins`
  - Extract cache from this run: `/home/james/.hermes/profiles/sera/cache/web/hermes-agent.nousresearch.com-ac6255942f.md`
- Recent delegation/source-session evidence is indexed in `/home/james/workspace/cloakbrowser-plugin-transition.md`, section 13, source session `20260712_020030_e09ea4`, messages 68095-69749.

## Current queued / active implementation slice

- A repo implementation worker is reported as running separately.
- The next planned slice in `PLAN.md` after Phase 0 discovery is **Phase 1: Config and dependency foundation**:
  - parse runtime config from `plugins.entries.cloakbrowser-hermes-plugin.config`;
  - keep host-owned `allow_tool_override` outside runtime config;
  - apply defaults without requiring YAML `null`;
  - validate `human_preset` as `default` or `careful`;
  - normalize omitted/empty optional strings as unset;
  - warn/no-op `geoip: true` when no `proxy` is set;
  - translate plugin config into SDK launch arguments including `args`.
- Live repo status observed during this handoff: branch `feature/direct-sdk-foundation`; `test_plugin.py` modified; `PLAN.md` and `config.py` untracked. This handoff did not inspect or validate those implementation edits.

## Blockers / open decisions

- Exact dependency packaging model for the `cloakbrowser` SDK remains undecided.
- Exact Hermes plugin API for task/session identity must be verified before finalizing the logical state boundary.
- Decide whether downloads/evaluate need user-visible plugin support or remain internal/unsupported.
- Decide and document whether `browser_vision` stays native or later gets screenshot-based CloakBrowser support.
- Decide and document whether `browser_cdp` stays native/unsupported or gets a tested CloakBrowser CDP path.
- `human_config` is deferred until accepted fields and runtime behavior are tested in this plugin.
- Existing `README.md` and `INSTALL.md` still describe MCP setup and must be rewritten as part of docs rollout; do not use them as target-state instructions.

## Next steps

1. Preserve this `STATUS.md` as context before further implementation.
2. Let the active implementation worker finish or coordinate before editing the same files.
3. Review current diffs in `test_plugin.py`, `config.py`, and `PLAN.md` before making additional code changes.
4. Complete/confirm Phase 0 facts if not already done: current Hermes plugin APIs, browser schemas, installed `cloakbrowser` SDK APIs, dependency approach, and task/session identity availability.
5. Implement only the planned config/dependency foundation slice first; do not broaden into tool parity or lifecycle races until foundation tests pass.
6. Before claiming completion, produce real passing output for relevant unit tests, lifecycle/race tests, same-profile sharing, cross-profile distinct-directory isolation, live direct-SDK temporary-profile smoke, and static checks as listed in `PLAN.md`.
