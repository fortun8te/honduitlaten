#!/bin/sh
# Compatibility entry point: managed service, no detached shell or growing bot.log.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$SCRIPT_DIR/run.sh" start
