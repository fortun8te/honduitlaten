"""Offline deployment checks: never contacts Telegram or changes host services."""
import fcntl
from contextlib import closing
import importlib.util
import os
import json
import time
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ctl', HERE / 'dogbotctl.py')
ctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctl)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dog bot space ')
        self.root = Path(self.tmp.name)
        for name in ('run.sh', 'dogbotctl.py', 'ensure.sh'):
            shutil.copy2(HERE / name, self.root / name)
        self.env = {k: v for k, v in os.environ.items() if k not in ctl.KEYS}
        self.root_patch = patch.object(ctl, 'ROOT', self.root)
        self.root_patch.start()
        self.env_patch = patch.dict(os.environ, self.env, clear=True)
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.root_patch.stop()
        self.tmp.cleanup()

    def call(self, *args):
        return subprocess.run([str(self.root / 'run.sh'), *args], env=self.env, capture_output=True, text=True)

    def db(self, name='dogbot.db'):
        path = self.root / name
        db = sqlite3.connect(path)
        db.executescript('CREATE TABLE members(id); CREATE TABLE kv(k,v); CREATE TABLE off(id,day); INSERT INTO members VALUES(42);')
        db.close()
        return path

    def test_missing_configuration_and_no_secret_echo(self):
        result = self.call()
        self.assertEqual(result.returncode, 2)
        self.assertIn('setup', result.stderr)
        secret = 'TOP-SECRET-INVALID-TOKEN'
        (self.root / '.env').write_text('DOGS_TELEGRAM_BOT_TOKEN=' + secret + '\nOWNER_ID=1\n')
        result = self.call('doctor')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_run_exec_handles_spaces_and_loads_env_without_execution(self):
        token = '123:' + 'a' * 35
        (self.root / '.env').write_text('DOGS_TELEGRAM_BOT_TOKEN=' + token + '\nOWNER_ID=99\nDOGBOT_DB="data with spaces.db"\n')
        (self.root / 'dogbot.py').write_text('import os; print(os.environ["OWNER_ID"]); print(os.environ["DOGBOT_DB"])')
        result = self.call('run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.root / 'data with spaces.db'), result.stdout)
        self.assertNotIn(token, result.stdout)
        (self.root / '.env').write_text('DOGS_TELEGRAM_BOT_TOKEN=$(touch injected)\nOWNER_ID=1\n')
        self.assertEqual(self.call().returncode, 2)
        self.assertFalse((self.root / 'injected').exists())

    def test_backup_restore_and_no_overwrite(self):
        path = self.db()
        backup = self.root / 'backups' / 'good copy.db'
        self.assertEqual(self.call('backup', str(backup)).returncode, 0)
        self.assertEqual(self.call('backup', str(backup)).returncode, 2)
        db = sqlite3.connect(path)
        db.execute('DELETE FROM members')
        db.commit()
        db.close()
        self.assertEqual(self.call('restore', str(backup)).returncode, 0)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT id FROM members').fetchone()[0], 42)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_restore_refuses_running_instance_and_invalid_database(self):
        path = self.db()
        backup = self.root / 'copy.db'
        ctl.copy_database(path, backup)
        with open(str(path) + '.lock', 'a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.call('restore', str(backup))
            self.assertEqual(result.returncode, 2)
            self.assertIn('running', result.stderr)
        invalid = self.root / 'invalid.db'
        invalid.write_text('not a database')
        self.assertEqual(self.call('restore', str(invalid)).returncode, 2)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT id FROM members').fetchone()[0], 42)

    def test_wal_backup_contains_committed_data(self):
        path = self.db()
        db = sqlite3.connect(path)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('INSERT INTO members VALUES(43)')
        db.commit()
        backup = self.root / 'wal.db'
        ctl.copy_database(path, backup)
        with closing(sqlite3.connect(backup)) as copied:
            self.assertEqual(copied.execute('SELECT count(*) FROM members').fetchone()[0], 2)
        db.close()

    def test_unit_quotes_paths_without_token(self):
        unit = ctl.unit_text('pi', '/a path/python3')
        self.assertIn('ExecStart="/a path/python3" "', unit)
        self.assertIn('RestartPreventExitStatus=2 3', unit)
        self.assertNotIn('DOGS_TELEGRAM_BOT_TOKEN', unit)
        self.assertIn('WantedBy=multi-user.target', unit)

    def test_health_requires_process_poll_and_tick(self):
        health = self.root / 'dogbot.db.health.json'
        with open(str(self.root / 'dogbot.db') + '.lock', 'a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock.write(str(os.getpid()))
            lock.flush()
            health.write_text(json.dumps({'pid': os.getpid(), 'last_poll': time.time(), 'last_tick': time.time(), 'stopped': False}))
            self.assertTrue(ctl.health_status())
            health.write_text(json.dumps({'pid': os.getpid(), 'last_poll': time.time() - 181, 'last_tick': time.time()}))
            self.assertFalse(ctl.health_status())
        self.assertFalse(ctl.health_status())
        health.write_text('[]')
        self.assertFalse(ctl.health_status())

    def test_profile_is_explicit_and_loads_configuration(self):
        (self.root / '.env').write_text('DOGS_TELEGRAM_BOT_TOKEN=123:' + 'a' * 35 + '\nOWNER_ID=99\n')
        (self.root / 'dogbot.py').write_text('import sys; print(sys.argv[1:])')
        result = self.call('profile')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("['setup']", result.stdout)

    def test_setup_saves_private_config(self):
        token = '123:' + 'b' * 35
        with patch('getpass.getpass', return_value=token), patch('builtins.input', return_value='42'):
            ctl.setup()
        self.assertEqual((self.root / '.env').stat().st_mode & 0o777, 0o600)
        self.assertEqual(ctl.configuration()['OWNER_ID'], '42')


if __name__ == '__main__':
    unittest.main()
