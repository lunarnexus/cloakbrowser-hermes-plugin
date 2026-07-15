# CloakBrowser Hermes Plugin Status / Handoff

_Last updated: 2026-07-15 by Sera. Scope: `/home/james/workspace/cloakbrowser-hermes-plugin` plus read-only comparison against `/home/james/workspace/cloakbrowser-mcp` and `feat/cloakbrowser-native-browser-backend` in `/home/james/.hermes/hermes-agent`._

## Goal

Rewrite `cloakbrowser-hermes-plugin` from an MCP-backed browser-tool override plugin into a standalone Hermes plugin that uses the Python `cloakbrowser` SDK directly, while preserving the existing Hermes `browser_*` tool contracts and avoiding Hermes core changes.

## Current state

- The standalone plugin implementation in this repo is active and no longer depends on MCP transport/runtime.
- Humanized auth typing parity has been restored in the plugin (`browser_type` now does focus/click, keyboard clear, uneven per-character typing, optional Enter submit).
- Headless runtime smoke in `mina` previously confirmed live Chrome-like UA/client-hints and successful typed-input smoke on Reddit login page.
- Full credentialed Reddit login is still not proven fixed.
- The remaining anti-bot gap is no longer believed to be just user-agent or basic typing.

## Evidence-backed conclusions from the 2026-07-15 anti-bot audit

1. The earlier wrapper had the richest wrapper-level anti-bot behavior.
   - Smart navigate used `domcontentloaded` + DOM settle + challenge-title pause.
   - Clicks had one-retry resilience.
   - Typing used explicit humanized keyboard choreography.
   - It exposed `fingerprint_seed` and headed viewport auto-sizing.

2. The old native integrated Hermes branch that historically worked did NOT reproduce most earlier-wrapper auth choreography.
   - It launched native CloakBrowser locally with persistent profiles and direct config pass-through.
   - It had stronger timeout/liveness/session hardening than the MCP.
   - But its wrapper-level navigate/click/type paths were still plain compared with that earlier wrapper.

3. The current standalone plugin now matches that earlier wrapper on smart navigate, click retry, and humanized typing, but still lacks headed viewport auto-detect parity.

4. `fingerprint_seed` is now supportable in the plugin only through the currently documented wrapper-equivalent flag path (`args += ["--fingerprint=<seed>"]`). Current public CloakBrowser Python docs do not expose a verified first-class `fingerprint_seed=` launch kwarg.

5. Therefore, the most likely remaining blockers for Reddit/login flows are:
   - deeper headless fingerprint coherence beyond UA alone
   - challenge completion behavior that still is not live-verified end to end
   - missing headed viewport parity when native/headed coherence depends on screen-derived sizing

See `PLAN.md`, section `Evidence-based Anti-Bot Inventory (2026-07-15 refresh)` for the source-backed comparison.

## Separate tracked bug

User reported a separate post-session exit bug after sessions that used the Cloak plugin:

- unhandled Node `EPIPE`
- thrown after Hermes exits back to shell
- Node.js v24.17.0

This is tracked separately from anti-bot work. It looks like CLI/session shutdown plumbing, not browser stealth logic.

## Tooling note

- Initial audit fell back to direct reads because CodeGraph was temporarily unavailable; later review confirmed the indexed repo state.
- Audit evidence in this handoff therefore comes from `read_file`, `search_files`, `terminal git show`, live runtime checks already performed in-session, and later CodeGraph re-checks.

## Recommended next implementation slice

1. Run live Reddit/login verification now that smart navigate and click retry are in place.
2. Add or prove headed viewport auto-detect parity.
3. Keep `fingerprint_seed` docs/tests aligned with the current `--fingerprint=<seed>` pass-through behavior.
4. Run a live fingerprint audit checklist for headless mode before claiming Reddit parity.
5. Investigate the separate Node `EPIPE` shutdown bug in Hermes core/CLI plumbing.
