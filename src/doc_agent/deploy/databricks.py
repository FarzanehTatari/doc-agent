"""Databricks runtime adapter.

Use this when running doc-agent inside a Databricks notebook, Job, or App.
It populates the two environment variables that `doc_agent.config.Settings`
already understands — `ANTHROPIC_API_KEY` and `DATA_DIR` — by pulling them
from Databricks Secrets and Unity Catalog respectively.

Typical usage at the top of a Databricks notebook or App entry point:

    from doc_agent.deploy.databricks import bootstrap
    bootstrap(
        secret_scope="doc-agent",
        secret_key="anthropic-api-key",
        volume_path="/Volumes/main/doc_agent/project_lib",
    )
    # …now any `from doc_agent.config import settings` sees the right values.
    from doc_agent.config import settings

The rest of the codebase is completely unaware of Databricks. This file is
the only place where Databricks-specific SDK calls live.
"""

from __future__ import annotations

import os
from pathlib import Path


def is_databricks_runtime() -> bool:
    """Best-effort detection: are we running inside a Databricks cluster?

    Databricks injects `DATABRICKS_RUNTIME_VERSION` into the env on all
    notebook / job kernels. Apps and serverless compute also set it.
    """
    return bool(os.environ.get("DATABRICKS_RUNTIME_VERSION"))


def get_secret(scope: str, key: str) -> str | None:
    """Read a value from a Databricks secret scope.

    Returns None if dbutils is unavailable (e.g. running locally) or the
    secret cannot be read. Never raises — callers can fall back to other
    sources.
    """
    try:
        # `dbutils` is auto-injected in notebook kernels; in Apps and Jobs
        # we get to it through the Databricks SDK runtime helper.
        from databricks.sdk.runtime import dbutils  # type: ignore
        return dbutils.secrets.get(scope=scope, key=key)
    except Exception:
        return None


def bootstrap(
    *,
    secret_scope: str = "doc-agent",
    secret_key: str = "anthropic-api-key",
    volume_path: str | os.PathLike[str] | None = None,
    overwrite: bool = False,
) -> dict[str, str]:
    """Populate env vars so `doc_agent.config.Settings` reads from Databricks.

    Args:
        secret_scope:  Databricks secret scope holding the Anthropic API key.
        secret_key:    key name within that scope.
        volume_path:   absolute path to a Unity Catalog Volume that will hold
                       `project_lib/` artifacts (canonical JSONs, RAG store,
                       generated docs, exports, memory). When None, the
                       existing `DATA_DIR` env var is left untouched.
        overwrite:     when False (default), pre-existing env vars win — useful
                       for local debugging where you want to override
                       Databricks-provided values from a `.env`.

    Returns:
        Dict of the env vars this call set, for logging / display.
    """
    set_vars: dict[str, str] = {}

    # --- API key ------------------------------------------------------------
    if overwrite or not os.environ.get("ANTHROPIC_API_KEY"):
        key = get_secret(secret_scope, secret_key)
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
            set_vars["ANTHROPIC_API_KEY"] = "(from databricks secret)"

    # --- Data directory -----------------------------------------------------
    if volume_path is not None and (overwrite or not os.environ.get("DATA_DIR")):
        vp = str(Path(volume_path))
        os.environ["DATA_DIR"] = vp
        set_vars["DATA_DIR"] = vp

    return set_vars
