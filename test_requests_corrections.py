"""Offline acceptance checks for consensual swaps and auditable corrections."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import dogbot as b


class RequestsCorrections(unittest.TestCase):
    def setUp(self):
        self.db = b.connect(':memory:'); self.addCleanup(self.db.close)
        self.clock = datetime(2026, 11, 2, 20, tzinfo=b.TZ)
        self.day = self.clock.date()
        self.sent, self.edits = [], []
        for uid, role in ((1, 'walker'), (2, 'walker'), (3, 'parent'), (4, 'parent')):
            self.db.execute('INSERT INTO members(id,name,role,joined) VALUES(?,?,?,?)',
                            (uid, str(uid), role, int(self.clock.replace(hour=9).timestamp()) + uid))
        self.db.commit()
        for key, value in [('now', lambda: self.clock), ('send', self.send), ('edit', self.edit), ('api', lambda *a, **k: True)]:
            p = patch.object(b, key, value); p.start(); self.addCleanup(p.stop)

    def send(self, uid, text, markup=None, **kw):
        msg = len(self.sent) + 100
        self.sent.append((uid, text, markup, msg)); return msg

    def edit(self, uid, msg, text, markup=None, **kw):
        self.edits.append((uid, msg, text, markup)); return True

    def tap(self, uid, data, msg=10, chat=None):
        b.on_button(self.db, {'id': 'q', 'from': {'id': uid}, 'data': data,
                             'message': {'message_id': msg, 'chat': {'id': chat or uid, 'type': 'private'}}})

    def rows(self, table): return [tuple(r) for r in self.db.execute('SELECT * FROM ' + table)]

    def live(self, status='on', day=None, walker=1, cover=None):
        self.db.execute('INSERT INTO nights(day,chore,walker,status,msg,cover_id,rotation_walker,done_at,done_ts) VALUES(?,?,?,?,?,?,?,?,?)',
                        (str(day or self.day), 'dogs', walker, status, 10, cover, 1,
                         '19:00' if status == 'done' else None, self.clock.timestamp() - 3600 if status == 'done' else None))
        self.db.commit()

    def score(self, uid=1, day=None):
        return next((r['points'] for r in b.monthly_points(self.db, day or self.day) if r['id'] == uid), 0)

    def proposal(self, kind, uid):
        matches = [(int(k.rsplit('_', 1)[1]), p) for k, p in b.all_pending(self.db)
                   if k.startswith(f'p_{uid}_') and p.get('type') == kind]
        self.assertEqual(len(matches), 1, (kind, uid, matches))
        return matches[0][0]

    def request(self):
        self.tap(1, f'nswap:{self.day}:0')
        preview = self.proposal('request_preview', 1)
        self.tap(1, 'request_confirm', preview)
        return self.proposal('swap', 2)

    def correction(self, action='undo', uid=1, day=None):
        self.tap(uid, f'correction:{day or self.day}:dogs:{action}')
        return self.proposal('correction', uid)

    def test_request_preview_is_private_and_changes_no_assignment(self):
        self.live()
        before = self.rows('nights'), self.rows('overrides')
        self.tap(1, f'nswap:{self.day}:0')
        self.assertEqual([x[0] for x in self.sent], [1])
        self.assertEqual((self.rows('nights'), self.rows('overrides')), before)
        msg = self.proposal('request_preview', 1)
        self.tap(1, 'request_cancel', msg)
        self.assertEqual((self.rows('nights'), self.rows('overrides')), before)
        self.assertFalse([p for _, p in b.all_pending(self.db) if p['type'] == 'swap'])

    def test_only_recipient_acceptance_changes_the_plan(self):
        self.live()
        source = self.request()
        self.assertEqual(b.night(self.db, self.day)['walker'], 1)
        self.assertEqual([x[0] for x in self.sent], [1, 2])
        for uid in (1, 3, 99):
            self.tap(uid, f'swap_reply:{source}:accept', msg=77)
            self.assertEqual(b.night(self.db, self.day)['walker'], 1)
        self.tap(2, f'swap_reply:{source}:accept', msg=77)
        self.assertEqual(b.night(self.db, self.day)['walker'], 2)
        self.assertIsNone(b.peek_pending(self.db, 2, source))

    def test_requests_view_does_not_expose_other_familys_private_controls(self):
        self.live(); source = self.request()
        for uid, expected in ((1, f'withdraw:2:{source}'), (2, f'swap_reply:{source}:accept')):
            _, kb = b.requests_view(self.db, uid)
            self.assertIn(expected, [x['callback_data'] for r in kb['inline_keyboard'] for x in r])
        _, kb = b.requests_view(self.db, 3)
        self.assertFalse([x for r in kb['inline_keyboard'] for x in r if x['callback_data'].startswith(('withdraw:', 'swap_reply:'))])

    def test_withdrawal_requires_private_confirmation_then_invalidates_accept(self):
        self.live(); source = self.request()
        before = self.rows('nights'), self.rows('overrides')
        messages = len(self.sent)
        self.tap(1, f'withdraw:2:{source}')
        review = self.proposal('withdraw', 1)
        self.assertEqual([x[0] for x in self.sent[messages:]], [1])
        self.assertIsNotNone(b.peek_pending(self.db, 2, source))
        self.tap(2, 'withdraw_confirm', review)
        self.assertIsNotNone(b.peek_pending(self.db, 2, source))
        self.tap(1, 'withdraw_confirm', review)
        self.assertIsNone(b.peek_pending(self.db, 2, source))
        self.tap(2, 'accept', source)
        self.assertEqual((self.rows('nights'), self.rows('overrides')), before)

    def test_expired_and_wrong_chat_request_confirmation_are_inert(self):
        self.live(); self.tap(1, f'nswap:{self.day}:0')
        review = self.proposal('request_preview', 1)
        self.tap(1, 'request_confirm', review, chat=2)
        self.assertEqual([x[0] for x in self.sent], [1])
        self.clock += timedelta(hours=1)
        self.tap(1, 'request_confirm', review)
        self.assertEqual([x[0] for x in self.sent], [1])
        self.assertEqual(b.night(self.db, self.day)['walker'], 1)

    def test_request_confirmation_ack_failure_does_not_send_twice(self):
        self.live(); self.tap(1, f'nswap:{self.day}:0')
        review = self.proposal('request_preview', 1)
        with patch.object(b, 'edit', side_effect=RuntimeError('ack unavailable')):
            with self.assertRaises(RuntimeError): self.tap(1, 'request_confirm', review)
        self.tap(1, 'request_confirm', review)
        self.assertEqual(len([x for x in self.sent if x[0] == 2]), 1)
        self.proposal('swap', 2)

    def test_correction_preview_and_cancel_are_private_and_inert(self):
        self.live('done'); before = self.rows('nights')
        review = self.correction()
        self.assertEqual([x[0] for x in self.sent], [1])
        self.assertEqual(self.rows('nights'), before)
        self.assertEqual(self.score(), 1)
        self.assertEqual(self.rows('corrections'), [])
        self.assertEqual(self.rows('outbox'), [])
        self.tap(1, 'correct_cancel', review)
        self.assertEqual(self.rows('nights'), before)
        self.assertEqual(self.score(), 1)

    def test_history_and_correction_are_limited_to_owner_and_seven_days(self):
        for offset in (0, 6, 7): self.live('done', self.day - timedelta(days=offset))
        _, kb = b.history_view(self.db, 1)
        callbacks = [x['callback_data'] for r in kb['inline_keyboard'] for x in r if x['callback_data'].startswith('correction:')]
        self.assertEqual(len(callbacks), 2)
        for uid in (2, 3, 99):
            self.tap(uid, f'correction:{self.day}:dogs:undo')
        self.tap(1, f'correction:{self.day - timedelta(days=7)}:dogs:undo')
        self.assertEqual(self.sent, [])
        self.assertIsNotNone(b.correction_allowed(self.db, 1, self.day - timedelta(days=6), 'dogs', 'undo'))

    def test_confirm_undo_updates_points_audit_and_parent_notices_once(self):
        self.live('done'); review = self.correction()
        self.tap(1, 'correct_confirm', review)
        self.assertEqual(self.score(), 0)
        self.assertEqual(b.night(self.db, self.day)['status'], 'on')
        audits = self.rows('corrections')
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0][1:6], (str(self.day), 'dogs', 1, 'done', 'on'))
        notices = self.rows('outbox')
        self.assertEqual({r[2] for r in notices}, {3, 4})
        self.tap(1, 'correct_confirm', review)
        self.assertEqual(self.rows('corrections'), audits)
        self.assertEqual(self.rows('outbox'), notices)
        self.assertEqual(self.score(), 0)

    def test_confirmation_revalidates_snapshot_and_actor(self):
        self.live('done'); review = self.correction()
        self.tap(2, 'correct_confirm', review)
        self.assertEqual(self.score(), 1)
        b.set_night(self.db, str(self.day), 'dogs', done_at='19:01')
        self.tap(1, 'correct_confirm', review)
        self.assertEqual(self.score(), 1)
        self.assertEqual(self.rows('corrections'), [])
        self.assertEqual(self.rows('outbox'), [])

    def test_expired_correction_cannot_change_points(self):
        self.live('done'); review = self.correction()
        self.clock += timedelta(hours=1)
        self.tap(1, 'correct_confirm', review)
        self.assertEqual(self.score(), 1)
        self.assertEqual(self.rows('corrections'), [])

    def test_atomic_failure_rolls_back_status_audit_and_notices(self):
        self.live('done'); review = self.correction()
        original = b.save_notice
        calls = []
        def fail_second(*args, **kw):
            calls.append(1)
            if len(calls) == 2: raise RuntimeError('storage failed')
            return original(*args, **kw)
        with patch.object(b, 'save_notice', side_effect=fail_second):
            with self.assertRaises(RuntimeError): self.tap(1, 'correct_confirm', review)
        self.assertEqual(self.score(), 1)
        self.assertEqual(self.rows('corrections'), [])
        self.assertEqual(self.rows('outbox'), [])
        self.assertIsNotNone(b.peek_pending(self.db, 1, review))
        self.tap(1, 'correct_confirm', review)
        self.assertEqual(self.score(), 0)
        self.assertEqual(len(self.rows('corrections')), 1)

    def test_failure_after_commit_does_not_replay_correction(self):
        self.live('done'); review = self.correction()
        with patch.object(b, 'edit', side_effect=RuntimeError('ack failed')):
            with self.assertRaises(RuntimeError): self.tap(1, 'correct_confirm', review)
        self.assertEqual(self.score(), 0)
        self.assertEqual(len(self.rows('corrections')), 1)
        self.assertEqual(len(self.rows('outbox')), 2)
        self.tap(1, 'correct_confirm', review)
        self.assertEqual(len(self.rows('corrections')), 1)
        self.assertEqual(len(self.rows('outbox')), 2)

    def test_late_completion_credits_original_month_and_does_not_duplicate(self):
        original_day = self.day - timedelta(days=2)
        self.live('missed', original_day)
        review = self.correction('done', day=original_day)
        self.assertEqual(self.score(day=original_day), 0)
        self.tap(1, 'correct_confirm', review)
        self.tap(1, 'correct_confirm', review)
        self.assertEqual(self.score(day=original_day), 1)
        self.assertEqual(self.score(), 0)
        self.assertEqual(len(self.rows('corrections')), 1)

    def test_parent_correction_keeps_rotation_and_credits_actual_parent(self):
        self.live('done', walker=None, cover=3)
        before = b.week(self.db, self.day, n=31)[1:]
        review = self.correction('undo', uid=3)
        self.tap(3, 'correct_confirm', review)
        self.assertEqual(self.score(3), 0)
        self.assertEqual(b.night(self.db, self.day)['status'], 'parent')
        self.assertEqual(b.night(self.db, self.day)['rotation_walker'], 1)
        self.assertEqual(b.week(self.db, self.day, n=31)[1:], before)
        review = self.correction('done', uid=3)
        self.tap(3, 'correct_confirm', review)
        self.assertEqual(self.score(3), 1)
        self.assertEqual(self.score(1), 0)
        self.assertEqual(b.week(self.db, self.day, n=31)[1:], before)


if __name__ == '__main__': unittest.main()
