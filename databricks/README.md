# Databricks deployment for doc-agent

This folder holds everything needed to run doc-agent on Databricks. Start
with **[docs/databricks.md](../docs/databricks.md)** — that's the full
walkthrough.

| File | Purpose |
|------|---------|
| `databricks.yml` | Asset Bundle config — declares the App + nightly Job |
| `app.yaml` | Databricks Apps manifest — Streamlit launcher + env wiring |
| `notebooks/00_smoke_test.py` | Verify deps, secret, Volume, ping after deploy |
| `notebooks/01_generate.py` | Run `generate_all` over every canonical JSON |
| `scripts/setup_workspace.sh` | One-time prep — CLI, secret scope, UC Volume |
| `scripts/upload_canonical.sh` | Push a laptop-produced canonical JSON to the Volume |

Nothing in this folder is imported by the laptop code path. `git checkout
main` removes it cleanly if you ever want to revert.
