"""The requested small everyday UI, with the existing capabilities still reachable."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
import dogbot as b


def actions(markup):
    return [button['callback_data'] for row in markup['inline_keyboard'] for button in row]


class MinimalEverydayUI(unittest.TestCase):
    def setUp(self):
        self.db = b.connect(':memory:')
        self.addCleanup(self.db.close)
        self.clock = datetime(2026, 10, 23, 17, tzinfo=b.TZ)
        self.day = self.clock.date()
        for uid, name, role in ((1, 'Michael', 'walker'), (2, 'Christian', 'walker'), (3, 'Parent', 'parent')):
            self.db.execute('INSERT INTO members(id,name,role,joined) VALUES(?,?,?,?)',
                            (uid, name, role, int(self.clock.timestamp()) - 3600 + uid))
        self.db.commit()
        for key, value in (('now', lambda: self.clock), ('send', lambda *a, **k: 101),
                           ('edit', lambda *a, **k: True), ('api', lambda *a, **k: True), ('OWNER_ID', 1)):
            p = patch.object(b, key, value); p.start(); self.addCleanup(p.stop)

    def test_normal_today_is_two_chores_one_action_and_two_destinations(self):
        before = self.db.total_changes
        text, kb = b.home_view(self.db, 1)
        self.assertEqual(len([line for line in text.splitlines() if line.strip()]), 3)
        self.assertIn('Christian', text)
        self.assertIn('you', text)
        self.assertIn('18:30', text)
        self.assertIn('21:45', text)
        self.assertEqual(actions(kb), [f'done:dogs:{self.day}', 'plan', 'more'])
        self.assertNotIn('points', text.lower())
        self.assertEqual(self.db.total_changes, before)

    def test_week_and_day_do_not_repeat_global_navigation(self):
        text, kb = b.week_view(self.db, self.day, uid=1)
        self.assertEqual(len([line for line in text.splitlines() if line.strip()]), 8)
        self.assertEqual(len(actions(kb)), 10)
        self.assertIn('home', actions(kb))
        self.assertNotIn('points', actions(kb))
        self.assertNotIn('requests', actions(kb))
        text, kb = b.night_view(self.db, 1, self.day + timedelta(days=1), 0)
        self.assertEqual(len([line for line in text.splitlines() if line.strip()]), 3)
        self.assertEqual(len(actions(kb)), 3)
        self.assertEqual(actions(kb)[-1], 'wp:0')

    def test_points_still_show_actual_credit_under_more(self):
        self.db.execute("INSERT INTO nights(day,chore,walker,status,done_at) VALUES(?,'dogs',1,'done','17:00')", (str(self.day),))
        self.db.commit()
        self.assertIn('points', actions(b.more_view(self.db, 1)[1]))
        text, kb = b.points_view(self.db, 1)
        self.assertIn('you: 1', text)
        self.assertEqual(len(actions(kb)), 3)
        self.assertIn('more', actions(kb))
        self.assertIn('history', actions(kb))

    def test_urgent_actions_and_setup_do_not_disappear(self):
        b.ask(self.db, 1, 1, [self.day + timedelta(days=1)])
        self.assertIn('requests', actions(b.home_view(self.db, 2)[1]))
        self.db.execute('DELETE FROM members WHERE id=2'); self.db.commit()
        self.assertIn('family', actions(b.home_view(self.db, 1)[1]))

    def test_private_review_keeps_impacts_and_confirmation(self):
        dates = [self.day + timedelta(days=1), self.day + timedelta(days=2)]
        msg = b.open_availability(self.db, 1, dates, review=True)
        proposal = b.peek_pending(self.db, 1, msg)
        text, kb = b.av_view(self.db, 1, proposal)
        self.assertLessEqual(len([line for line in text.splitlines() if line.strip()]), 6)
        self.assertIn('28', text)
        self.assertIn('Christian', text)
        self.assertIn('→', text)
        self.assertIn('av:confirm', actions(kb))
        self.assertIn('av:cancel', actions(kb))
        self.assertIn('av:details:0', actions(kb))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM off').fetchone()[0], 0)


if __name__ == '__main__': unittest.main()
