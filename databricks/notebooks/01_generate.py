# Databricks notebook source
# MAGIC %md
# MAGIC # doc-agent · generate all
# MAGIC
# MAGIC Runs `generate_all` against every canonical JSON found in
# MAGIC `<volume>/extracted/`, writes Markdown to `<volume>/generated/<model>/`,
# MAGIC and exports HTML + DOCX to `<volume>/exports/<model>/`.
# MAGIC
# MAGIC Designed to be invoked both interactively (open the notebook, click
# MAGIC Run) and as a Databricks Job — the `databricks.yml` bundle defines a
# MAGIC nightly schedule pointing here.

# COMMAND ----------
# MAGIC %pip install -e ../.
# MAGIC %restart_python

# COMMAND ----------
dbutils.widgets.text("volume_path",  "/Volumes/main/doc_agent/project_lib")
dbutils.widgets.text("secret_scope", "doc-agent")
dbutils.widgets.text("secret_key",   "anthropic-api-key")
dbutils.widgets.text("kinds",        "autodoc,sysreq,unitreq")
dbutils.widgets.text("model_filter", "")  # blank = all models

volume_path  = dbutils.widgets.get("volume_path")
secret_scope = dbutils.widgets.get("secret_scope")
secret_key   = dbutils.widgets.get("secret_key")
kinds        = [k.strip() for k in dbutils.widgets.get("kinds").split(",") if k.strip()]
model_filter = dbutils.widgets.get("model_filter").strip() or None

# COMMAND ----------
from doc_agent.deploy.databricks import bootstrap

bootstrap(secret_scope=secret_scope, secret_key=secret_key, volume_path=volume_path)

from doc_agent.ai.client import AIClient
from doc_agent.config import settings
from doc_agent.extract import CanonicalModel
from doc_agent.generate import generate_all, write_run_outputs
from doc_agent.memory import FactsMemory
from doc_agent.rag import RAGManager

settings.ensure_data_dir()
print(f"DATA_DIR = {settings.data_dir}")
print(f"kinds    = {kinds}")
print(f"filter   = {model_filter or '(none)'}")

# COMMAND ----------
# Find every canonical JSON the laptop has pushed up.
from pathlib import Path

extracted = settings.data_dir / "extracted"
json_paths = sorted(extracted.glob("*.json"))
if model_filter:
    json_paths = [p for p in json_paths if p.stem == model_filter]

if not json_paths:
    raise SystemExit(f"No canonical JSONs at {extracted} — push one with upload_canonical.sh first.")

print(f"Will process {len(json_paths)} model(s):")
for p in json_paths:
    print(f"  - {p.name}")

# COMMAND ----------
client = AIClient()
facts  = FactsMemory(settings.facts_path)
rag    = None
try:
    r = RAGManager(store_path=settings.rag_dir, collection_name=settings.rag_collection)
    if r.stats()["chunks"] > 0:
        rag = r
except Exception:
    rag = None

# COMMAND ----------
import json as _json

for jpath in json_paths:
    print(f"\n=== {jpath.name} ===")
    canonical = CanonicalModel.model_validate(_json.loads(jpath.read_text()))

    summary = generate_all(
        client=client,
        canonical=canonical,
        kinds=kinds,
        rag=rag,
        facts=facts,
        on_progress=lambda c, t, sp, k, d: print(
            f"  [{c}/{t}] {sp} · {k} — {'OK' if d else 'FAILED'}"
        ),
    )
    out_dir = settings.data_dir / "generated" / canonical.model.name
    write_run_outputs(summary, out_dir)

    print(
        f"  wrote {len(summary.docs)} doc(s) to {out_dir} · "
        f"in {summary.total_input_tokens:,} / out {summary.total_output_tokens:,} tok · "
        f"{summary.elapsed_s:.1f}s"
    )

# COMMAND ----------
# MAGIC %md
# MAGIC ## Done
# MAGIC
# MAGIC Outputs are on the Volume — open `02_export.py` (or the Streamlit App)
# MAGIC to bundle them into DOCX / HTML / PDF.
