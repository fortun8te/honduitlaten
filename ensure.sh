#!/bin/sh
# Launches the bot; dogbot.lock makes extra launches exit straight away.
cd "$(dirname "$0")"
nohup "$PWD/run.sh" >> bot.log 2>&1 &
