#!/bin/bash
# SessionStart hook: prepare an identical environment on every device
# (desktop, laptop, phone) when a Claude Code on the web session starts.
set -euo pipefail

# Only run inside the remote (Claude Code on the web) environment.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Use an isolated virtualenv so the project's pinned deps never collide with
# the container's system (Debian) packages. Idempotent + cache-friendly.
VENV_DIR="$CLAUDE_PROJECT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python3 -m pip install --upgrade pip >/dev/null 2>&1 || true
python3 -m pip install -r requirements.txt

# Make dev tooling (linter / test runner) available for the session.
python3 -m pip install ruff pytest

# Persist the venv for the rest of the session so every command (tests,
# linters, the app) uses the same interpreter.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export VIRTUAL_ENV=\"$VENV_DIR\"" >> "$CLAUDE_ENV_FILE"
  echo "export PATH=\"$VENV_DIR/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi
