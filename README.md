# Honduitlaten
Telegram bot (@honduitlatenbot) for the evening rota between Michael and his brother Christian: dishes at 18:30, dogs at 21:45 (Amsterdam time). Parents get pinged if something's left. Python standard library + SQLite, long polling.

Setup: `.env` with `DOGS_TELEGRAM_BOT_TOKEN` and `OWNER_ID`, then `set -a; . ./.env; python3 dogbot.py setup` (name + commands).
Start: `./ensure.sh` (launches run.sh; dogbot.lock stops duplicates). Stop: `p=$(cat dogbot.lock); kill $(ps -o ppid= -p $p) $p`
Tests: `python3 -m unittest test_dogbot`

Use: the owner taps Start, sends /invite and forwards the two links. /week shows this week and next; tap a day for i'm off / swap / i'll take it. Typing works too ("away 20-27 oct", "not fri"). Planning goes 2 weeks ahead. Each night: ✅ done or 🙅 can't (passes just that job to the other).
