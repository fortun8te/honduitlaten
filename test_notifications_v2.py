import unittest
from datetime import timedelta
import dogbot as b
from test_dogbot import Base, T


class CorrectedNotifications(Base):
    def test_queued_done_cannot_arrive_after_its_undo(self):
        self.night(T, 1, 'on', 7)
        sender = b.send
        b.send = lambda *args, **kwargs: None
        self.tap(1, 'done:dogs', 7)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox WHERE state='pending'").fetchone()[0], 1)
        b.send = sender
        self.tap(1, f'correction:{T}:dogs:undo', 7)
        preview = 100 + len(self.sent)
        self.tap(1, 'correct_confirm', preview)
        self.db.execute('UPDATE outbox SET next_try=0'); self.db.commit()
        b.drain_outbox(self.db)
        parent_messages = [text for uid, text in self.sent if uid == 3]
        self.assertTrue(any('withdrawn' in text for text in parent_messages))
        self.assertFalse(any('dogs are out' in text for text in parent_messages))
        self.assertEqual(b.night(self.db, T)['status'], 'on')

    def test_completion_notice_can_recover_after_daily_done_deadline(self):
        self.night(T, 1, 'on', 7)
        sender = b.send
        b.send = lambda *args, **kwargs: None
        self.tap(1, 'done:dogs', 7)
        b.now = lambda: self.at(T + timedelta(days=1), 8)
        b.send = sender
        self.db.execute('UPDATE outbox SET next_try=0'); self.db.commit()
        b.drain_outbox(self.db)
        self.assertTrue(any(uid == 3 and 'dogs are out' in text for uid, text in self.sent))

    def test_outage_history_keeps_expected_actor_for_private_correction(self):
        self.db.execute('UPDATE members SET joined=joined-86400'); self.db.commit()
        b.now = lambda: self.at(T, 8)
        yesterday = T - timedelta(days=1)
        expected = b.pick(self.db, yesterday)
        b.missed_yesterday(self.db, b.now())
        n = b.night(self.db, yesterday)
        self.assertEqual(n['walker'], expected)
        self.assertEqual(n['status'], 'missed')
        self.assertIsNotNone(b.correction_allowed(self.db, expected, yesterday, 'dogs', 'done'))


if __name__ == '__main__': unittest.main()
