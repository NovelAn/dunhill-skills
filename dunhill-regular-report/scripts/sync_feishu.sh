#!/usr/bin/env bash
# Sync Dunhill report to Feishu (Lark) cloud document via @larksuite/cli.
#
# Usage:
#   bash sync_feishu.sh <markdown_file> <title> [--folder <folder_token>] [--update <doc_token>]
#
# Prerequisites:
#   - @larksuite/cli installed globally: npm install -g @larksuite/cli
#   - Authenticated: npx @larksuite/cli auth login
#
# CLI: npx @larksuite/cli docs +create / +update

set -euo pipefail

MARKDOWN_FILE="$1"
TITLE="${2:-Dunhill Report}"
FOLDER_TOKEN=""
DOC_TOKEN=""

shift 2

while [[ $# -gt 0 ]]; do
    case "$1" in
        --folder)
            FOLDER_TOKEN="$2"
            shift 2
            ;;
        --update)
            DOC_TOKEN="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [[ ! -f "$MARKDOWN_FILE" ]]; then
    echo "Error: File not found: $MARKDOWN_FILE"
    exit 1
fi

# Resolve to absolute path
MARKDOWN_ABS="$(cd "$(dirname "$MARKDOWN_FILE")" && pwd)/$(basename "$MARKDOWN_FILE")"

if [[ -n "$DOC_TOKEN" ]]; then
    echo "Updating existing document: $DOC_TOKEN"
    npx @larksuite/cli docs +update "$DOC_TOKEN" --markdown "@${MARKDOWN_ABS}" --title "$TITLE"
    echo "Document updated: $DOC_TOKEN"
else
    ARGS=("docs" "+create" "--title" "$TITLE" "--markdown" "@${MARKDOWN_ABS}" "--api-version" "v2")

    if [[ -n "$FOLDER_TOKEN" ]]; then
        ARGS+=("--folder-token" "$FOLDER_TOKEN")
    fi

    echo "Creating new document: $TITLE"
    RESULT=$(npx @larksuite/cli "${ARGS[@]}")
    echo "$RESULT"
fi
