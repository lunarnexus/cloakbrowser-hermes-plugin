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
./.venv/bin/pip install -e ./cloakbrowser-mcp
```

## 2) Register the MCP server in Hermes

```bash
hermes mcp add cloakbrowser \
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

Verify:

```bash
hermes plugins list
```

## 4) Install the two skills

```bash
hermes skills install https://raw.githubusercontent.com/lunarnexus/ai-skills/master/cloakbrowser/SKILL.md
hermes skills install https://raw.githubusercontent.com/lunarnexus/ai-skills/master/reddit-research/SKILL.md
```

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
