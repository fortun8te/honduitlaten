"""Stable read-only forecasts, rotation ownership, and settled swap regressions."""
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import dogbot as b


class RotaStability(unittest.TestCase):
    def setUp(self):
        self.db = b.connect(':memory:'); self.addCleanup(self.db.close)
        self.clock = datetime(2026, 10, 23, 21, 50, tzinfo=b.TZ)
        self.day = self.clock.date()
        self.sent, self.edits = [], []
        joined = int(self.clock.replace(hour=9).timestamp())
        for uid, role in [(1, 'walker'), (2, 'walker'), (3, 'parent')]:
            self.db.execute('INSERT INTO members(id,name,role,joined) VALUES(?,?,?,?)', (uid, str(uid), role, joined + uid))
        self.db.commit()
        for key, value in [('now', lambda: self.clock), ('send', self.send), ('edit', self.edit), ('api', lambda *a, **k: True)]:
            p = patch.object(b, key, value); p.start(); self.addCleanup(p.stop)

    def send(self, uid, text, markup=None, **kw):
        self.sent.append((uid, text)); return len(self.sent) + 100

    def edit(self, uid, msg, text, markup=None, **kw):
        self.edits.append((uid, msg, text)); return True

    def tap(self, uid, data, msg=10):
        b.on_button(self.db, {'id': 'q', 'from': {'id': uid}, 'data': data,
                             'message': {'message_id': msg, 'chat': {'id': uid, 'type': 'private'}}})

    def live(self):
        self.db.execute("INSERT INTO nights(day,chore,walker,status,msg,rotation_walker) VALUES(?,'dogs',1,'on',10,1)", (str(self.day),))
        self.db.commit()

    def test_offline_first_evening_does_not_shift_tomorrows_plan(self):
        forecast = dict(b.week(self.db, self.day, n=31))
        self.assertEqual(forecast[self.day + timedelta(days=1)], 2)
        self.clock = self.clock.replace(hour=9) + timedelta(days=1)
        b.tick(self.db, self.clock)
        current = dict(b.week(self.db, self.clock.date(), n=30))
        self.assertEqual(current, {day: uid for day, uid in forecast.items() if day >= self.clock.date()})

    def test_several_missing_days_preserve_rotation_with_off_and_override(self):
        b.apply_off(self.db, 1, [self.day + timedelta(days=2)])
        b.apply_claim(self.db, 2, [self.day + timedelta(days=4)])
        forecast = dict(b.week(self.db, self.day, n=31))
        later = self.day + timedelta(days=8)
        self.assertEqual(dict(b.week(self.db, later, n=23)), {d: uid for d, uid in forecast.items() if d >= later})

    def test_parent_takeover_and_completion_do_not_reassign_next_month(self):
        self.live()
        before = b.week(self.db, self.day, n=31)[1:]
        self.tap(3, f'pcover:dogs:{self.day}', 30)
        self.assertEqual(b.night(self.db, self.day)['rotation_walker'], 1)
        self.assertEqual(b.week(self.db, self.day, n=31)[1:], before)
        self.tap(3, f'pdone:dogs:{self.day}', 30)
        self.assertEqual(b.week(self.db, self.day, n=31)[1:], before)
        self.assertEqual(b.week(self.db, self.day + timedelta(days=1), n=30), before)
        self.assertEqual(next(r['points'] for r in b.monthly_points(self.db, self.day) if r['id'] == 3), 1)

    def test_walker_cover_counts_as_the_covering_walkers_turn(self):
        self.live()
        self.tap(1, 'cant:dogs')
        self.assertEqual(b.night(self.db, self.day)['walker'], 2)
        self.assertEqual(b.week(self.db, self.day, n=2)[1][1], 1)

    def test_accepting_swap_after_done_changes_nothing(self):
        self.live()
        b.pending(self.db, 2, 50, {'type': 'swap', 'from': 1, 'to': 2, 'back': None, 'owners': {str(self.day): 1}})
        self.tap(1, 'done:dogs')
        self.assertFalse(b.swap_valid(self.db, b.peek_pending(self.db, 2, 50), self.clock))
        before = b.week(self.db, self.day, n=31)
        self.tap(2, 'accept', 50)
        self.assertEqual(b.week(self.db, self.day, n=31), before)
        self.assertIsNone(self.db.execute('SELECT * FROM overrides').fetchone())
        self.assertEqual(self.edits[-1][2], b.tr('en', 'old'))

    def test_browsing_and_forecasting_never_write_a_plan(self):
        snapshot = list(self.db.iterdump())
        for page in range(5): b.week_view(self.db, self.day, page=page, uid=1)
        for offset in range(31): b.owner(self.db, self.day + timedelta(days=offset), self.day)
        self.assertEqual(list(self.db.iterdump()), snapshot)

    def test_schema_migrates_original_walker_once_and_preserves_parent_anchor(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as folder:
            path = folder + '/old.db'
            old = sqlite3.connect(path)
            old.executescript("CREATE TABLE nights(day TEXT PRIMARY KEY, walker INTEGER, status TEXT, cant TEXT DEFAULT '', msg INTEGER, done_at TEXT); INSERT INTO nights VALUES('2026-10-23',1,'on','',10,NULL);")
            old.close()
            migrated = b.connect(path)
            self.assertEqual(b.night(migrated, self.day)['rotation_walker'], 1)
            self.assertIn('done_ts', b.night(migrated, self.day).keys())
            b.set_night(migrated, str(self.day), 'dogs', walker=None, status='parent', cover_id=3)
            migrated.close()
            reopened = b.connect(path)
            try: self.assertEqual(b.night(reopened, self.day)['rotation_walker'], 1)
            finally: reopened.close()


if __name__ == '__main__': unittest.main()
