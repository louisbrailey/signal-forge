#!/usr/bin/env bash
# Signal Forge — local backup wrapper.
#
#   ./backup.sh                 # plaintext snapshot into data/backups/
#   ./backup.sh --encrypt       # prompts for a passphrase, gpg-encrypts
#   ./backup.sh --out ~/sf-bak  # snapshot into a chosen directory
#
# Restore:
#   uv run signalforge restore <path-to-backup>            # asks to confirm
#   uv run signalforge restore <path-to-backup.gpg>        # asks for passphrase
#
# A .pre-restore copy of the current database is kept next to it on restore.
set -euo pipefail
cd "$(dirname "$0")"

ARGS=()
[[ "${1:-}" == "--encrypt" ]] && ARGS+=(--encrypt) && shift || true
if [[ "${1:-}" == "--out" ]]; then ARGS+=(--out-dir "$2"); shift 2; fi

exec uv run signalforge backup "${ARGS[@]}"
