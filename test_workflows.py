"""User journeys through the actual handlers, with Telegram replaced by a fake."""
import io
import unittest
from contextlib import redirect_stderr
from datetime import date, datetime
from unittest.mock import patch
import dogbot as b
from test_dogbot import Base, T


class Workflows(Base):
    def test_points_screen_updates_without_switching_back_to_today(self):
        self.text(1, '/today')
        msg = 100 + len(self.sent)
        self.tap(1, 'points', msg)
        self.assertEqual(self.db.execute('SELECT page FROM weekmsg WHERE id=1').fetchone()[0], -3)
        self.night(T, 1, 'done')
        b.refresh_weeks(self.db)
        self.assertIn('Points', self.edits[-1][2])
        self.assertIn('you: 1', self.edits[-1][2])

    def test_parent_completion_keeps_the_person_visible(self):
        self.night(T, 1, 'on', 7)
        self.tap(3, f'pcover:dogs:{T}')
        self.tap(3, f'pdone:dogs:{T}')
        text, _ = b.home_view(self.db, 1)
        self.assertIn('Mum · ✅', text)
        week, _ = b.week_view(self.db, T, uid=1)
        self.assertIn('Mum ✓', week)

    def test_repeated_swap_tap_sends_one_request(self):
        self.tap(1, 'nswap:2026-10-16:0')
        first = list(self.sent)
        self.tap(1, 'nswap:2026-10-16:0')
        self.assertEqual(self.sent, first)
        self.assertEqual(len(b.all_pending(self.db)), 1)

    def test_finish_early_prevents_later_reminder(self):
        b.now = lambda: self.at(T, 17)
        text, kb = b.home_view(self.db, 1)
        data = [item['callback_data'] for row in kb['inline_keyboard'] for item in row]
        self.assertIn(f'done:dogs:{T}', data)
        self.tap(1, f'done:dogs:{T}')
        self.assertEqual(b.night(self.db, T)['status'], 'done')
        self.sent.clear()
        b.tick(self.db, self.at(T, 21, 45))
        self.assertFalse(any(chat == 1 and 'yours tonight' in text for chat, text in self.sent))

    def test_early_done_cannot_take_someone_elses_chore(self):
        b.now = lambda: self.at(T, 17)
        self.tap(2, f'done:dogs:{T}')
        self.assertIsNone(b.night(self.db, T))
        self.tap(1, 'done:dogs:2026-10-16')
        self.assertIsNone(b.night(self.db, date(2026, 10, 16)))

    def test_whole_range_rejected_instead_of_silently_shortened(self):
        self.text(1, 'away 20 oct - 20 nov')
        self.assertEqual(self.sent[-1][1], b.tr('en', 'too_far'))
        self.assertEqual(b.all_pending(self.db), [])

    def test_failed_next_question_keeps_visible_question(self):
        self.text(1, 'fri sat')
        msg = 100 + len(self.sent)
        before = b.peek_pending(self.db, 1, msg)
        b.edit = lambda *args, **kwargs: None
        self.tap(1, 'off', msg)
        self.assertEqual(b.peek_pending(self.db, 1, msg), before)
        b.edit = lambda *args, **kwargs: True
        self.tap(1, 'off', msg)
        self.assertEqual(b.peek_pending(self.db, 1, msg)['off'], ['2026-10-16'])

    def test_expired_confirmation_does_not_change_rota(self):
        self.text(1, 'not tonight')
        msg = 100 + len(self.sent)
        b.now = lambda: self.at(T, 23, 10)
        self.tap(1, 'confirm', msg)
        self.assertFalse(b.is_off(self.db, 1, T))

    def test_leap_date_and_dutch_short_range(self):
        self.assertEqual(b.parse_days('29 feb', date(2028, 3, 1)), [date(2032, 2, 29)])
        self.assertEqual(len(b.parse_days('weg ma-vr', T)), 5)
        self.assertEqual(b.parse_days('overmorgen', T), [date(2026, 10, 17)])

    def test_log_does_not_print_token(self):
        stream = io.StringIO()
        with patch.object(b, 'TOKEN', '1234:secret'), redirect_stderr(stream):
            b.log('failure', 'https://api.telegram.org/bot1234:secret/sendMessage')
        self.assertNotIn('1234:secret', stream.getvalue())


if __name__ == '__main__':
    unittest.main()
