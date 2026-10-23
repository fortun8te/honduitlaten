"""Opt-in real Docker lifecycle tests. Network is disabled; Telegram is replaced in memory.
Run: DOGBOT_TEST_DOCKER=1 python3 -m unittest test_container -v
Build honduitlaten:local first. Creates/removes only its uniquely named test resources.
"""
import json
import gzip
import shutil
import sqlite3
import tarfile
import tempfile
import os
from pathlib import Path
import subprocess
import time
import unittest
import uuid

FAKE_RUNTIME = '''
import dogbot, time
original_health = dogbot.write_health
dogbot.write_health = lambda force=False: original_health(True)
def api(method, **kwargs):
    if method == 'getMe': return {'username':'offline_test_bot'}
    if method == 'getUpdates':
        time.sleep(0.1)
        return []
    return {'message_id':1}
dogbot.api = api
db = dogbot.connect()
dogbot.kv(db, 'container_test_boots', str(int(dogbot.kv(db, 'container_test_boots') or 0) + 1))
db.close()
dogbot.run()
'''


@unittest.skipUnless(os.environ.get('DOGBOT_TEST_DOCKER') == '1', 'opt-in Docker integration')
class ContainerTests(unittest.TestCase):
    def docker(self, *args, check=True):
        result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=60)
        if check and result.returncode:
            self.fail(result.stderr)
        return result

    def test_compose_configuration_is_valid(self):
        with tempfile.TemporaryDirectory(prefix='dogbot-compose-') as folder:
            root = Path(folder)
            shutil.copy2(Path(__file__).parent / 'compose.yaml', root / 'compose.yaml')
            (root / '.env').write_text('DOGS_TELEGRAM_BOT_TOKEN=123:' + 'offline_' * 5 + '\nOWNER_ID=99\n')
            self.docker('compose', '-f', str(root / 'compose.yaml'), 'config', '--quiet')

    def test_build_excludes_secret_files_from_all_layers(self):
        image = 'dogbot-secret-test:' + uuid.uuid4().hex[:12]
        marker = ('never_bake_this_' + uuid.uuid4().hex).encode()
        current = os.environ.get('DOGBOT_TEST_IMAGE', 'honduitlaten:local')
        meta = json.loads(self.docker('image', 'inspect', current).stdout)[0]
        platform = 'linux/' + meta['Architecture']
        if meta.get('Variant'):
            platform += '/' + meta['Variant']
        try:
            with tempfile.TemporaryDirectory(prefix='dogbot-image-') as folder:
                root = Path(folder)
                for name in ('Dockerfile', '.dockerignore', 'dogbot.py', 'dogbotctl.py', 'run.sh'):
                    shutil.copy2(Path(__file__).parent / name, root / name)
                (root / '.env').write_bytes(marker)
                (root / 'dogbot.db').write_bytes(marker)
                self.docker('build', '--platform', platform, '-t', image, str(root))
                archive = root / 'image.tar'
                self.docker('save', '-o', str(archive), image)
                with tarfile.open(archive) as saved:
                    for member in saved:
                        if not member.isfile():
                            continue
                        data = saved.extractfile(member).read()
                        if data[:2] == b'\x1f\x8b':
                            data = gzip.decompress(data)
                        self.assertNotIn(marker, data, member.name)
        finally:
            self.docker('image', 'rm', image, check=False)

    def test_import_private_root_owned_backup(self):
        unique = 'dogbot-import-test-' + uuid.uuid4().hex[:12]
        volume, container = unique + '-data', unique
        image = os.environ.get('DOGBOT_TEST_IMAGE', 'honduitlaten:local')
        self.docker('volume', 'create', volume)
        try:
            self.docker('create', '--name', container, '--network', 'none', '-v', volume + ':/data', image)
            with tempfile.TemporaryDirectory(prefix='dogbot-import-') as folder:
                source = Path(folder) / 'pi-backup.db'
                db = sqlite3.connect(source)
                db.executescript("CREATE TABLE members(id); CREATE TABLE kv(k,v); CREATE TABLE off(id,day); INSERT INTO members VALUES(42);")
                db.close()
                source.chmod(0o600)
                self.docker('cp', str(source), container + ':/data/import.db')
            # Docker Desktop may preserve host UID; exercise the root-owned case explicitly.
            self.docker('run', '--rm', '--network', 'none', '-v', volume + ':/data', '--user', '0:0', '--entrypoint', 'chown', image, '0:0', '/data/import.db')
            stat_code = "import os; s=os.stat('/data/import.db'); print(s.st_uid, oct(s.st_mode & 0o777))"
            before = self.docker('run', '--rm', '--network', 'none', '-v', volume + ':/data', '--entrypoint', 'python3', image, '-c', stat_code)
            self.assertEqual(before.stdout.strip(), '0 0o600')
            refused = self.docker('run', '--rm', '--network', 'none', '-v', volume + ':/data', image, 'restore', '/data/import.db', check=False)
            self.assertEqual(refused.returncode, 2)
            self.docker('run', '--rm', '--network', 'none', '-v', volume + ':/data', '--user', '0:0', '--entrypoint', 'chown', image, '10001:10001', '/data/import.db')
            after = self.docker('run', '--rm', '--network', 'none', '-v', volume + ':/data', '--entrypoint', 'python3', image, '-c', stat_code)
            self.assertEqual(after.stdout.strip(), '10001 0o600')
            self.docker('run', '--rm', '--network', 'none', '-v', volume + ':/data', image, 'restore', '/data/import.db')
            restored = self.docker('run', '--rm', '--network', 'none', '-v', volume + ':/data', '--entrypoint', 'python3', image, '-c',
                                  "import sqlite3,os; print(os.getuid(), sqlite3.connect('/data/dogbot.db').execute('SELECT id FROM members').fetchone()[0]); s=os.stat('/data/dogbot.db'); print(s.st_uid, oct(s.st_mode & 0o777))")
            self.assertEqual(restored.stdout.strip(), '10001 42\n10001 0o600')
        finally:
            self.docker('rm', '-f', container, check=False)
            self.docker('volume', 'rm', volume, check=False)

    def test_lifecycle_health_persistence_and_private_image(self):
        unique = 'dogbot-test-' + uuid.uuid4().hex[:12]
        volume, container = unique + '-data', unique
        image = os.environ.get('DOGBOT_TEST_IMAGE', 'honduitlaten:local')
        token = '123456:' + 'offline_secret_' * 3
        self.docker('volume', 'create', volume)
        try:
            meta = json.loads(self.docker('image', 'inspect', image).stdout)[0]
            self.assertEqual(meta['Config']['User'], '10001:10001')
            self.assertNotIn(token, json.dumps(meta))
            self.assertNotIn(token, self.docker('history', '--no-trunc', image).stdout)
            files = self.docker('run', '--rm', '--network', 'none', '--entrypoint', 'python3', image,
                                '-c', "import os; print(os.listdir('/app')); print(os.getuid())").stdout
            self.assertNotIn('.env', files)
            self.assertIn('10001', files)
            for boot in (1, 2):
                self.docker('run', '-d', '--name', container, '--network', 'none', '--read-only',
                            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                            '-v', volume + ':/data', '-e', 'DOGS_TELEGRAM_BOT_TOKEN=' + token,
                            '-e', 'OWNER_ID=99', '--entrypoint', 'python3', image, '-c', FAKE_RUNTIME)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    result = self.docker('exec', container, 'python3', '/app/dogbotctl.py', 'healthcheck', check=False)
                    if result.returncode == 0:
                        break
                    time.sleep(0.25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                state = self.docker('exec', container, 'python3', '-c',
                                    "import sqlite3; print(sqlite3.connect('/data/dogbot.db').execute(\"SELECT v FROM kv WHERE k='container_test_boots'\").fetchone()[0])").stdout
                self.assertEqual(state.strip(), str(boot))
                self.docker('exec', container, 'python3', '/app/dogbotctl.py', 'backup', '/data/backup' + str(boot) + '.db')
                refusal = self.docker('exec', container, 'python3', '/app/dogbotctl.py', 'restore', '/data/backup1.db', check=False)
                self.assertEqual(refusal.returncode, 2)
                self.assertNotIn(token, self.docker('logs', container).stdout)
                self.docker('stop', '-t', '10', container)
                inspection = json.loads(self.docker('inspect', container).stdout)[0]
                self.assertEqual(inspection['State']['ExitCode'], 0)
                self.docker('rm', container)
            stopped = self.docker('run', '--rm', '--network', 'none', '-v', volume + ':/data', image, 'healthcheck', check=False)
            self.assertEqual(stopped.returncode, 1)
            self.docker('run', '--rm', '--network', 'none', '-v', volume + ':/data', image, 'restore', '/data/backup1.db')
            state = self.docker('run', '--rm', '--network', 'none', '-v', volume + ':/data', '--entrypoint', 'python3', image,
                               '-c', "import sqlite3; print(sqlite3.connect('/data/dogbot.db').execute(\"SELECT v FROM kv WHERE k='container_test_boots'\").fetchone()[0])").stdout
            self.assertEqual(state.strip(), '1')
        finally:
            self.docker('rm', '-f', container, check=False)
            self.docker('volume', 'rm', volume, check=False)


if __name__ == '__main__':
    unittest.main()
