# Deploying doc-agent on Databricks

This guide describes how to run the post-Extract half of doc-agent on
Databricks — leaving MATLAB-based `.slx` extraction on a laptop that has
desktop MATLAB.

The split:

```
┌──────────────────────────────────┐                 ┌─────────────────────────────────────────┐
│  Laptop (has MATLAB)             │  canonical.json │             Databricks                   │
│                                  │  ────────────►  │                                          │
│  doc-agent extract VSEModel.slx  │   (UC Volume)   │  • Generate (Anthropic API)              │
│                                  │                 │  • Export to HTML / DOCX / PDF           │
│                                  │                 │  • RAG library (chromadb on the Volume)  │
│                                  │                 │  • Streamlit UI as a Databricks App      │
│                                  │                 │  • Scheduled regenerate via a Job        │
└──────────────────────────────────┘                 └─────────────────────────────────────────┘
```

The boundary is the canonical JSON file produced by Extract. Everything
downstream is pure Python and runs in either environment without code
changes — only env vars (`DATA_DIR`, `ANTHROPIC_API_KEY`) differ.

## What's in this branch

All Databricks-specific code lives in two folders, separate from the rest of
the project:

```
databricks/
├── databricks.yml                  Bundle config — declares the App and Job
├── app.yaml                        Databricks Apps manifest (Streamlit launcher)
├── notebooks/
│   ├── 00_smoke_test.py            One-shot sanity check: deps, secret, Volume, ping
│   └── 01_generate.py              Run generate_all over every canonical JSON
└── scripts/
    ├── setup_workspace.sh          One-time prep: CLI, secret, Volume, schema
    └── upload_canonical.sh         Push a canonical JSON from laptop → Volume

src/doc_agent/deploy/
├── __init__.py
└── databricks.py                   Runtime adapter — reads secrets via dbutils

docs/databricks.md                  ← you are here
```

No file under `src/doc_agent/` outside `deploy/` was modified. The existing
`config.py` already honors `DATA_DIR` and `ANTHROPIC_API_KEY` env vars, so
the Databricks adapter just sets those before the app code runs.

## One-time setup

### Prerequisites

* Access to a Databricks workspace, with permission to:
  * create a secret scope,
  * create a Unity Catalog Volume,
  * deploy a Databricks App and a Job.
* Your platform team has enabled **Unity Catalog** in the workspace.
* Locally: the [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html)
  (`brew install databricks` on macOS), and an Anthropic API key.

### Setup steps

1. **Run the setup script** (creates the CLI profile, secret scope, and
   Volume; idempotent):

   ```bash
   bash databricks/scripts/setup_workspace.sh
   ```

   It will ask you for:
   * the workspace URL (e.g. `https://adb-1234567890.0.azuredatabricks.net`),
   * a Personal Access Token (`databricks configure` step),
   * your Anthropic API key (stored in the `doc-agent/anthropic-api-key`
     secret).

   At the end it prints the values you'll need for the next step.

2. **Edit `databricks/databricks.yml`** to match what the script printed:
   * `workspace_host` — your workspace URL.
   * `volume_path` — the Volume path (default `/Volumes/main/doc_agent/project_lib`).
   * Catalog / schema / secret names if you used non-defaults.

3. **Deploy the bundle** (registers the App and Job in your workspace):

   ```bash
   databricks bundle deploy --target dev
   ```

   This uploads the repo to a Databricks workspace folder and creates the
   declared resources. Re-run any time you change configuration.

4. **Open the smoke-test notebook** in the workspace
   (`databricks/notebooks/00_smoke_test.py`) and Run All. Every cell must
   print a `PASS` line. If a cell fails, the error message tells you what's
   missing (usually the Volume path or the secret).

## Day-to-day workflow

```bash
# 1. On the laptop with MATLAB: extract a model.
doc-agent extract VSEModel.slx -o project_lib/extracted/VSEModel.json

# 2. Push the canonical JSON to the Volume.
bash databricks/scripts/upload_canonical.sh project_lib/extracted/VSEModel.json
```

Then either:

* **Open the Streamlit App** — link is in the Databricks workspace under
  Apps → `doc-agent`. Use the Generate, Export, Library, and Chat tabs
  exactly as you do locally. Files live on the Volume instead of your
  laptop.

* **Run `01_generate.py`** directly — useful when you want to override the
  set of subsystems or kinds via notebook widgets.

* **Let the nightly Job run it** — once you un-pause the `nightly_generate`
  schedule in `databricks.yml` and redeploy, every canonical JSON on the
  Volume gets regenerated daily at 06:00 UTC.

## What the Databricks adapter does

`src/doc_agent/deploy/databricks.py` exposes one function:

```python
from doc_agent.deploy.databricks import bootstrap
bootstrap(
    secret_scope="doc-agent",
    secret_key="anthropic-api-key",
    volume_path="/Volumes/main/doc_agent/project_lib",
)
```

It populates `ANTHROPIC_API_KEY` (from a Databricks secret) and `DATA_DIR`
(to the Volume) in `os.environ`. After that, any `from doc_agent.config
import settings` sees those values exactly as it would see values from a
local `.env` file. No other doc-agent code is aware that Databricks exists.

This means:

* The same `pytest` suite that passes locally also passes on a Databricks
  cluster.
* You can ship a hotfix by `git push` from the laptop and `databricks bundle
  deploy` — no Databricks-specific code paths to keep in sync.
* If MATLAB Production Server later becomes available, only `MatlabBridge`
  changes; the Databricks deployment is unaffected.

## What this does NOT solve

* **MATLAB.** `.slx` files still need a machine with desktop MATLAB to
  produce a canonical JSON. If your company eventually deploys MATLAB
  Production Server, swap `MatlabBridge` to call it via HTTP and Extract
  can move into Databricks too. Until then it stays on the laptop.

* **Persistence across cluster restarts.** Anything written to a cluster's
  local disk (`/tmp`, `/databricks/driver`) is gone when the cluster shuts
  down. All doc-agent state lives on the Volume (`settings.data_dir`),
  which survives.

* **Multi-user concurrency on chromadb.** A single-node App is fine. If you
  scale to multiple writer processes, the chromadb store on a Volume can
  hit file-lock contention — at that point migrate `RAGManager` to
  Databricks Vector Search. Don't pre-optimise; do it only if you hit it.

## Rolling back

Everything Databricks-specific lives on the `databricks` git branch and in
`databricks/` + `src/doc_agent/deploy/`. To revert to the laptop-only
project:

```bash
git checkout main
```

`main` has never seen any of these files.
