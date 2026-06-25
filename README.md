# cloakbrowser-hermes-plugin

Hermes plugin that makes the built-in `browser_*` tool family run through the ColorSource CloakBrowser MCP server.

Behavior:
- `browser_*` overrides are active whenever this plugin is enabled.
- First browser action auto-launches a headed CloakBrowser window.
- `/cloak connect` is optional prewarm.
- `/cloak disconnect` closes the current CloakBrowser session.
- The persistent browser profile lives at:
  - `~/.hermes/profiles/<profile>/browser-profiles/cloakbrowser`

This plugin is designed for local desktop Hermes installs where you want a visible browser window, manual login, and persistent session state.

## Requirements

1. Hermes with plugin support.
2. A configured CloakBrowser MCP server named `cloakbrowser`.
3. A desktop session (headed browser mode).

## MCP setup

Example install flow for the ColorSource MCP server:

1. Clone/install the MCP server in a Python virtualenv.
2. Register it with Hermes:

```bash
hermes mcp add cloakbrowser \
  --command /absolute/path/to/venv/bin/cloakbrowser-mcp \
  --args --caps all
```

3. Restart Hermes or run `/reload-mcp` in a fresh session.

Verify:

```bash
hermes mcp list
```

You should see the `cloakbrowser` server registered.

## Plugin install

There are two practical installation paths.

### Option A: install from git

Hermes installs plugins from git repositories:

```bash
hermes plugins install <git-url-or-owner/repo> --enable
```

Once this repo is published, install it directly from GitHub, for example:

```bash
hermes plugins install https://github.com/<owner>/cloakbrowser-hermes-plugin.git --enable
```

Or with GitHub shorthand:

```bash
hermes plugins install <owner>/cloakbrowser-hermes-plugin --enable
```

### Option B: local development install from a workspace checkout

Hermes discovers user plugins under the active profile directory.

Example:

```bash
mkdir -p ~/.hermes/profiles/<profile>/plugins
ln -sfn ~/workspace/cloakbrowser-hermes-plugin \
  ~/.hermes/profiles/<profile>/plugins/cloakbrowser-hermes-plugin
hermes plugins enable cloakbrowser-hermes-plugin
```

Then start a new Hermes session.

Notes:
- `hermes plugins enable` updates config, but the plugin loads on the next session.
- Replace `<profile>` with your Hermes profile name.
- Repeat the same process under `~/.hermes/profiles/<name>/plugins/` on any other machine or profile.

## Usage

Once enabled, use Hermes normally with the standard browser tools.

Examples:

```text
browser_navigate(url="https://example.com")
browser_snapshot(full=false)
browser_click(ref="@e1")
```

Slash commands:

```text
/cloak status
/cloak connect
/cloak disconnect
```

Meaning:
- `/cloak status` shows plugin/browser state.
- `/cloak connect` launches the browser immediately.
- `/cloak disconnect` closes the current CloakBrowser session.
- After `/cloak disconnect`, the next `browser_*` call auto-launches again.

## Reverting to stock Hermes browser behavior

Disable the plugin:

```bash
hermes plugins disable cloakbrowser-hermes-plugin
```

Then start a new Hermes session.

## Implementation notes

The plugin overrides these built-in browser tools:
- `browser_navigate`
- `browser_snapshot`
- `browser_click`
- `browser_type`
- `browser_scroll`
- `browser_back`
- `browser_press`
- `browser_get_images`
- `browser_console`

It intentionally does not override:
- `web_search`
- `web_extract`
- `browser_cdp`

## MCP runtime layout

This plugin expects a separately installed CloakBrowser MCP server.

A typical local layout looks like:

```text
~/workspace/cloakbrowser-mcp/
├── .venv/
│   └── bin/cloakbrowser-mcp
└── cloakbrowser-mcp/
```

The important part is that Hermes is configured to launch the MCP entrypoint from the virtualenv, for example:

```bash
hermes mcp add cloakbrowser \
  --command ~/workspace/cloakbrowser-mcp/.venv/bin/cloakbrowser-mcp \
  --args --caps all
```

The plugin repository and the MCP runtime should remain separate projects.
