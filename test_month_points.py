"""Offline month-planning and completion-credit acceptance tests."""
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

import dogbot as b


class MonthAndPoints(unittest.TestCase):
    def setUp(self):
        self.db = b.connect(':memory:')
        self.addCleanup(self.db.close)
        self.day = date(2026, 10, 23)
        self.clock = datetime(2026, 10, 23, 20, tzinfo=b.TZ)
        self.sent, self.edits = [], []
        for uid, name, role, joined in [(2, 'Second', 'walker', 20), (1, 'First', 'walker', 10),
                                         (3, 'Parent', 'parent', 30), (4, 'Other parent', 'parent', 40)]:
            self.db.execute('INSERT INTO members(id,name,role,joined) VALUES(?,?,?,?)', (uid, name, role, joined))
        self.db.commit()
        for key, replacement in [('now', lambda: self.clock), ('send', self.send),
                                 ('edit', self.edit), ('api', lambda *a, **k: True)]:
            p = patch.object(b, key, replacement); p.start(); self.addCleanup(p.stop)

    def send(self, chat, text, markup=None, **kwargs):
        self.sent.append((chat, text, markup))
        return 100 + len(self.sent)

    def edit(self, chat, msg, text, markup=None, **kwargs):
        self.edits.append((chat, msg, text, markup))
        return True

    def row(self, day=None, chore='dogs', walker=1, status='done', cover=None, msg=10):
        self.db.execute('INSERT INTO nights(day,chore,walker,status,cover_id,msg,done_at) VALUES(?,?,?,?,?,?,?)',
                        (str(day or self.day), chore, walker, status, cover, msg, '22:00' if status == 'done' else None))
        self.db.commit()

    def tap(self, uid, data, msg=10):
        b.on_button(self.db, {'id': 'q', 'from': {'id': uid}, 'data': data,
                             'message': {'message_id': msg, 'chat': {'id': uid, 'type': 'private'}}})

    def text(self, text):
        b.on_text(self.db, {'from': {'id': 1}, 'chat': {'type': 'private'}, 'text': text})

    def scores(self, day=None, db=None):
        return {r['id']: r['points'] for r in b.monthly_points(db or self.db, day or self.day)}

    def test_five_pages_cover_exactly_today_through_thirty_days(self):
        self.assertEqual(b.AHEAD, 31)
        self.assertEqual(b.MAX_PAGE, 4)
        all_days = []
        for page in range(5):
            with self.subTest(page=page):
                _, kb = b.week_view(self.db, self.day, page=page, uid=1)
                self.assertTrue(all(kb['inline_keyboard']), 'Empty button rows are invalid')
                callbacks = [button['callback_data'] for row in kb['inline_keyboard'] for button in row]
                day_buttons = [cb for cb in callbacks if cb.startswith('wk:')]
                self.assertEqual(len(day_buttons), 3 if page == 4 else 7)
                all_days.extend(date.fromisoformat(cb.split(':')[1]) for cb in day_buttons)
                nav = [cb for cb in callbacks if cb.startswith('wp:')]
                expected = ([f'wp:{page - 1}'] if page else []) + ([f'wp:{page + 1}'] if page < 4 else [])
                self.assertEqual(nav, expected)
                self.assertTrue(all(len(cb.encode()) <= 64 for cb in callbacks))
        self.assertEqual(all_days, [self.day + timedelta(days=i) for i in range(31)])

    def test_navigation_clamps_to_real_first_and_last_pages(self):
        self.tap(1, 'wp:999')
        self.assertEqual(self.edits[-1][2], b.week_view(self.db, self.day, page=4, uid=1)[0])
        self.tap(1, 'wp:-99')
        self.assertEqual(self.edits[-1][2], b.week_view(self.db, self.day, page=0, uid=1)[0])

    def test_fifteen_days_ahead_now_has_a_real_confirmation(self):
        self.text('not 7 nov')
        pending = b.all_pending(self.db)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0][1]['selected'], ['2026-11-07'])
        self.assertFalse(b.is_off(self.db, 1, date(2026, 11, 7)))
        self.tap(1, 'av:confirm', 101)
        self.assertTrue(b.is_off(self.db, 1, date(2026, 11, 7)))

    def test_last_day_allowed_but_next_day_callback_rejected(self):
        allowed, denied = self.day + timedelta(days=30), self.day + timedelta(days=31)
        self.tap(1, f'noff:{allowed}:4')
        self.assertFalse(b.is_off(self.db, 1, allowed))
        self.tap(1, 'av:confirm', 100 + len(self.sent))
        self.assertTrue(b.is_off(self.db, 1, allowed))
        self.tap(1, f'noff:{denied}:4')
        self.assertFalse(b.is_off(self.db, 1, denied))

    def test_whole_range_rejected_if_it_crosses_month_horizon(self):
        self.text('away 20-24 nov')
        self.assertEqual(self.sent[-1][1], b.tr('en', 'too_far'))
        self.assertEqual(b.all_pending(self.db), [])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM off').fetchone()[0], 0)

    def test_zero_score_walkers_stay_visible_in_join_order(self):
        rows = b.monthly_points(self.db, self.day)
        self.assertEqual([(r['id'], r['name'], r['role'], r['points']) for r in rows],
                         [(1, 'First', 'walker', 0), (2, 'Second', 'walker', 0)])

    def test_each_done_chore_awards_one_point_to_actual_completer(self):
        self.row()
        self.row(chore='dishes')
        self.row(day=self.day + timedelta(days=1), walker=2)
        self.row(day=self.day + timedelta(days=1), chore='dishes', walker=None, cover=3)
        self.assertEqual(self.scores(), {1: 2, 2: 1, 3: 1})
        self.assertEqual([r['id'] for r in b.monthly_points(self.db, self.day)], [1, 2, 3])

    def test_uncompleted_work_and_parent_claims_earn_no_points(self):
        for i, status in enumerate(('on', 'nobody', 'missed', 'parent')):
            self.row(day=self.day + timedelta(days=i), walker=1 if status == 'on' else None,
                     status=status, cover=3 if status == 'parent' else None)
        self.assertEqual(self.scores(), {1: 0, 2: 0})

    def test_duplicate_done_callback_does_not_duplicate_points(self):
        self.row(status='on')
        self.tap(1, 'done:dogs')
        self.tap(1, 'done:dogs')
        self.tap(1, f'done:dogs:{self.day}', msg=999)
        self.assertEqual(self.scores(), {1: 1, 2: 0})
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM nights').fetchone()[0], 1)

    def test_parent_points_only_after_own_completion(self):
        self.row(status='on')
        self.tap(3, f'pcover:dogs:{self.day}', msg=30)
        self.assertEqual(self.scores(), {1: 0, 2: 0})
        self.tap(4, f'pdone:dogs:{self.day}', msg=40)
        self.assertEqual(self.scores(), {1: 0, 2: 0})
        self.tap(3, f'pdone:dogs:{self.day}', msg=30)
        self.tap(3, f'pdone:dogs:{self.day}', msg=30)
        self.assertEqual(self.scores(), {1: 0, 2: 0, 3: 1})

    def test_after_midnight_counts_toward_chore_month_not_click_month(self):
        october = date(2026, 10, 31)
        self.row(day=october, status='on')
        self.clock = datetime(2026, 11, 1, 1, tzinfo=b.TZ)
        self.tap(1, 'done:dogs')
        self.assertEqual(self.scores(october), {1: 1, 2: 0})
        self.assertEqual(self.scores(self.clock.date()), {1: 0, 2: 0})

    def test_month_filter_excludes_adjacent_months_and_other_years(self):
        for day in (date(2026, 9, 30), date(2026, 11, 1), date(2025, 10, 23)):
            self.row(day=day)
        self.row(day=date(2026, 10, 1), walker=2)
        self.assertEqual(self.scores(), {1: 0, 2: 1})

    def test_points_survive_backup_and_database_reopen(self):
        self.row()
        self.row(chore='dishes', walker=None, cover=3)
        expected = b.monthly_points(self.db, self.day)
        with tempfile.TemporaryDirectory() as folder:
            path = folder + '/backup.db'
            dest = b.connect(path)
            self.db.backup(dest); dest.close()
            restored = b.connect(path)
            try: self.assertEqual(b.monthly_points(restored, self.day), expected)
            finally: restored.close()


if __name__ == '__main__':
    unittest.main()
