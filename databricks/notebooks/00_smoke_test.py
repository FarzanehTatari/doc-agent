# Databricks notebook source
# MAGIC %md
# MAGIC # doc-agent · smoke test
# MAGIC
# MAGIC Run this once after deploying the bundle to verify the four things that
# MAGIC must all be true before anything else works:
# MAGIC
# MAGIC 1. The repo installs cleanly (`pip install -e .`).
# MAGIC 2. The Anthropic API key is reachable via the Databricks secret scope.
# MAGIC 3. The Unity Catalog Volume is mounted and writable.
# MAGIC 4. The `AIClient.ping()` call succeeds end-to-end (network + auth).
# MAGIC
# MAGIC Each cell prints a clear PASS / FAIL line, so a green run = ready to use.

# COMMAND ----------
# MAGIC %pip install -e ../.
# MAGIC %restart_python

# COMMAND ----------
# Parameters — adjust these to match your workspace.
dbutils.widgets.text("volume_path", "/Volumes/main/doc_agent/project_lib")
dbutils.widgets.text("secret_scope", "doc-agent")
dbutils.widgets.text("secret_key",   "anthropic-api-key")

volume_path  = dbutils.widgets.get("volume_path")
secret_scope = dbutils.widgets.get("secret_scope")
secret_key   = dbutils.widgets.get("secret_key")

# COMMAND ----------
# 1) Bootstrap the Databricks adapter — populates DATA_DIR and
#    ANTHROPIC_API_KEY in the environment so `settings` picks them up.
from doc_agent.deploy.databricks import bootstrap, is_databricks_runtime

print("Databricks runtime detected:", is_databricks_runtime())
print("Bootstrapped env vars:",
      bootstrap(secret_scope=secret_scope, secret_key=secret_key,
                volume_path=volume_path))

# COMMAND ----------
# 2) Settings come up with the right values?
from doc_agent.config import settings

assert settings.has_api_key, "FAIL: ANTHROPIC_API_KEY is empty"
assert str(settings.data_dir).startswith("/Volumes/"), (
    f"FAIL: data_dir is {settings.data_dir} — expected a UC Volume path"
)
print(f"PASS · data_dir   = {settings.data_dir}")
print(f"PASS · api_key    = {'set' if settings.has_api_key else 'MISSING'}")
print(f"PASS · model      = {settings.ai_model}")

# COMMAND ----------
# 3) Volume writable?
from pathlib import Path

settings.ensure_data_dir()
probe = Path(settings.data_dir) / ".smoke_test"
probe.write_text("ok")
assert probe.read_text() == "ok"
probe.unlink()
print(f"PASS · Volume {settings.data_dir} is writable")

# COMMAND ----------
# 4) End-to-end Anthropic call.
from doc_agent.ai.client import AIClient

ping = AIClient().ping()
assert ping.ok, f"FAIL: ping returned {ping.error}"
print(f"PASS · Anthropic ping — {ping.latency_ms:.0f} ms — reply: {ping.reply!r}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## All four checks passed
# MAGIC
# MAGIC You are ready to run `01_generate.py` against a real canonical JSON.
# MAGIC Upload one with:
# MAGIC
# MAGIC ```bash
# MAGIC bash databricks/scripts/upload_canonical.sh project_lib/extracted/VSEModel.json
# MAGIC ```
