#!/bin/bash
cd -P "$(dirname "$0")"
set -e
if [ ! -x .venv/bin/python ]; then
  /usr/bin/python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements-macos.txt
exec .venv/bin/python main.py
