# Smoke scripts

These scripts are optional live smokes for an installed CloakBrowser Hermes plugin. They intentionally have no shebang so they are not run with ambient `/usr/bin/python3`.

Run them with the Hermes Agent virtualenv Python:

```bash
/home/james/.hermes/hermes-agent/venv/bin/python scripts/mina_live_tools_smoke.py --profile mina
/home/james/.hermes/hermes-agent/venv/bin/python scripts/mina_toyota_vision_smoke.py --profile mina
```

Both scripts read the installed plugin path from the selected Hermes profile, defaulting to `~/.hermes/profiles/mina/plugins/cloakbrowser-hermes-plugin`.
