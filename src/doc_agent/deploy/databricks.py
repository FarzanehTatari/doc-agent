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

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
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


# ---------------------------------------------------------------------------
# Upload / download helpers
# ---------------------------------------------------------------------------
#
# These run on the LAPTOP (not inside Databricks). They push a canonical JSON
# produced by the MATLAB Extract step up to a Unity Catalog Volume so the
# Databricks-side generate / export workflow can find it. The same module
# provides the inverse — pulling generated docs back down so you can keep a
# local copy or feed them to git.
#
# Two transports are supported, picked in order:
#   1) Databricks Python SDK  (`pip install databricks-sdk`) — preferred,
#      uses your CLI profile, gives proper error messages on auth failure.
#   2) `databricks` CLI in subprocess — fallback, only needs the binary on
#      PATH and `databricks configure` to have been run.
#
# If neither is available, the helpers raise a clear error pointing at the
# install instructions.

DEFAULT_VOLUME_PATH = "/Volumes/main/doc_agent/project_lib"


@dataclass
class UploadResult:
    """Outcome of one upload — useful for logging in scripts and notebooks."""

    src: Path
    dst: str                # the dbfs:/Volumes/... destination
    bytes_copied: int
    transport: str          # "sdk" or "cli"


def _sdk_workspace_client():
    """Return a Databricks SDK WorkspaceClient if importable; else None."""
    try:
        from databricks.sdk import WorkspaceClient  # type: ignore
        return WorkspaceClient()
    except Exception:
        return None


def _cli_available() -> bool:
    """Return True iff the `databricks` CLI is on PATH."""
    return shutil.which("databricks") is not None


def _ensure_transport() -> str:
    """Pick the upload transport, or raise a clear actionable error."""
    if _sdk_workspace_client() is not None:
        return "sdk"
    if _cli_available():
        return "cli"
    raise RuntimeError(
        "No Databricks transport available. Install one of:\n"
        "  • Python SDK:   pip install databricks-sdk\n"
        "  • CLI:          brew install databricks  (or see docs.databricks.com/dev-tools/cli)\n"
        "Then run `databricks configure` once to set workspace URL + PAT."
    )


def _validate_canonical_json(path: Path) -> None:
    """Cheap sanity check — fail before uploading garbage.

    Confirms the file parses as JSON and looks like a CanonicalModel (has a
    `model.name` field). We avoid importing the full Pydantic model here so
    the helper still works in stripped-down environments — but if pydantic is
    around we use it for a stricter check.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: not valid JSON ({e})") from e

    if not isinstance(data, dict) or "model" not in data:
        raise ValueError(
            f"{path}: doesn't look like a canonical model — missing top-level 'model' key."
        )

    try:
        from doc_agent.extract import CanonicalModel  # local import — optional
        CanonicalModel.model_validate(data)
    except ImportError:
        pass  # full validation unavailable; basic shape check above is enough.


def push_canonical_json(
    local_path: str | os.PathLike[str],
    *,
    volume_path: str = DEFAULT_VOLUME_PATH,
    subdir: str = "extracted",
    validate: bool = True,
    overwrite: bool = True,
) -> UploadResult:
    """Push one canonical JSON file from the laptop to a UC Volume.

    Args:
        local_path:   path to the canonical JSON on the laptop.
        volume_path:  root of the Volume on Databricks; the file lands at
                      `<volume_path>/<subdir>/<filename>`.
        subdir:       sub-folder under the Volume root — defaults to
                      "extracted" to match `settings.extracted_dir`.
        validate:     when True (default), refuse to upload anything that
                      doesn't parse as a CanonicalModel.
        overwrite:    when False, fail if the destination already exists.

    Returns:
        UploadResult — what was copied, how, and where.
    """
    src = Path(local_path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(src)
    if src.suffix.lower() != ".json":
        raise ValueError(f"Expected a .json file, got {src.suffix!r}.")
    if validate:
        _validate_canonical_json(src)

    dst_dir = volume_path.rstrip("/") + "/" + subdir.strip("/")
    dst = f"{dst_dir}/{src.name}"
    transport = _ensure_transport()

    if transport == "sdk":
        ws = _sdk_workspace_client()
        assert ws is not None
        # Make sure the parent path exists. Files API uses POSIX semantics
        # on Volumes; mkdirs is a no-op if already present.
        try:
            ws.files.create_directory(dst_dir)
        except Exception:
            pass
        with src.open("rb") as fh:
            ws.files.upload(dst, fh, overwrite=overwrite)
    else:  # cli
        # databricks fs cp wants the dbfs: prefix for Volumes.
        cmd = ["databricks", "fs", "cp"]
        if overwrite:
            cmd.append("--overwrite")
        cmd += [str(src), f"dbfs:{dst}"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"databricks fs cp failed (exit {proc.returncode}):\n"
                f"  stdout: {proc.stdout.strip()}\n  stderr: {proc.stderr.strip()}"
            )

    return UploadResult(
        src=src, dst=f"dbfs:{dst}", bytes_copied=src.stat().st_size, transport=transport
    )


def push_all_canonicals(
    local_dir: str | os.PathLike[str] | None = None,
    *,
    volume_path: str = DEFAULT_VOLUME_PATH,
    validate: bool = True,
    overwrite: bool = True,
) -> list[UploadResult]:
    """Push every canonical JSON found in a local directory.

    When `local_dir` is None, uses `settings.extracted_dir` from the active
    config (which respects `DATA_DIR` if set).
    """
    if local_dir is None:
        from doc_agent.config import settings
        local_dir = settings.extracted_dir
    root = Path(local_dir).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    results: list[UploadResult] = []
    for p in sorted(root.glob("*.json")):
        results.append(
            push_canonical_json(
                p, volume_path=volume_path, validate=validate, overwrite=overwrite,
            )
        )
    return results


def pull_generated(
    *,
    model_name: str,
    volume_path: str = DEFAULT_VOLUME_PATH,
    local_dir: str | os.PathLike[str] | None = None,
) -> list[Path]:
    """Download every generated `.md` for a model back to the laptop.

    The inverse of `push_canonical_json`: pulls from
    `<volume_path>/generated/<model_name>/` into a local folder (defaults to
    `<settings.data_dir>/generated/<model_name>/`).

    Returns the list of local files written.
    """
    if local_dir is None:
        from doc_agent.config import settings
        local_dir = settings.data_dir / "generated" / model_name
    dst_dir = Path(local_dir).expanduser().resolve()
    dst_dir.mkdir(parents=True, exist_ok=True)

    src_dir = f"{volume_path.rstrip('/')}/generated/{model_name}"
    transport = _ensure_transport()
    written: list[Path] = []

    if transport == "sdk":
        ws = _sdk_workspace_client()
        assert ws is not None
        for entry in ws.files.list_directory_contents(src_dir):
            if not entry.path.endswith(".md"):
                continue
            local = dst_dir / Path(entry.path).name
            with ws.files.download(entry.path).contents as stream:
                local.write_bytes(stream.read())
            written.append(local)
    else:  # cli
        cmd = ["databricks", "fs", "cp", "--recursive", "--overwrite",
               f"dbfs:{src_dir}", str(dst_dir)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"databricks fs cp --recursive failed (exit {proc.returncode}):\n"
                f"  stderr: {proc.stderr.strip()}"
            )
        written = sorted(dst_dir.glob("*.md"))

    return written
