#!/usr/bin/env bash
# upload_canonical.sh — thin wrapper around `doc-agent deploy push`.
#
# Kept around for muscle-memory and for environments where running the Typer
# CLI is awkward. For everyday use, prefer:
#
#     doc-agent deploy push project_lib/extracted/VSEModel.json
#     doc-agent deploy push-all                 # everything in extracted/
#     doc-agent deploy pull VSEModel            # generated docs back to laptop
#
# Both routes call the same `push_canonical_json` in
# src/doc_agent/deploy/databricks.py, which validates the file against the
# CanonicalModel schema before uploading.
#
# Usage:
#   bash databricks/scripts/upload_canonical.sh project_lib/extracted/VSEModel.json
#   bash databricks/scripts/upload_canonical.sh path/to/file.json \
#       /Volumes/main/doc_agent/project_lib

set -euo pipefail

SRC="${1:-}"
DST="${2:-/Volumes/main/doc_agent/project_lib}"

if [[ -z "$SRC" ]]; then
    echo "usage: $0 <canonical.json> [volume-path]" >&2
    exit 2
fi

exec doc-agent deploy push --volume "$DST" "$SRC"
