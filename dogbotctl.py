#!/usr/bin/env python3
"""Offline setup and operations. Python 3.9+, standard library only."""
import argparse
import fcntl
import getpass
import json
import time
import os
import pwd
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
SERVICE = 'honduitlaten.service'
KEYS = {'DOGS_TELEGRAM_BOT_TOKEN', 'OWNER_ID', 'DOGBOT_DB', 'DOGBOT_LOCK', 'DOGBOT_HEALTH'}


def configuration(required=True):
    values = {}
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:]
            key, sep, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if not sep or key not in KEYS:
                raise ValueError('Invalid .env entry; use only the keys in .env.example.')
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '\"\'':
                value = value[1:-1]
            values[key] = value
    for key in KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    if required:
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}', values.get('DOGS_TELEGRAM_BOT_TOKEN', '')):
            raise ValueError('Missing or invalid bot token. Run ./run.sh setup.')
        if not re.fullmatch(r'[1-9][0-9]*', values.get('OWNER_ID', '')):
            raise ValueError('Missing or invalid OWNER_ID. Run ./run.sh setup.')
    db = Path(values.get('DOGBOT_DB') or ROOT / 'dogbot.db').expanduser()
    values['DOGBOT_DB'] = str(db if db.is_absolute() else ROOT / db)
    for key in ('DOGBOT_LOCK', 'DOGBOT_HEALTH'):
        if values.get(key):
            path = Path(values[key]).expanduser()
            values[key] = str(path if path.is_absolute() else ROOT / path)
    return values


def acquire_lock():
    config = configuration(False)
    handle = Path(config.get('DOGBOT_LOCK') or config['DOGBOT_DB'] + '.lock').open('a+')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise ValueError('Bot is running. Stop it before restoring.')
    return handle


def running():
    try:
        handle = acquire_lock()
    except ValueError:
        return True
    handle.close()
    return False


def db_source(path):
    if not path.is_file():
        raise ValueError('Database does not exist yet; start the bot first.')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
    try:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Database integrity check failed.')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'members', 'kv', 'off'}.issubset(tables):
            raise ValueError('This is not a Honduitlaten database.')
    except Exception:
        db.close()
        raise
    return db


def copy_database(source, destination):
    if source.resolve() == destination.resolve():
        raise ValueError('Source and destination must differ.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = db_source(source)
    fd, temp = tempfile.mkstemp(prefix='.dogbot-backup-', dir=str(destination.parent))
    os.close(fd)
    try:
        dst = sqlite3.connect(temp)
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
        with open(temp, 'rb') as stream:
            os.fsync(stream.fileno())
        os.replace(temp, destination)
        directory = os.open(str(destination.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        src.close()
        if os.path.exists(temp):
            os.unlink(temp)


def setup():
    if (ROOT / '.env').exists():
        raise ValueError('.env already exists; edit it locally to change settings.')
    token = getpass.getpass('BotFather token (hidden): ').strip()
    owner = input('Your numeric Telegram user ID: ').strip()
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}', token):
        raise ValueError('Invalid token format; nothing saved.')
    if not re.fullmatch(r'[1-9][0-9]*', owner):
        raise ValueError('OWNER_ID must be a positive number; nothing saved.')
    fd = os.open(str(ROOT / '.env'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write('DOGS_TELEGRAM_BOT_TOKEN=' + token + '\nOWNER_ID=' + owner + '\n')
    print('Saved private settings. Run ./run.sh doctor, then ./run.sh run.')


def systemctl(*args):
    if sys.platform != 'linux' or not shutil.which('systemctl'):
        raise ValueError('Service commands need Raspberry Pi OS (systemd). Use ./run.sh run here.')
    return subprocess.run(['sudo', 'systemctl', *args], check=True)


def unit_text(user, python=sys.executable):
    def quote(value, expand_dollars=False):
        if '\n' in value or '\r' in value:
            raise ValueError('Install path cannot contain a newline.')
        return '\"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$' if expand_dollars else '$') + '\"'
    return ('[Unit]\nDescription=Honduitlaten family bot\nWants=network-online.target\n'
            'After=network-online.target\nStartLimitIntervalSec=0\n\n[Service]\nType=simple\n'
            'User=' + user + '\nWorkingDirectory=' + str(ROOT).replace('%', '%%') + '\n'
            'ExecStart=' + quote(python, True) + ' ' + quote(str(ROOT / 'dogbotctl.py'), True) + ' run\n'
            'Restart=on-failure\nRestartSec=15\nRestartPreventExitStatus=2 3\n'
            'TimeoutStopSec=45\nUMask=0077\nNoNewPrivileges=true\nPrivateTmp=true\n'
            'Environment=PYTHONUNBUFFERED=1\nStandardOutput=journal\nStandardError=journal\n'
            '\n[Install]\nWantedBy=multi-user.target\n')


def install():
    configuration()
    if sys.platform != 'linux' or not shutil.which('systemctl'):
        raise ValueError('Install this service on Raspberry Pi OS, not this computer.')
    if os.geteuid() == 0:
        raise ValueError('Run install as your regular Pi user, without sudo. It requests sudo when needed.')
    if running():
        raise ValueError('Stop the foreground bot before installing the service.')
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / SERVICE
        source.write_text(unit_text(pwd.getpwuid(os.getuid()).pw_name))
        subprocess.run(['sudo', 'install', '-m', '644', str(source), '/etc/systemd/system/' + SERVICE], check=True)
    systemctl('daemon-reload')
    systemctl('enable', '--now', SERVICE)
    print('Service installed and enabled at boot. Check ./run.sh status and ./run.sh logs.')


def health_status():
    active = running()
    print('Bot process: ' + ('running' if active else 'stopped'))
    config = configuration(False)
    path = Path(config.get('DOGBOT_HEALTH') or config['DOGBOT_DB'] + '.health.json')
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError('Invalid health record')
        pid = data.get('pid')
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ValueError('Missing process identity')
        os.kill(pid, 0)
        lock_path = Path(config.get('DOGBOT_LOCK') or config['DOGBOT_DB'] + '.lock')
        if lock_path.read_text().strip() != str(pid):
            raise ValueError('Process identity changed')
        ages = [time.time() - float(data.get(key) or 0) for key in ('last_poll', 'last_tick')]
        healthy = active and not data.get('stopped') and all(0 <= age < 180 for age in ages)
        print('Bot activity: ' + ('healthy; recent Telegram poll and schedule check' if healthy else 'not verified healthy; polling or schedule check is stale/stopped'))
        return healthy
    except (OSError, ValueError, TypeError):
        print('Bot activity: no usable health record yet')
        return False


def doctor():
    errors = []
    try:
        config = configuration()
        print('Settings: valid format (Telegram connection not tested)')
    except ValueError as exc:
        errors.append(str(exc))
        config = configuration(False)
    try:
        ZoneInfo('Europe/Amsterdam')
        print('Amsterdam time zone: available')
    except Exception:
        errors.append('Time zone missing: install tzdata on the Pi.')
    path = Path(config['DOGBOT_DB'])
    if not path.parent.is_dir() or not os.access(path.parent, os.W_OK):
        errors.append('Database folder must exist and be writable.')
    if path.exists():
        try:
            db_source(path).close()
            print('Database: integrity OK')
        except (ValueError, sqlite3.Error):
            errors.append('Database could not be read or failed its integrity check.')
    else:
        print('Database: will be created on first start')
    health_status()
    for error in errors:
        print('Needs attention: ' + error)
    return 2 if errors else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='run', choices=['run', 'healthcheck', 'profile', 'setup', 'doctor', 'status', 'install', 'start', 'stop', 'restart', 'logs', 'backup', 'restore'])
    parser.add_argument('file', nargs='?')
    args = parser.parse_args()
    if args.command in ('backup', 'restore') and not args.file:
        parser.error('backup and restore require a file path')
    if args.command == 'setup':
        setup()
    elif args.command == 'doctor':
        return doctor()
    elif args.command == 'healthcheck':
        return 0 if health_status() else 1
    elif args.command == 'status':
        health_status()
        if sys.platform == 'linux' and shutil.which('systemctl'):
            subprocess.run(['systemctl', '--no-pager', 'status', SERVICE])
    elif args.command == 'install':
        install()
    elif args.command in ('start', 'stop', 'restart'):
        systemctl(args.command, SERVICE)
    elif args.command == 'logs':
        if sys.platform != 'linux' or not shutil.which('journalctl'):
            raise ValueError('Logs are in the foreground terminal here; on the Pi use this command.')
        subprocess.run(['sudo', 'journalctl', '-u', SERVICE, '-n', '80', '--no-pager'], check=True)
    elif args.command == 'backup':
        destination = Path(args.file).expanduser()
        if destination.exists():
            raise ValueError('Backup file already exists. Choose a new filename.')
        copy_database(Path(configuration(False)['DOGBOT_DB']), destination)
        print('Backup saved.')
    elif args.command == 'restore':
        with acquire_lock():
            destination = Path(configuration(False)['DOGBOT_DB'])
            # Old WAL files must never be replayed over the restored database.
            if destination.exists():
                db = sqlite3.connect(str(destination))
                try:
                    if db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                        raise ValueError('Database is busy; close all other database users first.')
                finally:
                    db.close()
            copy_database(Path(args.file).expanduser(), destination)
            for suffix in ('-wal', '-shm'):
                sidecar = Path(str(destination) + suffix)
                if sidecar.exists():
                    sidecar.unlink()
        print('Database restored. Start the bot when ready.')
    else:
        values = configuration()
        os.environ.update(values)
        os.execv(sys.executable, [sys.executable, str(ROOT / 'dogbot.py')] + (['setup'] if args.command == 'profile' else []))
    return 0


if __name__ == '__main__':
    if sys.version_info < (3, 9):
        sys.exit('Python 3.9 or newer is required.')
    try:
        sys.exit(main())
    except (ValueError, OSError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        # Do not echo unknown exception details: paths and subprocess args may contain secrets.
        print(str(exc) if isinstance(exc, ValueError) else 'Operation failed. Check file permissions, disk space, and service availability.', file=sys.stderr)
        sys.exit(2)
    except (KeyboardInterrupt, EOFError):
        sys.exit(130)
