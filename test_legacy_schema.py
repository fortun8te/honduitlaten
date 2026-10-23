"""Refuse incompatible buttons-only data before changing its database."""
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

import dogbot as b


class LegacySchemaGuard(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'family.db'

    def create_legacy(self, populated=True, mixed=False):
        db = sqlite3.connect(self.path)
        db.executescript('''
            CREATE TABLE members(id INTEGER PRIMARY KEY, name TEXT, role TEXT, joined INTEGER, lang TEXT DEFAULT 'nl');
            CREATE TABLE kv(k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE tasks(day TEXT, chore TEXT, who INTEGER, payback INTEGER DEFAULT 0, done_at TEXT,
                               missed INTEGER DEFAULT 0, PRIMARY KEY(day,chore));
            CREATE TABLE points(day TEXT, chore TEXT, uid INTEGER, n INTEGER);
            CREATE TABLE cards(uid INTEGER, day TEXT, msg INTEGER, pings INTEGER, PRIMARY KEY(uid,day));
            PRAGMA user_version=1;
        ''')
        if populated:
            db.executescript('''
                INSERT INTO members VALUES(1,'Michael','walker',100,'nl'),(2,'Christian','walker',101,'nl');
                INSERT INTO kv VALUES('offset','9876'),('code','saved-invite'),('since','2026-10-16');
                INSERT INTO tasks VALUES('2026-10-22','honden',2,0,'22:10',0),
                  ('2026-10-22','afwas',1,0,NULL,1),('2026-10-24','afwas',2,1,NULL,0),
                  ('2026-10-25','honden',NULL,0,NULL,0);
                INSERT INTO points VALUES('2026-10-22','honden',2,1),('2026-10-22','honden',1,-1);
                INSERT INTO cards VALUES(1,'2026-10-22',4567,2);
            ''')
        if mixed:
            db.execute("CREATE TABLE nights(day TEXT,chore TEXT,walker INTEGER,status TEXT,PRIMARY KEY(day,chore))")
        db.commit(); db.close()

    def assert_refused_without_changes(self):
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, r'button-only-rota.*Migration is required'):
            b.connect(str(self.path))
        self.assertEqual(self.path.read_bytes(), original)
        db = sqlite3.connect(self.path)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        db.close()

    def test_populated_legacy_database_is_unchanged_when_refused(self):
        self.create_legacy()
        self.assert_refused_without_changes()
        db = sqlite3.connect(self.path)
        try:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM members').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 4)
            self.assertEqual(db.execute('SELECT SUM(n) FROM points WHERE uid=1').fetchone()[0], -1)
            self.assertEqual(db.execute("SELECT v FROM kv WHERE k='offset'").fetchone()[0], '9876')
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='nights'").fetchone())
        finally: db.close()

    def test_empty_legacy_schema_is_still_not_a_current_schema(self):
        self.create_legacy(populated=False)
        self.assert_refused_without_changes()

    def test_prior_accidental_current_tables_do_not_bypass_legacy_guard(self):
        self.create_legacy(mixed=True)
        self.assert_refused_without_changes()

    def test_new_database_and_current_database_can_open(self):
        db = b.connect(str(self.path))
        db.execute("INSERT INTO members(id,name,role,joined) VALUES(1,'Michael','walker',100)")
        db.execute("INSERT INTO nights(day,chore,walker,status,done_at) VALUES('2026-10-22','dogs',1,'done','22:10')")
        db.commit(); db.close()
        db = b.connect(str(self.path))
        try:
            self.assertEqual(b.night(db, date(2026, 10, 22))['done_at'], '22:10')
            self.assertEqual(b.monthly_points(db, date(2026, 10, 23))[0]['points'], 1)
        finally: db.close()
        db = b.connect(':memory:'); db.close()

    def test_older_main_schema_still_migrates_its_history(self):
        old = sqlite3.connect(self.path)
        old.executescript('''
            CREATE TABLE nights(day TEXT PRIMARY KEY,walker INTEGER,status TEXT,cant TEXT DEFAULT '',msg INTEGER,done_at TEXT);
            INSERT INTO nights VALUES('2026-10-22',1,'done','',567,'22:10');
            CREATE TABLE overrides(day TEXT PRIMARY KEY,walker INTEGER);
            INSERT INTO overrides VALUES('2026-10-24',2);
        ''')
        old.close()
        migrated = b.connect(str(self.path))
        try:
            row = b.night(migrated, date(2026, 10, 22))
            self.assertEqual((row['chore'], row['walker'], row['status'], row['done_at'], row['rotation_walker']),
                             ('dogs', 1, 'done', '22:10', 1))
            self.assertEqual(tuple(migrated.execute('SELECT day,chore,walker FROM overrides').fetchone()),
                             ('2026-10-24', 'dogs', 2))
        finally: migrated.close()


if __name__ == '__main__': unittest.main()
