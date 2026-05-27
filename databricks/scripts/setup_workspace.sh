#!/usr/bin/env bash
# setup_workspace.sh — one-time Databricks workspace prep for doc-agent.
#
# Run this once after your platform team has given you a workspace + Unity
# Catalog access. Idempotent — re-runs are safe.
#
# What it does:
#   1. Installs the Databricks CLI if missing.
#   2. Prompts you for workspace URL + a Personal Access Token, runs
#      `databricks configure`.
#   3. Creates a secret scope and prompts for your Anthropic API key.
#   4. Creates the Unity Catalog Volume that holds project_lib/.
#
# Adjust the variables at the top to match your workspace conventions.

set -euo pipefail

CATALOG="${CATALOG:-main}"
SCHEMA="${SCHEMA:-doc_agent}"
VOLUME="${VOLUME:-project_lib}"
SECRET_SCOPE="${SECRET_SCOPE:-doc-agent}"
SECRET_KEY="${SECRET_KEY:-anthropic-api-key}"

# --- 1. Databricks CLI --------------------------------------------------------
if ! command -v databricks >/dev/null 2>&1; then
    echo "Installing Databricks CLI…"
    if command -v brew >/dev/null 2>&1; then
        brew tap databricks/tap && brew install databricks
    else
        echo "Please install the Databricks CLI manually:" >&2
        echo "  https://docs.databricks.com/dev-tools/cli/install.html" >&2
        exit 2
    fi
fi

# --- 2. Authenticate ----------------------------------------------------------
if ! databricks current-user me >/dev/null 2>&1; then
    echo "Configuring CLI — you'll be prompted for your workspace URL + PAT."
    databricks configure
fi
echo "Logged in as: $(databricks current-user me --output json | python3 -c 'import sys,json;print(json.load(sys.stdin)["userName"])')"

# --- 3. Secret scope ----------------------------------------------------------
if databricks secrets list-scopes --output json | grep -q "\"name\":\"$SECRET_SCOPE\""; then
    echo "Secret scope '$SECRET_SCOPE' already exists."
else
    echo "Creating secret scope '$SECRET_SCOPE'…"
    databricks secrets create-scope "$SECRET_SCOPE"
fi
echo "Setting secret $SECRET_SCOPE/$SECRET_KEY (paste your Anthropic API key, then Ctrl-D):"
databricks secrets put-secret "$SECRET_SCOPE" "$SECRET_KEY"

# --- 4. Unity Catalog Volume --------------------------------------------------
echo "Ensuring UC schema $CATALOG.$SCHEMA exists…"
databricks schemas create "$SCHEMA" "$CATALOG" 2>/dev/null || true
echo "Ensuring Volume $CATALOG.$SCHEMA.$VOLUME exists…"
databricks volumes create "$CATALOG" "$SCHEMA" "$VOLUME" MANAGED 2>/dev/null || true

VOLUME_PATH="/Volumes/$CATALOG/$SCHEMA/$VOLUME"
echo "Creating top-level subdirectories on the Volume…"
for sub in extracted generated exports rag; do
    databricks fs mkdirs "dbfs:$VOLUME_PATH/$sub" 2>/dev/null || true
done

cat <<EOF

=========================================================
Workspace prepared. Use these values in databricks.yml:

  volume_path:  $VOLUME_PATH
  secret_scope: $SECRET_SCOPE
  secret_key:   $SECRET_KEY

Next:
  databricks bundle deploy --target dev
EOF
