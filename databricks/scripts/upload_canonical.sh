#!/usr/bin/env bash
# upload_canonical.sh — push a canonical JSON from the laptop to the Volume.
#
# The MATLAB-driven Extract step still runs on a machine with MATLAB.
# Once it produces project_lib/extracted/<Model>.json, this script copies
# that file to /Volumes/<catalog>/<schema>/project_lib/extracted/ in your
# Databricks workspace, where the Generate notebook / App can pick it up.
#
# Requires:
#   * databricks CLI v0.205+   (`brew install databricks` or `pip install databricks-cli`)
#   * `databricks configure`  has been run once with your workspace URL + PAT
#
# Usage:
#   bash databricks/scripts/upload_canonical.sh project_lib/extracted/VSEModel.json
#   bash databricks/scripts/upload_canonical.sh project_lib/extracted/VSEModel.json \
#       /Volumes/main/doc_agent/project_lib/extracted/
#
# The default destination matches the bundle's `volume_path` variable. If you
# changed that variable, pass an explicit destination as the second argument.

set -euo pipefail

SRC="${1:-}"
DST="${2:-/Volumes/main/doc_agent/project_lib/extracted/}"

if [[ -z "$SRC" ]]; then
    echo "usage: $0 <canonical.json> [dst-volume-path]" >&2
    exit 2
fi
if [[ ! -f "$SRC" ]]; then
    echo "error: file not found — $SRC" >&2
    exit 2
fi
if ! command -v databricks >/dev/null 2>&1; then
    echo "error: databricks CLI not on PATH. See databricks/scripts/setup_workspace.sh" >&2
    exit 3
fi

DST_FILE="${DST%/}/$(basename "$SRC")"

echo "Uploading:"
echo "  src: $SRC"
echo "  dst: $DST_FILE"
databricks fs cp --overwrite "$SRC" "dbfs:$DST_FILE"
echo "OK"
