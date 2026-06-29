# INSTALL

Installs the CloakBrowser-backed Hermes stack:
- `cloakbrowser-mcp` (third party)
- `cloakbrowser-hermes-plugin`
- `cloakbrowser` skill
- `reddit-research` skill

Notes:
- Requires a GUI desktop session. The plugin launches CloakBrowser headed.
- Use `--caps all`.
- Do not copy an existing `.venv` from another machine.

## 1) Install the patched cloakbrowser-mcp

Use the branch with the backend-kwarg fix:
- repo: `https://github.com/lunarnexus/cloakbrowser-mcp.git`
- branch: `fix/remove-backend-kwarg`
- commit: `ab2700c3fe79ff3aa0475ff74be537fd82dde3aa`

```bash
git clone -b fix/remove-backend-kwarg https://github.com/lunarnexus/cloakbrowser-mcp.git ~/workspace/cloakbrowser-mcp
cd ~/workspace/cloakbrowser-mcp
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install -e .
```

This repo's `pyproject.toml` lives at the repo root, so the editable install target is `.`.

## 2) Register the MCP server in Hermes

```bash
hermes mcp add cloakbrowser \
  --command "$HOME/workspace/cloakbrowser-mcp/.venv/bin/cloakbrowser-mcp" \
  --args --caps all
```

Notes:
- `hermes mcp add` prompts to enable the discovered tools. Answer `y` to enable all tools.
- Headed CloakBrowser needs the desktop session env. If Hermes strips GUI vars from the MCP child, add dynamic env passthrough:

```bash
hermes config set mcp_servers.cloakbrowser.env.DISPLAY '${DISPLAY}'
hermes config set mcp_servers.cloakbrowser.env.DBUS_SESSION_BUS_ADDRESS '${DBUS_SESSION_BUS_ADDRESS}'
hermes config set mcp_servers.cloakbrowser.env.XAUTHORITY '${XAUTHORITY}'
```

Run those from the same desktop session used to start Hermes; do not hard-code display numbers like `:10.0`.
- In non-interactive automation, feed `y` on stdin:

```bash
printf 'y\n' | hermes mcp add cloakbrowser \
  --command "$HOME/workspace/cloakbrowser-mcp/.venv/bin/cloakbrowser-mcp" \
  --args --caps all
```

Verify:

```bash
hermes mcp list
hermes mcp test cloakbrowser
```

## 3) Install the Hermes plugin

```bash
hermes plugins install https://github.com/lunarnexus/cloakbrowser-hermes-plugin.git --enable
```

If you already have the repo checked out locally and want Hermes to use that workspace copy directly:

```bash
mkdir -p ~/.hermes/profiles/<profile>/plugins
ln -sfn ~/workspace/cloakbrowser-hermes-plugin \
  ~/.hermes/profiles/<profile>/plugins/cloakbrowser-hermes-plugin
hermes plugins enable cloakbrowser-hermes-plugin
```

Replace `<profile>` with your Hermes profile name. Plugin changes take effect in a new session.

Verify:

```bash
hermes plugins list
```

## 4) Install the two skills

```bash
hermes skills install https://raw.githubusercontent.com/lunarnexus/ai-skills/master/cloakbrowser/SKILL.md
hermes skills install https://raw.githubusercontent.com/lunarnexus/ai-skills/master/reddit-research/SKILL.md
```

If you already have `~/workspace/ai-skills` locally and want to use those workspace copies directly:

```bash
mkdir -p ~/.hermes/profiles/<profile>/skills
ln -sfn ~/workspace/ai-skills/cloakbrowser \
  ~/.hermes/profiles/<profile>/skills/cloakbrowser
ln -sfn ~/workspace/ai-skills/reddit-research \
  ~/.hermes/profiles/<profile>/skills/reddit-research
```

Replace `<profile>` with your Hermes profile name.

Verify:

```bash
hermes skills list
```

## 5) Start a fresh Hermes session

Plugin and MCP changes should be tested in a new session.

## 6) First-run check

In a fresh Hermes session:

```text
/cloak status
/skill cloakbrowser
Open https://example.com and tell me what is visible.
```

Expected:
- a headed CloakBrowser window opens
- `browser_*` goes through CloakBrowser

Optional Reddit check:

```text
/skill reddit-research
Scan the first 5 visible posts on https://www.reddit.com/r/hermesagent/ and list their titles.
```

## Disable

```bash
hermes plugins disable cloakbrowser-hermes-plugin
```

Then start a new Hermes session.
