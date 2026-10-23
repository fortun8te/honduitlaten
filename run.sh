#!/bin/sh
# One process; systemd manages retries on the Pi.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/dogbotctl.py" "$@"
