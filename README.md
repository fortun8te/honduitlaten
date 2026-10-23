# Honduitlaten

A small private Telegram bot for two walkers and up to two parents. It shares the evening dog walks and dishes, handles unavailable days and swaps, and asks parents for help when needed. It runs from a shell with Python and SQLite; no Node, containers, database server, web server, or paid hosting is needed on the Pi.

Times use **Europe/Amsterdam**, including summer/winter time: dishes at **18:30**, dogs at **21:45**. Escalation is at 21:00 for dishes and 23:00 for dogs; completion remains possible until 03:00 the next morning. Keep the Pi's clock synchronized.

## Raspberry Pi 2B setup

Use **Raspberry Pi OS Lite, 32-bit**, with Python **3.9 or newer**. The Pi 2B needs wired Ethernet or a supported USB Wi-Fi adapter. Enable SSH during OS setup if you want to use it without a monitor. Use a reliable power supply and SD card.

On the Pi:

```sh
sudo apt update
sudo apt install -y python3 tzdata ca-certificates
python3 --version
```

Copy this folder to your Pi user account, for example `~/honduitlaten`. Preserve the existing `dogbot.db` when moving an existing bot; stop the old instance first and use the backup command below to copy its state safely. Don't run the same Telegram token on two computers at once.

```sh
cd ~/honduitlaten
chmod +x run.sh ensure.sh
./run.sh setup
./run.sh doctor
./run.sh run
```

Setup asks for the **BotFather token** without displaying it, and your **numeric Telegram user ID** (not a username or the bot's ID). Obtain your own ID from a trusted source. Settings are saved in `.env` with private file permissions. Format validation is offline; it does not prove the token is accepted by Telegram. Existing environment variables override `.env`.

The final command runs in the foreground. Press **Ctrl+C** to stop it. Open the bot in Telegram with the owner account and tap Start. Optionally run `./run.sh profile` once to update the Telegram name and menu. This contacts Telegram; setup and doctor do not. Once the foreground check works, stop it and enable automatic startup:

```sh
./run.sh install
./run.sh status
./run.sh logs
```

Run `install` as your normal Pi user, **without sudo**. It requests sudo only for installing/managing the system service. The bot runs as your normal user. The service starts at boot, restarts after crashes, waits between retries, and uses the system journal instead of an endlessly growing `bot.log`. Invalid configuration and duplicate-instance exits stop rather than repeatedly restarting.

## Everyday family flow

1. The owner taps **Start** and opens **Family** or `/invite` to get the walker and parent invite links. Reopening this screen keeps the same links. Only the owner's explicit **Replace links** confirmation invalidates old links; existing family members remain joined.
2. Share each link only with the intended person. There are two walker places and two parent places.
3. **Today** shows both chores and their status. You can mark your own task done before its reminder. **Planning** shows a compact month-ahead rota in weekly pages, with separate actions for availability and swaps.
4. For tonight, use the reminder's **Done** or **Can't** action. Can't passes only that chore, so dishes and dogs remain separate.
5. If both walkers are unavailable, parents are asked for help. A parent choosing to cover means they have taken responsibility; they must still mark the chore done after doing it. Each person can choose Dutch or English with `/lang`.

**Availability:** open `/availability` or its planning button, choose **I can't** or **I'm available again**, and select one or several dates on the compact calendar. Already-unavailable days are marked. **Review** shows the selected dates and the effect on both chores; **Confirm** saves the whole batch. Selecting, reviewing and cancelling are private drafts: they do not change the rota or notify anyone else. A database error rolls back the whole batch. If the plan or cutoff changed while you were reviewing, review it again before saving.

Typed availability changes use the same private review and confirmation flow. A date range outside the 31-day window (today plus 30 days) is rejected as a whole. Today's dishes can change before 21:00 and dogs before 23:00. Becoming available again does not take an already-delivered chore away from its current person; completed tasks and parent coverage stay intact. If a confirmation screen cannot update, the visible question keeps its original meaning. A saved change remains saved even if its acknowledgement needs retrying.

**Swaps:** choose a date, review the proposed request privately, then confirm sending it. The other walker still needs to accept before the assignment changes. **Requests** (`/requests`) shows incoming requests to accept/decline and your outgoing requests to withdraw. Repeated taps do not send duplicate requests. Review the scope shown on the request: it asks who will walk the dogs; dishes follow their separate scheduling rules.

**History and corrections:** **History** (`/history`) shows your own chores from today and the previous six days. If you tapped Done by mistake, or forgot to confirm work you did, open its correction, review it privately and confirm. You can correct only your own eligible record. Confirmation updates the task and its points together and tells parents about the correction. An undone completion is **unconfirmed**, not proof that the chore was not done. Older records stay outside the correction window.

Parent alerts and correction notices are saved and retried after a restart; stale queued notices are cancelled when the work changes. Parent coverage, both-walkers-unavailable days and outages preserve the rota's history so later dates do not randomly switch. After an overnight outage, the bot reports **unconfirmed work**, without claiming it was never done.

**Points stay simple:** each completed dog walk or dish task earns one point for the person who did it. Today shows your current-month total; **Points** shows family totals, a previous-month view and a link to History. Parent takeovers count only after completion. Repeated taps never add extra points. Completing or correcting after midnight credits the scheduled chore date, including at month end. Undoing a completion removes that task's point. Points are informational and do not change the rota or create penalties. Existing completion history contributes automatically.

The bot keeps its schedule and membership in `dogbot.db` across restarts. An invite link is not a public sign-up link; don't post it publicly. Use the current in-chat help/menu for the available shortcuts.

## Shell controls

Run these from the project folder:

| Command | Purpose |
|---|---|
| `./run.sh` or `./run.sh run` | Run in the foreground |
| `./run.sh setup` | Create private settings; refuses to overwrite existing settings |
| `./run.sh profile` | Update the Telegram bot name and command menu (contacts Telegram) |
| `./run.sh doctor` | Offline checks for settings, time zone, database and running process |
| `./run.sh status` | Process, recent poll/schedule health and, on the Pi, service status |
| `./run.sh logs` | Last 80 service log lines |
| `./run.sh start` | Start the installed service |
| `./run.sh stop` | Stop the installed service |
| `./run.sh restart` | Restart the installed service |
| `./run.sh backup backups/before-update.db` | Save a consistent SQLite backup, even while running |
| `./run.sh restore backups/before-update.db` | Restore while stopped; refuses a running instance |

`ensure.sh` is retained as a compatibility shortcut for `./run.sh start`. It requires the installed service. It no longer creates hidden background loops. Service commands require systemd on Linux; foreground operation and offline checks also work on macOS.

To watch logs continuously: `sudo journalctl -u honduitlaten.service -f`. To disable automatic startup: `sudo systemctl disable --now honduitlaten.service`.

## Backup, restore and updates

Backups contain family names, Telegram IDs and planning data. Keep them private and copy important backups off the SD card. Backup files are created with private permissions and an existing backup is never overwritten. SQLite's backup API includes committed changes that may still be in a WAL file. The finished backup replaces a temporary file atomically.

Before updating source files:

```sh
./run.sh backup backups/before-update.db
./run.sh stop
# Copy the updated source files here, preserving .env and dogbot.db.
./run.sh doctor
python3 -m unittest discover -v
./run.sh start
./run.sh status
```

To restore a previous database:

```sh
./run.sh stop
./run.sh backup backups/before-restore.db
./run.sh restore backups/before-update.db
./run.sh doctor
./run.sh start
```

Restore replaces the current database. It validates the backup first and holds the same exclusive lock as the bot during replacement. Keep all other database tools closed during restore. If the bot is running in another terminal, Ctrl+C there first. Do not remove lock files to force a restore: the lock is attached to the open file and removing it defeats duplicate-process protection.

To change settings, edit `.env` locally and restart. Optional `DOGBOT_DB` selects another database; relative paths are resolved against the project folder. Its parent directory must already exist and be writable. A separate database also uses a separate lock. Token and owner ID names are unchanged from the original bot. Optional `DOGBOT_LOCK` and `DOGBOT_HEALTH` override the lock and health record paths; normally leave these unset. The defaults are the database path followed by `.lock` and `.health.json`. Health reports require a successful poll and schedule check within the last three minutes; a held lock alone does not mean the bot is healthy.

## Troubleshooting

- **Missing/invalid settings:** run setup, or correct `.env`. Values are parsed as plain text; shell commands and variable expansions in `.env` are never executed.
- **Service won't start:** run `./run.sh doctor`, then `./run.sh logs`. Confirm the folder still exists and the Pi user can write to it.
- **Already running:** stop the other foreground/service instance. Do not run two copies using the same token.
- **No Telegram replies:** check internet access, system clock, token and whether another machine uses that token. Offline doctor checks cannot prove Telegram connectivity.
- **Settings changed:** restart the service. Reinstall the service if you move the project folder or Python executable.
- **Database problem:** stop, copy the files somewhere safe, and restore a known good backup. Do not delete the database to try to fix startup.

## Try the flow without Telegram

```sh
python3 preview.py --port 8768
```

Open `http://127.0.0.1:8768`. This is a local simulator with sample family members and five times of day. Try both sides of a swap, mark a chore done, switch to the parent view, and test after-midnight completion. It calls the real bot handlers with a fake Telegram connection and temporary in-memory data. It never loads `.env` or contacts Telegram. Stop with Ctrl+C. The Pi does not need to run this preview.

## Verification and remaining hardware check

All automated tests run without sending Telegram messages:

```sh
python3 -m unittest discover -v
```

On 23 October 2026, **207 offline application/deployment tests passed** in an emulated **Linux ARMv7 32-bit** Python 3.11 environment with networking disabled (211 discovered, four Docker-only tests skipped in that run). The suite includes 300 seeded scheduling sequences, all 31 planning dates, atomic multi-date availability, private swap/correction confirmations, stable invitation links, monthly points and backup persistence, outage recovery, failed-screen retries, stale actions, early/after-midnight completion, parent takeover and navigation that keeps the current panel live. The **four Docker integration tests also passed separately** against the built ARMv7 image, covering container lifecycle, private backup import, Compose configuration and exclusion of secrets from image layers. Source hashes inside the running image matched the checked source files. ARM emulation verifies software compatibility, not physical Pi speed or boot reliability.

Deployment tests cover missing configuration, secret redaction, paths containing spaces, safe configuration loading, private settings, online SQLite backup, restore integrity, and refusing restore while running. Linux service syntax was checked with `systemd-analyze verify` in an existing Debian container; this does not verify boot or performance on the Pi itself.

**The Pi was unavailable during development.** Before relying on it, check on the actual Pi:

- Foreground startup and an owner `/start` reply work.
- All four intended accounts can join through the correct links.
- Availability, swap acceptance/rejection, completion and parent coverage work in Telegram.
- A service restart preserves membership and planning; logs have no token exposure.
- A reboot starts the service without logging in.
- Disconnect/reconnect the network and confirm replies recover without duplicate reminders.
- Leave it running through the dish/dog reminder times and following morning; verify timing and recovery.
- Make a backup, stop the service, restore it, and verify the plan remains correct.

A test pass or valid service file is not a substitute for those device and real Telegram checks.

## NAS / Docker option

This is an alternative home for the **same bot**, not a second instance to run beside the Pi. The Pi's direct shell setup above stays the lighter choice. On a NAS with Docker/Compose (or a compatible Compose project manager), copy this folder and keep the data volume persistent. The official Python base supports common Intel/AMD NAS CPUs, ARM64, and ARMv7; Docker selects the host architecture when building. A NAS vendor's container support and permissions still need checking on the actual device.

Create `.env` from `.env.example`, enter the real token and owner ID locally, and set its permissions to `600`. If Python is available on that machine, `./run.sh setup` can do this instead. Do **not** include a real `.env` in an image or repository. `.dockerignore` only allows application source into the build; Compose passes settings at runtime. Docker administrators can still inspect container environment settings, so grant NAS/Docker access only to trusted people.

From the project folder on the NAS:

```sh
cp .env.example .env
chmod 600 .env
# Edit .env locally with the real BotFather token and your Telegram user ID.
docker compose build
docker compose run --rm bot doctor
docker compose up -d
docker compose ps
docker compose logs --tail=80 bot
```

Before startup, `doctor` will correctly report no running process/health record. After startup allow up to roughly two minutes for the first healthy check. The container polls Telegram over outbound HTTPS, so **no inbound port, router forwarding or public website is needed**. The service uses a non-root user, a read-only application filesystem, bounded logs, and a persistent named volume at `/data`. SQLite, its lock and health record all stay in that volume. No credentials are baked into the image.

To check it or manage it:

```sh
docker compose exec bot python3 /app/dogbotctl.py healthcheck
docker compose logs --tail=80 bot
docker compose restart bot
docker compose stop bot
docker compose up -d
```

`healthcheck` exits successfully only when the lock is held by the recorded live process and both Telegram polling and the schedule check succeeded within three minutes. Docker reports unhealthy after repeated failures. **Docker does not restart a container solely because it becomes unhealthy**; the bot retries network failures itself, and `unless-stopped` restarts a crashed process or brings it back after the Docker host restarts. A deliberate `stop` remains stopped until you start it again. NAS monitoring can alert on unhealthy status.

Update the Telegram profile/menu explicitly with `docker compose run --rm bot profile`. This contacts Telegram. `doctor`, backup and restore do not.

### Docker backups and restore

Back up the live database and copy the completed backup off the NAS volume:

```sh
docker compose exec bot python3 /app/dogbotctl.py backup /data/before-update.db
docker compose cp bot:/data/before-update.db ./before-update.db
```

Choose a new filename each time. For a backup already stored in the volume:

```sh
docker compose stop bot
docker compose run --rm bot backup /data/before-restore.db
docker compose run --rm bot restore /data/before-update.db
docker compose up -d
```

To import an existing Pi backup before first startup:

```sh
# Stop the old Pi bot first; use its ./run.sh backup command to make pi-backup.db.
docker compose create
container_id=$(docker compose ps -aq bot)
docker cp ./pi-backup.db "$container_id:/data/import.db"
# The copied file may have a different owner; preserve mode 600 and give the bot access.
docker compose run --rm --user 0:0 --entrypoint chown bot 10001:10001 /data/import.db
docker compose run --rm bot restore /data/import.db
docker compose up -d
```

The one-off ownership command fixes the copied backup's owner without weakening its private permissions. Only this file operation runs as root; restore and the bot run as the non-root user. The imported backup is read-only input; the restored database belongs to that user. Keep your original backup until the NAS bot's plan and membership have been verified.

To update, make a backup, copy the new source files while preserving `.env`, then run `docker compose build` and `docker compose up -d`. The named volume survives container replacement and ordinary `docker compose down`. **Do not use `docker compose down -v` or delete the volume unless you intend to erase the bot's data.**

If you choose a host folder instead of the provided named volume, create it and grant UID/GID `10001:10001` write access before mounting it at `/data`. Do not solve permission errors by running the whole bot as root. A named volume avoids most NAS folder ownership differences.

### Offline container verification

The opt-in Docker test uses a fake Telegram transport and disables container networking. It checks non-root execution, health, graceful stop, recreation with the same database, backup/restore and absence of runtime credentials from image configuration/history. It creates and removes only uniquely named test containers and volumes:

```sh
docker build -t honduitlaten:local .
DOGBOT_TEST_DOCKER=1 python3 -m unittest test_container -v
```

This prepares and verifies the container locally. **No NAS was identified or deployed to.** Actual NAS reboot behaviour, vendor Compose support, outbound network access and real family Telegram interactions remain device checks before relying on it.
