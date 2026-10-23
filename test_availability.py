"""Private multi-date planning remains a draft until an explicit, current confirmation."""
import json
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch
import dogbot as b

TODAY = date(2026, 10, 23)
TIME = datetime(2026, 10, 23, 18, 0, tzinfo=b.TZ)


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.db = b.connect(':memory:')
        self.addCleanup(self.db.close)
        for uid, role in ((1, 'walker'), (2, 'walker'), (3, 'parent')):
            self.db.execute('INSERT INTO members(id,name,role,joined,lang) VALUES(?,?,?,?,?)', (uid, str(uid), role, uid, 'nl'))
        self.db.commit()
        for key, value in [('now', TIME), ('send', 100), ('edit', True)]:
            mocked = patch.object(b, key, return_value=value)
            setattr(self, key, mocked.start())
            self.addCleanup(mocked.stop)
        self.answer = Mock()

    def tap(self, arg, uid=1, chat=1):
        return b.handle_availability_button(self.db, uid, arg, chat, 100, self.answer)

    def proposal(self):
        return b.peek_pending(self.db, 1, 100)

    def real_state(self):
        return {table: [tuple(r) for r in self.db.execute('SELECT * FROM ' + table)]
                for table in ('off', 'nights', 'overrides', 'outbox')}

    def select_review(self, days):
        b.open_availability(self.db, 1)
        for day in days: self.tap('toggle:' + str(day))
        self.tap('review')

    def test_selection_review_and_cancel_never_change_rota_or_notify_family(self):
        original = self.real_state()
        self.select_review([TODAY, TODAY + timedelta(days=3)])
        self.assertEqual(self.real_state(), original)
        self.assertEqual(self.proposal()['stage'], 'review')
        self.assertEqual([call.args[0] for call in self.send.call_args_list], [1])
        self.tap('cancel')
        self.assertIsNone(self.proposal())
        self.assertEqual(self.real_state(), original)

    def test_compact_calendar_has_full_horizon_and_current_off_marker(self):
        self.db.execute('INSERT INTO off VALUES(?,?)', (1, str(TODAY)))
        self.db.commit()
        b.open_availability(self.db, 1)
        markup = self.send.call_args.args[2]
        buttons = [item for row in markup['inline_keyboard'] for item in row]
        days = [item for item in buttons if item['callback_data'].startswith('av:toggle:')]
        self.assertEqual(len(days), 31)
        self.assertLess(len(buttons), 50)
        self.assertIn('🚫', days[0]['text'])
        self.assertEqual(days[-1]['callback_data'], 'av:toggle:' + str(TODAY + timedelta(days=30)))
        self.assertEqual(self.proposal()['days'], [str(TODAY)])
        self.assertEqual(self.proposal()['expires'], TIME.timestamp() + 3600)

    def test_confirm_required_and_multiday_off_applies_once(self):
        selected = [TODAY + timedelta(days=1), TODAY + timedelta(days=5)]
        b.open_availability(self.db, 1)
        self.tap('toggle:' + str(selected[0]))
        self.tap('confirm')
        self.assertEqual(self.db.execute('SELECT count(*) FROM off').fetchone()[0], 0)
        self.tap('toggle:' + str(selected[1]))
        self.tap('review')
        self.tap('confirm')
        self.assertEqual([r[0] for r in self.db.execute('SELECT day FROM off ORDER BY day')], list(map(str, selected)))
        self.assertIsNone(self.proposal())
        with patch.object(b, 'confirm_off') as apply:
            self.tap('confirm')
            apply.assert_not_called()

    def test_mode_on_restores_multiple_dates(self):
        days = [TODAY + timedelta(days=1), TODAY + timedelta(days=2)]
        b.apply_off(self.db, 1, days)
        self.select_review(days)
        self.tap('back')
        self.tap('mode:on')
        self.tap('review')
        self.assertTrue(all(b.is_off(self.db, 1, d) for d in days))
        self.tap('confirm')
        self.assertFalse(any(b.is_off(self.db, 1, d) for d in days))

    def test_failed_send_or_edit_preserves_previous_step(self):
        self.send.return_value = None
        self.assertIsNone(b.open_availability(self.db, 1))
        self.assertIsNone(self.proposal())
        self.send.return_value = 100
        b.open_availability(self.db, 1)
        original = self.proposal()
        self.edit.return_value = None
        self.tap('toggle:' + str(TODAY))
        self.assertEqual(self.proposal(), original)
        self.tap('cancel')
        self.assertEqual(self.proposal(), original)
        self.edit.return_value = True
        self.tap('toggle:' + str(TODAY))
        original = self.proposal()
        self.edit.return_value = None
        self.tap('review')
        self.assertEqual(self.proposal(), original)
        self.tap('confirm')
        self.assertFalse(b.is_off(self.db, 1, TODAY))

    def test_successful_confirm_survives_failed_ack_and_only_retries_initiator(self):
        day = TODAY + timedelta(days=1)
        self.select_review([day])
        self.edit.return_value = None
        self.send.return_value = None
        self.tap('confirm')
        self.assertTrue(b.is_off(self.db, 1, day))
        self.assertIsNone(self.proposal())
        rows = self.db.execute('SELECT recipient,state,payload FROM outbox').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(tuple(rows[0])[:2], (1, 'pending'))
        self.assertIn('Opgeslagen', json.loads(rows[0]['payload'])['text'])

    def test_membership_availability_and_assignment_changes_stale_review(self):
        day = TODAY + timedelta(days=1)
        changes = ["UPDATE members SET role='parent' WHERE id=2",
                   "INSERT INTO off VALUES(2,'2026-10-24')",
                   "INSERT INTO overrides(day,chore,walker) VALUES('2026-10-24','dogs',2)",
                   "INSERT INTO nights(day,chore,walker,status) VALUES('2026-10-24','dogs',2,'on')"]
        for sql in changes:
            self.select_review([day])
            self.db.execute(sql); self.db.commit()
            self.tap('confirm')
            self.assertFalse(b.is_off(self.db, 1, day))
            self.answer.assert_called_with('av_stale')
            self.assertEqual(self.proposal()['stage'], 'review')

    def test_role_private_horizon_expiry_and_cutoff_validation(self):
        b.open_availability(self.db, 1)
        for arg in ('toggle:nope', 'toggle:' + str(TODAY - timedelta(days=1)),
                    'toggle:' + str(TODAY + timedelta(days=31))):
            self.tap(arg)
            self.assertEqual(self.proposal()['selected'], [])
        self.tap('toggle:' + str(TODAY), uid=3, chat=3)
        self.tap('toggle:' + str(TODAY), chat=999)
        self.assertEqual(self.proposal()['selected'], [])
        self.select_review([TODAY])
        self.now.return_value = TIME + timedelta(hours=2)
        self.tap('confirm')
        self.answer.assert_called_with('old')
        self.assertFalse(b.is_off(self.db, 1, TODAY))
        self.now.return_value = TIME.replace(hour=20, minute=50)
        b.open_availability(self.db, 1, [TODAY], review=True)
        self.now.return_value = TIME.replace(hour=21, minute=1)
        self.tap('confirm')
        self.answer.assert_called_with('av_stale')
        self.assertFalse(b.is_off(self.db, 1, TODAY))

    def test_invalid_selected_date_rejects_entire_confirmation(self):
        self.select_review([TODAY, TODAY + timedelta(days=1)])
        proposal = self.proposal()
        proposal['selected'].append(str(TODAY + timedelta(days=31)))
        b.pending(self.db, 1, 100, proposal)
        self.tap('confirm')
        self.assertEqual(self.db.execute('SELECT count(*) FROM off').fetchone()[0], 0)

    def test_single_date_review_explains_scope_and_cutoffs(self):
        b.open_availability(self.db, 1, days=[TODAY], mode='on', review=True)
        text = self.send.call_args.args[1]
        self.assertIn('honden en afwas', text)
        self.assertIn('21:00', text)
        self.assertIn('23:00', text)
        self.assertEqual(self.proposal()['mode'], 'on')
        self.assertEqual(self.proposal()['stage'], 'review')
        self.assertFalse(b.is_off(self.db, 1, TODAY))

    def test_sql_abort_in_middle_rolls_back_whole_batch_and_keeps_review(self):
        days = [TODAY + timedelta(days=1), TODAY + timedelta(days=2)]
        self.select_review(days)
        self.db.execute("CREATE TRIGGER fail_second BEFORE INSERT ON off WHEN NEW.day='2026-10-25' BEGIN SELECT RAISE(ABORT,'test failure'); END")
        self.db.commit()
        before = self.real_state()
        previous_edits = self.edit.call_count
        self.tap('confirm')
        self.answer.assert_called_with('error')
        self.assertEqual(self.real_state(), before)
        self.assertEqual(self.proposal()['stage'], 'review')
        self.assertEqual(self.edit.call_count, previous_edits)

    def test_outage_commits_reassignment_before_network_and_keeps_retryable_reminder(self):
        self.now.return_value = TIME.replace(hour=22)
        self.db.execute("INSERT INTO nights(day,chore,walker,status,msg,rotation_walker) VALUES(?,'dogs',1,'on',77,1)", (str(TODAY),))
        self.db.commit()
        self.select_review([TODAY, TODAY + timedelta(days=1)])
        def offline(*args, **kwargs):
            self.assertFalse(self.db.in_transaction)
            self.assertTrue(b.is_off(self.db, 1, TODAY))
            self.assertEqual(b.night(self.db, TODAY)['walker'], 2)
            return None
        self.send.side_effect = offline
        self.edit.side_effect = offline
        self.tap('confirm')
        row = b.night(self.db, TODAY)
        self.assertEqual((row['walker'], row['status'], row['msg']), (2, 'on', None))
        self.assertTrue(b.is_off(self.db, 1, TODAY + timedelta(days=1)))
        self.assertIsNone(self.proposal())
        self.answer.assert_called_with('saved')

    def test_both_off_preserves_anchor_and_durably_asks_parent_after_commit(self):
        self.now.return_value = TIME.replace(hour=22)
        b.apply_off(self.db, 2, [TODAY])
        self.db.execute("INSERT INTO nights(day,chore,walker,status,msg,rotation_walker) VALUES(?,'dogs',1,'on',77,1)", (str(TODAY),))
        self.db.commit()
        self.select_review([TODAY])
        def offline(*args, **kwargs):
            self.assertFalse(self.db.in_transaction)
            return None
        self.send.side_effect = offline
        self.tap('confirm')
        row = b.night(self.db, TODAY)
        self.assertEqual((row['walker'], row['status'], row['rotation_walker']), (None, 'nobody', 1))
        notices = self.db.execute('SELECT recipient,state FROM outbox').fetchall()
        self.assertEqual([tuple(r) for r in notices], [(3, 'pending')])

    def test_available_again_preserves_delivered_assignment_but_revives_nobody(self):
        b.apply_off(self.db, 1, [TODAY])
        self.db.execute("INSERT INTO nights(day,chore,walker,status,msg) VALUES(?,'dogs',2,'on',77)", (str(TODAY),))
        self.db.execute("INSERT INTO nights(day,chore,status) VALUES(?,'dishes','nobody')", (str(TODAY),))
        self.db.commit()
        b.open_availability(self.db, 1, [TODAY], mode='on', review=True)
        self.tap('confirm')
        dog, dish = b.night(self.db, TODAY), b.night(self.db, TODAY, 'dishes')
        self.assertEqual((dog['walker'], dog['msg']), (2, 77))
        self.assertEqual((dish['walker'], dish['status']), (1, 'on'))
        self.assertFalse(b.is_off(self.db, 1, TODAY))


if __name__ == '__main__':
    unittest.main()
