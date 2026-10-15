# Honduitlaatbot
Telegram bot (@honduitlatenbot) for the evening rota between Michael and his brother Christian. Om en om: one of them has the evening and does both chores, dishes at 18:30 and dogs at 21:45 (Amsterdam time). Buttons only, Dutch. Python standard library + SQLite, long polling.

Setup: `.env` with `DOGS_TELEGRAM_BOT_TOKEN` and `OWNER_ID`, then `set -a; . ./.env; python3 dogbot.py setup` (name, no commands).
Start: `./ensure.sh` (launches run.sh; dogbot.lock stops duplicates). Stop: `p=$(cat dogbot.lock); kill $(ps -o ppid= -p $p) $p`
Tests: `python3 -m unittest test_dogbot`

Use: the owner taps Start and sends the invite with 📤. ☰ Menu shows tonight, tomorrow and the stand. 📅 Kalender lists your evenings two weeks ahead; tap one to drop the dishes, the dogs or both. The one on duty gets one card at 18:30 (✅ Afwas, ✅ Honden, 🙅 Ik kan niet) and at most one more at 21:45 for the dogs. Everything else arrives silently.

Points: doing the other's chore is +1 for you and -1 for him. A chore still open at 03:00 is -1 for whoever had it and +1 for the other. Whoever is behind automatically gets the other's next chores, from two days out, until it's even; those can't be given away. If both can't, someone else does it and nobody gets points.

Upgrading from the old version: the old tables (nights, off, overrides, weekmsg) stay in the database unused, and parents get nothing for now.
