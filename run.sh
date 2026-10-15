#!/bin/sh
# Keeps the bot alive. Exits if another instance holds the lock (code 3).
cd "$(dirname "$0")"
set -a; . ./.env; set +a
while true; do python3 dogbot.py; [ $? -eq 3 ] && exit 0; sleep 5; done
