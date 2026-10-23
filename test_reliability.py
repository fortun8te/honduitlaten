"""Offline regressions for state transitions, network failures, and ownership."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import dogbot as b


class Reliability(unittest.TestCase):
    def setUp(self):
        self.db = b.connect(':memory:')
        self.addCleanup(self.db.close)
        self.clock = datetime(2026, 10, 23, 20, 0, tzinfo=b.TZ)
        self.day = self.clock.date()
        self.sent = []
        self.edited = []
        self._seed(self.db)
        for target, replacement in [
            ('now', lambda: self.clock), ('send', self.send),
            ('edit', self.edit), ('api', lambda *a, **k: True),
        ]:
            patcher = patch.object(b, target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _seed(self, db):
        joined = int((self.clock - timedelta(days=2)).timestamp())
        for uid, role in [(1, 'walker'), (2, 'walker'), (3, 'parent'), (4, 'parent')]:
            db.execute('INSERT INTO members(id,name,role,joined) VALUES(?,?,?,?)',
                       (uid, 'Person' + str(uid), role, joined + uid))
        db.commit()

    def send(self, chat, text, markup=None, **kwargs):
        self.sent.append((chat, text, markup))
        return 1000 + len(self.sent)

    def edit(self, chat, msg, text, markup=None, **kwargs):
        self.edited.append((chat, msg, text, markup))
        return True

    def row(self, chore='dogs', who=1, status='on', msg=100, day=None):
        self.db.execute('INSERT INTO nights(day,chore,walker,status,msg) VALUES(?,?,?,?,?)',
                        (str(day or self.day), chore, who, status, msg))
        self.db.commit()

    def tap(self, uid, data, msg=100, chat=None):
        b.on_button(self.db, {'id': 'q', 'from': {'id': uid}, 'data': data,
                             'message': {'message_id': msg,
                                         'chat': {'id': chat or uid, 'type': 'private'}}})

    def pending(self, uid, msg):
        return dict(b.all_pending(self.db)).get(f'p_{uid}_{msg}')

    def test_available_again_revives_both_unassigned_chores(self):
        for uid in (1, 2): b.apply_off(self.db, uid, [self.day])
        for chore in b.CHORES: self.row(chore, None, 'nobody', None)
        b.undo_off(self.db, 1, self.day)
        for chore in b.CHORES:
            row = b.night(self.db, self.day, chore)
            self.assertEqual((row['walker'], row['status']), (1, 'on'), chore)
        self.assertFalse(b.is_off(self.db, 1, self.day))

    def test_volunteer_revives_unassigned_dishes_and_clears_off(self):
        for uid in (1, 2): b.apply_off(self.db, uid, [self.day])
        for chore in b.CHORES: self.row(chore, None, 'nobody', None)
        b.take_empty(self.db, 1, self.day)
        self.assertFalse(b.is_off(self.db, 1, self.day))
        for chore in b.CHORES:
            row = b.night(self.db, self.day, chore)
            self.assertEqual((row['walker'], row['status']), (1, 'on'), chore)

    def test_accepted_swap_updates_reminders_that_failed_to_send(self):
        self.row('dogs', 1, msg=None)
        self.row('dishes', 2, msg=None)
        b.pending(self.db, 2, 222, {'type': 'swap', 'from': 1, 'to': 2, 'back': None,
                                  'owners': {str(self.day): 1}})
        self.tap(2, 'accept', 222)
        self.assertEqual(b.night(self.db, self.day)['walker'], 1)
        self.assertEqual(b.night(self.db, self.day, 'dishes')['walker'], 2)
        self.assertIsNotNone(self.pending(2, 222).get('impact'))
        self.tap(2, 'accept', 222)
        self.assertEqual(b.night(self.db, self.day)['walker'], 2)
        self.assertEqual(b.night(self.db, self.day, 'dishes')['walker'], 1)
        self.assertIsNone(self.pending(2, 222))

    def test_unsent_chore_is_not_passed_to_an_unavailable_walker(self):
        b.apply_off(self.db, 2, [self.day])
        for chore in b.CHORES: self.row(chore, 1, msg=None)
        b.confirm_off(self.db, 1, [self.day])
        for chore in b.CHORES:
            row = b.night(self.db, self.day, chore)
            self.assertEqual((row['walker'], row['status']), (None, 'nobody'), chore)

    def test_failed_next_question_does_not_consume_visible_question(self):
        days = [str(self.day + timedelta(days=i)) for i in (1, 2)]
        original = {'type': 'ask', 'target': 1, 'off': [], 'walk': [], 'days': days}
        b.pending(self.db, 1, 100, original)
        with patch.object(b, 'edit', return_value=None):
            self.tap(1, 'off')
        self.assertEqual(self.pending(1, 100), original)
        self.tap(1, 'off')
        self.assertEqual(self.pending(1, 100)['off'], days[:1])
        self.assertEqual(self.pending(1, 100)['walk'], [])

    def test_failed_final_preview_keeps_last_question(self):
        days = [str(self.day + timedelta(days=1))]
        original = {'type': 'ask', 'target': 1, 'off': [], 'walk': [], 'days': days}
        b.pending(self.db, 1, 100, original)
        with patch.object(b, 'edit', return_value=None): self.tap(1, 'walk')
        self.assertEqual(self.pending(1, 100), original)
        self.tap(1, 'walk')
        self.assertEqual(self.pending(1, 100)['type'], 'preview')
        self.assertEqual(self.pending(1, 100)['walk'], days)

    def test_stale_nobody_notification_is_not_delivered_after_assignment(self):
        self.row(who=None, status='nobody', msg=None)
        with patch.object(b, 'send', return_value=None):
            b.parent_help(self.db, self.day, 'dogs', 'nobody_parents')
        b.set_night(self.db, str(self.day), 'dogs', walker=1, status='on')
        self.db.execute('UPDATE outbox SET next_try=0'); self.db.commit()
        b.drain_outbox(self.db)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox WHERE state='pending'").fetchone()[0], 0)

    def test_restart_after_cutoff_reports_unknown_previous_night_once(self):
        for chore in b.CHORES: self.row(chore)
        self.clock += timedelta(hours=13)  # next morning, after completion window
        b.tick(self.db, self.clock)
        notices = [(uid, text) for uid, text, _ in self.sent if uid in (3, 4)]
        self.assertTrue(notices, 'Parents need to know last night remained unconfirmed during the outage')
        for chore in b.CHORES: self.assertNotEqual(b.night(self.db, self.day, chore)['status'], 'done')
        self.sent.clear()
        b.tick(self.db, self.clock)
        self.assertFalse([x for x in self.sent if x[0] in (3, 4)], 'Catch-up must not spam each tick')

    def test_unknown_callback_never_completes_a_chore(self):
        self.row()
        self.tap(1, 'something-new:dogs')
        self.assertEqual(b.night(self.db, self.day)['status'], 'on')

    def test_dated_done_requires_current_assignment_and_private_owner(self):
        self.row()
        for uid, chat in [(2, 2), (3, 3), (99, 99), (1, 2)]:
            self.tap(uid, f'done:dogs:{self.day}', msg=999, chat=chat)
            self.assertEqual(b.night(self.db, self.day)['status'], 'on')
        self.tap(1, f'done:dogs:{self.day}', msg=999)
        self.assertEqual(b.night(self.db, self.day)['status'], 'done')

    def test_done_after_midnight_uses_original_date_and_expires_at_three(self):
        self.row()
        self.clock = b.at(self.day + timedelta(days=1), 1)
        self.tap(1, 'done:dogs')
        self.assertEqual(b.night(self.db, self.day)['status'], 'done')
        self.row('dishes', 1, msg=101)
        self.clock = b.at(self.day + timedelta(days=1), b.DONE_UNTIL)
        self.tap(1, 'done:dishes', msg=101)
        self.assertEqual(b.night(self.db, self.day, 'dishes')['status'], 'on')

    def test_parent_takeover_requires_separate_completion_by_same_parent(self):
        self.row()
        self.tap(3, f'pcover:dogs:{self.day}', msg=300)
        row = b.night(self.db, self.day)
        self.assertEqual(row['status'], 'parent')
        self.assertIsNone(row['done_at'])
        for uid in (1, 4):
            self.tap(uid, f'pdone:dogs:{self.day}', msg=300)
            self.assertEqual(b.night(self.db, self.day)['status'], 'parent')
        self.tap(3, f'pdone:dogs:{self.day}', msg=300)
        self.assertEqual(b.night(self.db, self.day)['status'], 'done')

    def test_failed_handler_retains_offset_until_success(self):
        b.kv(self.db, 'offset', '50')
        update = {'update_id': 50, 'message': {'from': {'id': 1}, 'chat': {'type': 'private'}, 'text': '/today'}}
        with patch.object(b, 'api', return_value=[update]), patch.object(b.time, 'sleep'), \
             patch.object(b, 'on_text', side_effect=RuntimeError('temporary failure')):
            self.assertIsNone(b.poll(self.db, 0))
        self.assertEqual(b.kv(self.db, 'offset'), '50')
        with patch.object(b, 'api', return_value=[update]), patch.object(b, 'on_text') as handler:
            self.assertEqual(b.poll(self.db, 0), 1)
            handler.assert_called_once()
        self.assertEqual(b.kv(self.db, 'offset'), '51')

    def test_pending_parent_notice_survives_database_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'state.db')
            db = b.connect(path)
            try:
                with patch.object(b, 'send', return_value=None):
                    b.queue_notice(db, 3, 'Persisted alert', event='restart-test')
            finally: db.close()
            db = b.connect(path)
            try:
                db.execute('UPDATE outbox SET next_try=0'); db.commit()
                b.drain_outbox(db)
                self.assertEqual(self.sent, [(3, 'Persisted alert', None)])
                b.drain_outbox(db)
                self.assertEqual(len(self.sent), 1)
                self.assertEqual(db.execute('SELECT state FROM outbox').fetchone()[0], 'sent')
            finally: db.close()


if __name__ == '__main__':
    unittest.main()
