#!/bin/zsh
set -e

SCRIPT_DIR="${0:A:h:h}"
PYTHON="$SCRIPT_DIR/.venv/bin/python3"

cd "$SCRIPT_DIR"

if [[ ! -x "$PYTHON" ]]; then
  /usr/bin/env python3 -m venv .venv
fi

if ! "$PYTHON" -c "import tos" >/dev/null 2>&1; then
  "$PYTHON" -m pip install --disable-pip-version-check -r requirements.txt
fi

exec "$PYTHON" server.py
