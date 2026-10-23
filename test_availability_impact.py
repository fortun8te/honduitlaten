"""Availability previews use the exact save policy without touching live planning."""
import unittest
import re
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch
import dogbot as b

TODAY = date(2026, 10, 23)
TIME = datetime(2026, 10, 23, 18, 0, tzinfo=b.TZ)


class AvailabilityImpact(unittest.TestCase):
    def setUp(self):
        self.db = b.connect(':memory:')
        self.addCleanup(self.db.close)
        for uid, who, role in ((1, 'Michael', 'walker'), (2, 'Christian', 'walker'), (3, 'Mum', 'parent')):
            self.db.execute('INSERT INTO members(id,name,role,joined,lang) VALUES(?,?,?,?,?)',
                            (uid, who, role, int(TIME.timestamp()) + uid, 'en'))
        self.db.commit()
        for name, result in (('now', TIME), ('send', 100), ('edit', True)):
            replacement = patch.object(b, name, return_value=result)
            setattr(self, name, replacement.start()); self.addCleanup(replacement.stop)

    def proposal(self, days, mode='off'):
        return {'type': 'availability', 'selected': list(map(str, days)), 'mode': mode,
                'days': [str(TODAY)], 'expires': TIME.timestamp() + 3600,
                'stage': 'review', 'snapshot': b.av_snapshot(self.db, list(map(str, days)), TIME)}

    def test_review_matches_committed_off_plan_including_knock_on_dates(self):
        selected = next(day for day, who in b.week(self.db, TODAY, n=10) if who == 1)
        proposal = self.proposal([selected])
        impact = b.av_impact(self.db, 1, proposal, TIME)
        self.assertTrue(any(not item['selected'] for item in impact))
        b.commit_availability(self.db, 1, 100, proposal, TIME)
        actual = b.av_plan(self.db, TIME)
        for item in impact: self.assertEqual(item['after'], actual[item['day']])
        selected_row = next(item for item in impact if item['selected'])
        self.assertEqual(selected_row['before']['dogs']['person'], 1)
        self.assertEqual(selected_row['after']['dogs']['person'], 2)
        text = b.av_impact_text(self.db, 1, proposal, impact, TIME)
        self.assertIn('Also changes in the rota', text)
        self.assertIn('you→Christian', text)

    def test_available_again_preview_matches_commit_and_preserves_delivered_work(self):
        b.apply_off(self.db, 1, [TODAY])
        self.db.execute("INSERT INTO nights(day,chore,walker,status,msg) VALUES(?,'dogs',2,'on',77)", (str(TODAY),))
        self.db.execute("INSERT INTO nights(day,chore,status) VALUES(?,'dishes','nobody')", (str(TODAY),))
        self.db.commit()
        proposal = self.proposal([TODAY], 'on')
        impact = b.av_impact(self.db, 1, proposal, TIME)
        text, _ = b.av_view(self.db, 1, proposal)
        self.assertIn('=Christian 📩', text)
        self.assertIn('no one→you', text)
        b.commit_availability(self.db, 1, 100, proposal, TIME)
        actual = b.av_plan(self.db, TIME)
        for item in impact: self.assertEqual(item['after'], actual[item['day']])
        self.assertEqual(b.night(self.db, TODAY)['msg'], 77)

    def test_open_source_transaction_simulates_without_commit_or_notifications(self):
        self.db.execute('INSERT INTO off VALUES(?,?)', (2, str(TODAY)))
        self.assertTrue(self.db.in_transaction)
        before = self.db.total_changes
        proposal = self.proposal([TODAY])
        with patch.object(b, 'queue_notice', side_effect=AssertionError('notification in preview')):
            impact = b.av_impact(self.db, 1, proposal, TIME)
        self.assertTrue(self.db.in_transaction)
        self.assertEqual(self.db.total_changes, before)
        self.assertFalse(b.is_off(self.db, 1, TODAY))
        self.assertIsNone(impact[0]['after']['dogs']['person'])
        self.send.assert_not_called(); self.edit.assert_not_called()
        self.db.rollback()
        self.assertFalse(b.is_off(self.db, 2, TODAY))

    def test_settled_parent_and_cutoff_assignments_are_explicitly_unchanged(self):
        self.db.execute("INSERT INTO nights(day,chore,walker,status,done_at) VALUES(?,'dishes',1,'done','19:00')", (str(TODAY),))
        self.db.execute("INSERT INTO nights(day,chore,status,cover_id) VALUES(?,'dogs','parent',3)", (str(TODAY),))
        self.db.commit()
        text, _ = b.av_view(self.db, 1, self.proposal([TODAY]))
        self.assertIn('=Mum 🙋', text)
        self.assertIn('=you ✓', text)
        self.db.execute("UPDATE nights SET status='on',walker=1,msg=77 WHERE chore='dishes'")
        self.db.commit()
        self.now.return_value = TIME.replace(hour=22)
        text, _ = b.av_view(self.db, 1, self.proposal([TODAY]))
        self.assertIn('=you ⌛', text)

    def test_cosmetic_profile_changes_do_not_stale_but_membership_and_cutoffs_do(self):
        days = [str(TODAY)]
        before = b.av_snapshot(self.db, days, TIME)
        self.db.execute("UPDATE members SET name='New name',lang='nl' WHERE id=2")
        self.db.commit()
        self.assertEqual(before, b.av_snapshot(self.db, days, TIME))
        self.assertNotEqual(before, b.av_snapshot(self.db, days, TIME.replace(hour=22)))
        self.db.execute("UPDATE members SET role='parent' WHERE id=2")
        self.db.commit()
        self.assertNotEqual(before, b.av_snapshot(self.db, days, TIME))

    def test_assignment_change_stales_review_even_if_people_did_not_change(self):
        days = [TODAY + timedelta(days=1)]
        proposal = self.proposal(days)
        b.pending(self.db, 1, 100, proposal)
        self.db.execute("INSERT INTO overrides VALUES(?,'dogs',2)", (str(days[0]),))
        self.db.commit()
        answer = Mock()
        b.handle_availability_button(self.db, 1, 'confirm', 1, 100, answer)
        answer.assert_called_with('av_stale')
        self.assertFalse(b.is_off(self.db, 1, days[0]))

    def test_long_names_and_all_dates_fit_message_and_button_limits(self):
        self.db.execute('UPDATE members SET name=? WHERE id=2', ('🦮' * 500,))
        self.db.commit()
        days = [TODAY + timedelta(days=offset) for offset in range(31)]
        text, keyboard = b.av_view(self.db, 1, self.proposal(days))
        self.assertLessEqual(len(text.encode('utf-16-le')) // 2, 4096)
        self.assertIn('Save 31 days', str(keyboard))
        for row in keyboard['inline_keyboard']:
            for button in row:
                self.assertLessEqual(len(button['callback_data'].encode()), 64)
        proposal = self.proposal(days)
        proposal['impact'] = b.av_impact(self.db, 1, proposal, TIME)
        shown = []
        for page in range(5):
            proposal['impact_page'] = page
            detail, buttons = b.av_view(self.db, 1, proposal)
            self.assertLessEqual(len(detail.encode('utf-16-le')) // 2, 4096)
            shown.extend(re.findall(r'^(\d+/\d+) ', detail, re.M))
            for row in buttons['inline_keyboard']:
                for button in row: self.assertLessEqual(len(button['callback_data'].encode()), 64)
        self.assertEqual(shown, [f'{day.day}/{day.month}' for day in days])
        self.assertIn('…', text)

    def test_cancelled_review_leaves_real_schedules_and_outbox_identical(self):
        def state():
            return {table: [tuple(row) for row in self.db.execute('SELECT * FROM ' + table)]
                    for table in ('members', 'off', 'overrides', 'nights', 'outbox')}
        before = state()
        b.open_availability(self.db, 1, days=[TODAY], review=True)
        self.assertEqual(before, state())
        b.handle_availability_button(self.db, 1, 'cancel', 1, 100, Mock())
        self.assertEqual(before, state())
        self.assertIsNone(b.peek_pending(self.db, 1, 100))

    def test_worst_case_four_long_names_and_statuses_fit_without_hiding_dates(self):
        for uid in (2, 3, 4, 5):
            self.db.execute('REPLACE INTO members(id,name,role,joined,lang) VALUES(?,?,?,?,?)',
                            (uid, '🦮' * 500, 'parent', uid, 'en'))
        self.db.commit()
        days = [TODAY + timedelta(days=offset) for offset in range(31)]
        before = {'dogs': {'person': 2, 'status': 'on', 'delivered': True, 'closed': False},
                  'dishes': {'person': 3, 'status': 'on', 'delivered': True, 'closed': False}}
        after = {'dogs': {'person': 4, 'status': 'on', 'delivered': True, 'closed': False},
                 'dishes': {'person': 5, 'status': 'on', 'delivered': True, 'closed': False}}
        impact = [{'day': str(day), 'selected': True, 'before': before, 'after': after} for day in days]
        shown = []
        for page in range(5):
            proposal = dict(self.proposal(days), impact_page=page)
            text = b.av_impact_text(self.db, 1, proposal, impact, TIME)
            self.assertLessEqual(len(text.encode('utf-16-le')) // 2, 3900)
            shown.extend(re.findall(r'^(\d+/\d+) ', text, re.M))
        self.assertEqual(shown, [f'{day.day}/{day.month}' for day in days])

    def test_two_selected_dates_have_short_summary_and_all_later_effects_are_disclosed(self):
        days = [TODAY + timedelta(days=1), TODAY + timedelta(days=2)]
        b.open_availability(self.db, 1, days=days, review=True)
        proposal = b.peek_pending(self.db, 1, 100)
        impact = proposal['impact']
        later = [item for item in impact if not item['selected']]
        self.assertEqual(len(later), 28)
        text, keyboard = b.av_view(self.db, 1, proposal)
        self.assertEqual(len(re.findall(r'^\d+/\d+ ', text, re.M)), 2)
        self.assertLess(len(text), 700)
        self.assertIn('28 other dates change', text)
        self.assertIn('Covering a walk counts as a turn', text)
        self.assertIn('View all 30 dates', str(keyboard))
        self.assertNotIn('rest of the 31 days stays the same', text)
        for unused in ('📩', '✓', '🙋', '⌛'): self.assertNotIn(unused, text)
        shown = []
        for page in range((len(impact) + 6) // 7):
            b.handle_availability_button(self.db, 1, 'details:' + str(page), 1, 100, Mock())
            detail = self.edit.call_args.args[2]
            shown.extend(re.findall(r'^(\d+/\d+) ', detail, re.M))
            self.assertLessEqual(len(re.findall(r'^\d+/\d+ ', detail, re.M)), 7)
        self.assertEqual(shown, [f'{date.fromisoformat(item["day"]).day}/{date.fromisoformat(item["day"]).month}' for item in impact])

    def test_detail_navigation_uses_saved_impact_and_cannot_reapprove_changed_plan(self):
        days = [TODAY + timedelta(days=1), TODAY + timedelta(days=2)]
        b.open_availability(self.db, 1, days=days, review=True)
        original = b.peek_pending(self.db, 1, 100)
        self.db.execute("INSERT INTO overrides VALUES(?,'dogs',2)", (str(TODAY + timedelta(days=3)),))
        self.db.commit()
        before = self.db.total_changes
        with patch.object(b, 'av_impact', side_effect=AssertionError('must not recompute saved details')):
            b.handle_availability_button(self.db, 1, 'details:0', 1, 100, Mock())
            b.handle_availability_button(self.db, 1, 'summary', 1, 100, Mock())
        proposal = b.peek_pending(self.db, 1, 100)
        self.assertEqual(proposal['impact'], original['impact'])
        self.assertEqual(proposal['snapshot'], original['snapshot'])
        self.assertEqual(self.db.total_changes - before, 2)  # private display state only
        self.assertEqual(self.db.execute('SELECT count(*) FROM off').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)
        answer = Mock()
        b.handle_availability_button(self.db, 1, 'confirm', 1, 100, answer)
        answer.assert_called_with('av_stale')

    def test_back_discards_saved_effect_and_review_rebuilds_it(self):
        day = TODAY + timedelta(days=1)
        b.open_availability(self.db, 1, days=[day], review=True)
        b.handle_availability_button(self.db, 1, 'back', 1, 100, Mock())
        proposal = b.peek_pending(self.db, 1, 100)
        self.assertNotIn('impact', proposal)
        self.assertNotIn('snapshot', proposal)
        self.assertNotIn('impact_page', proposal)
        b.handle_availability_button(self.db, 1, 'review', 1, 100, Mock())
        self.assertIn('impact', b.peek_pending(self.db, 1, 100))

    def test_save_from_details_is_same_single_gate_and_commits_the_saved_projection(self):
        days = [TODAY + timedelta(days=1), TODAY + timedelta(days=2)]
        b.open_availability(self.db, 1, days=days, review=True)
        b.handle_availability_button(self.db, 1, 'details:1', 1, 100, Mock())
        proposal = b.peek_pending(self.db, 1, 100)
        _, keyboard = b.av_view(self.db, 1, proposal)
        self.assertIn('av:confirm', str(keyboard))
        b.handle_availability_button(self.db, 1, 'confirm', 1, 100, Mock())
        self.assertIsNone(b.peek_pending(self.db, 1, 100))
        actual = b.av_plan(self.db, TIME)
        for item in proposal['impact']: self.assertEqual(item['after'], actual[item['day']])


if __name__ == '__main__':
    unittest.main()
