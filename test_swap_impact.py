"""Acceptance tests for truthful swap scope and renewed consent after changes."""
import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import dogbot as b


class SwapImpact(unittest.TestCase):
    def setUp(self):
        self.db = b.connect(':memory:'); self.addCleanup(self.db.close)
        self.clock = datetime(2026, 11, 2, 20, 30, tzinfo=b.TZ)
        self.day = self.clock.date()
        self.sent, self.edits, self.answers = [], [], []
        for uid, role in ((1, 'walker'), (2, 'walker'), (3, 'parent')):
            self.db.execute('INSERT INTO members(id,name,role,joined) VALUES(?,?,?,?)',
                            (uid, 'Person' + str(uid), role, int(self.clock.replace(hour=9).timestamp()) + uid))
        self.db.commit()
        for key, value in [('now', lambda: self.clock), ('send', self.send), ('edit', self.edit), ('api', lambda *a, **k: True)]:
            p = patch.object(b, key, value); p.start(); self.addCleanup(p.stop)

    def send(self, uid, text, markup=None, **kw):
        msg = 100 + len(self.sent)
        self.sent.append((uid, text, markup, msg)); return msg

    def edit(self, uid, msg, text, markup=None, **kw):
        self.edits.append((uid, msg, text, markup)); return True

    def tap(self, uid, data, msg=10):
        b.on_button(self.db, {'id': 'q', 'from': {'id': uid}, 'data': data,
                             'message': {'message_id': msg, 'chat': {'id': uid, 'type': 'private'}}})

    def live(self, dish_status='on'):
        for chore, walker in (('dogs', 1), ('dishes', 2)):
            status = dish_status if chore == 'dishes' else 'on'
            parent = 3 if status == 'parent' else None
            self.db.execute('INSERT INTO nights(day,chore,walker,status,msg,cover_id,rotation_walker) VALUES(?,?,?,?,?,?,?)',
                            (str(self.day), chore, None if parent else walker, status, 10 if chore == 'dogs' else 20, parent, walker))
        self.db.commit()

    def request(self):
        return b.ask(self.db, 1, 2, [self.day])

    def accept(self, source):
        return b.on_swap_reply(self.db, 2, True, 2, source, lambda key=None, **kw: self.answers.append(key))

    def assignments(self):
        return [(r['day'], r['chore'], r['walker'], r['status'], r['cover_id'])
                for r in self.db.execute('SELECT * FROM nights ORDER BY day,chore')]

    def assert_projection_matches_saved(self, impact):
        for entry in impact:
            day = b.date.fromisoformat(entry['day'])
            dog = b.owner(self.db, day, self.day)
            for chore in b.CHORES:
                row = b.night(self.db, day, chore)
                actual = (row['walker'] or row['cover_id']) if row else dog if chore == 'dogs' else b.dishes(self.db, day, dog)
                status = row['status'] if row else 'planned'
                self.assertEqual((entry['after'][chore]['person'], entry['after'][chore]['status']),
                                 (actual, status), (day, chore))

    def test_projection_does_not_commit_or_change_open_source_transaction(self):
        self.live()
        self.db.execute('INSERT INTO off(id,day) VALUES(?,?)', (2, str(self.day + timedelta(days=1))))
        before = list(self.db.iterdump())
        self.assertTrue(self.db.in_transaction)
        impact = b.swap_impact(self.db, 2, [self.day, self.day + timedelta(days=1)], self.clock)
        self.assertTrue(impact)
        self.assertTrue(self.db.in_transaction)
        self.assertEqual(list(self.db.iterdump()), before)
        self.assertEqual(self.sent, [])
        self.db.rollback()
        self.assertFalse(b.is_off(self.db, 2, self.day + timedelta(days=1)))

    def test_normal_projection_matches_both_accepted_chore_assignments(self):
        self.live(); impact = b.swap_impact(self.db, 2, [self.day], self.clock)
        today = next(r for r in impact if r['day'] == str(self.day))
        self.assertEqual([today['before'][c]['person'] for c in ('dogs', 'dishes')], [1, 2])
        self.assertEqual([today['after'][c]['person'] for c in ('dogs', 'dishes')], [2, 1])
        self.accept(self.request())
        self.assert_projection_matches_saved(impact)

    def test_completed_dishes_remain_with_original_completer(self):
        self.live('done'); impact = b.swap_impact(self.db, 2, [self.day], self.clock)
        today = next(r for r in impact if r['day'] == str(self.day))
        self.assertEqual((today['after']['dishes']['person'], today['after']['dishes']['status']), (2, 'done'))
        self.accept(self.request())
        self.assert_projection_matches_saved(impact)
        self.assertEqual(b.night(self.db, self.day, 'dishes')['walker'], 2)

    def test_parent_cover_is_preserved_in_preview_and_acceptance(self):
        self.live('parent'); impact = b.swap_impact(self.db, 2, [self.day], self.clock)
        today = next(r for r in impact if r['day'] == str(self.day))
        self.assertEqual((today['after']['dishes']['person'], today['after']['dishes']['status']), (3, 'parent'))
        self.accept(self.request()); self.assert_projection_matches_saved(impact)

    def test_after_dishes_cutoff_swap_changes_dogs_only(self):
        self.live(); self.clock = self.clock.replace(hour=21)
        impact = b.swap_impact(self.db, 2, [self.day], self.clock)
        today = next(r for r in impact if r['day'] == str(self.day))
        self.assertEqual(today['after']['dishes']['person'], 2)
        self.accept(self.request()); self.assert_projection_matches_saved(impact)
        self.assertEqual(b.night(self.db, self.day)['walker'], 2)
        self.assertEqual(b.night(self.db, self.day, 'dishes')['walker'], 2)

    def test_crossing_dishes_deadline_requires_second_explicit_accept(self):
        self.live(); source = self.request(); previous = b.peek_pending(self.db, 2, source)['impact']
        self.clock = self.clock.replace(hour=21)
        before = self.assignments()
        self.assertEqual(self.accept(source), 'review')
        self.assertEqual(self.assignments(), before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM overrides').fetchone()[0], 0)
        self.assertNotEqual(b.peek_pending(self.db, 2, source)['impact'], previous)
        self.assertIn('request_updated', self.answers)
        self.accept(source)
        self.assertEqual(b.night(self.db, self.day)['walker'], 2)
        self.assertEqual(b.night(self.db, self.day, 'dishes')['walker'], 2)

    def test_parent_cover_after_request_requires_review_and_preserves_parent(self):
        self.live(); source = self.request()
        b.set_night(self.db, str(self.day), 'dishes', walker=None, cover_id=3, status='parent')
        before = self.assignments()
        self.assertEqual(self.accept(source), 'review')
        self.assertEqual(self.assignments(), before)
        self.accept(source)
        self.assertEqual(b.night(self.db, self.day)['walker'], 2)
        self.assertEqual(b.night(self.db, self.day, 'dishes')['status'], 'parent')
        self.assertEqual(b.night(self.db, self.day, 'dishes')['cover_id'], 3)

    def test_failed_updated_review_preserves_original_scope_and_assignment(self):
        self.live(); source = self.request(); original = b.peek_pending(self.db, 2, source)
        self.clock = self.clock.replace(hour=21)
        before = self.assignments()
        for failed in (None, False):
            with patch.object(b, 'edit', return_value=failed):
                self.assertEqual(self.accept(source), 'review')
            self.assertEqual(b.peek_pending(self.db, 2, source), original)
            self.assertEqual(self.assignments(), before)
        self.assertEqual(self.accept(source), 'review')
        self.assertEqual(self.assignments(), before)
        self.accept(source)
        self.assertEqual(b.night(self.db, self.day)['walker'], 2)

    def test_changed_sender_preview_never_sends_request_to_other_walker(self):
        self.live(); self.tap(1, f'nswap:{self.day}:0')
        source = self.sent[-1][3]
        self.assertEqual([m[0] for m in self.sent], [1])
        self.clock = self.clock.replace(hour=21)
        before = self.assignments()
        self.tap(1, 'request_confirm', source)
        self.assertEqual([m[0] for m in self.sent], [1])
        self.assertEqual(self.assignments(), before)
        self.assertFalse([p for _, p in b.all_pending(self.db) if p.get('type') == 'swap'])

    def test_month_scope_with_long_emoji_names_fits_telegram_for_both_languages(self):
        self.db.execute('UPDATE members SET name=? WHERE id=1', ('😀' * 64,))
        self.db.execute('UPDATE members SET name=? WHERE id=2', ('🦮' * 64,)); self.db.commit()
        days = [self.day + timedelta(days=i) for i in range(31)]
        impact = b.swap_impact(self.db, 2, days, self.clock)
        self.assertEqual(len([r for r in impact if r['selected']]), 31)
        for lang in ('en', 'nl'):
            self.db.execute('UPDATE members SET lang=?', (lang,)); self.db.commit()
            for uid in (1, 2, 3):
                text = b.swap_request_text(self.db, uid, 1, impact)
                self.assertLess(len(text.encode('utf-16-le')) // 2, 4096, (lang, uid))
                self.assertIn('31 gekozen dagen' if lang == 'nl' else '31 selected dates', text)
                self.assertEqual(len(re.findall(r'^\d+/\d+ ·', text, re.MULTILINE)), 5)
                visible_dates = []
                for page in range(5):
                    detail = b.swap_request_text(self.db, uid, 1, impact, page=page)
                    self.assertLess(len(detail.encode('utf-16-le')) // 2, 4096, (lang, uid, page))
                    rendered = re.findall(r'^(\d+/\d+) ·', detail, re.MULTILINE)
                    self.assertEqual(len(rendered), 3 if page == 4 else 7)
                    visible_dates.extend(rendered)
                self.assertEqual(visible_dates, [f'{day.day}/{day.month}' for day in days])

    def test_private_sender_detail_navigation_never_sends_or_changes_plan(self):
        self.live()
        self.tap(1, f'nswap:{self.day}:0')
        source = self.sent[-1][3]
        proposal = b.peek_pending(self.db, 1, source)
        self.assertGreater(len(proposal['impact']), 7)
        before = self.assignments()
        untouched = {table: [tuple(row) for row in self.db.execute('SELECT * FROM ' + table)]
                     for table in ('nights', 'off', 'overrides', 'outbox')}
        messages = list(self.sent)
        for callback in ('request_preview_details:0', 'request_preview_details:1', 'request_preview_summary'):
            self.tap(1, callback, source)
            self.assertEqual(self.assignments(), before)
            self.assertEqual(self.sent, messages)
            self.assertEqual(b.peek_pending(self.db, 1, source), proposal)
            for table, rows in untouched.items():
                self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM ' + table)], rows)
            callbacks = [button['callback_data'] for row in self.edits[-1][3]['inline_keyboard'] for button in row]
            self.assertEqual(callbacks.count('request_confirm'), 1)
            self.assertIn('request_cancel', callbacks)
            self.assertNotIn('accept', callbacks)
            self.assertFalse(any(cb.startswith('swap_reply:') for cb in callbacks))
        self.tap(1, 'request_confirm', source)
        self.assertEqual([message[0] for message in self.sent[len(messages):]], [2])
        self.assertEqual(self.assignments(), before, 'Sending a request must still wait for the recipient')

    def test_inbox_opening_does_not_accept_or_change_proposal(self):
        self.live(); source = self.request()
        before = self.assignments(); original = b.peek_pending(self.db, 2, source)
        self.tap(2, f'request_open:2:{source}', msg=555)
        self.assertEqual(self.assignments(), before)
        self.assertEqual(b.peek_pending(self.db, 2, source), original)
        self.tap(3, f'request_open:2:{source}', msg=556)
        self.assertEqual(self.assignments(), before)
        self.assertEqual(b.peek_pending(self.db, 2, source), original)

    def test_legacy_request_cannot_commit_without_showing_current_task_scope(self):
        self.live()
        source = 777
        b.pending(self.db, 2, source, {'type': 'swap', 'from': 1, 'to': 2, 'back': None,
                                     'owners': {str(self.day): 1}})
        before = self.assignments()
        self.assertEqual(self.accept(source), 'review')
        self.assertEqual(self.assignments(), before)
        self.assertIsNotNone(b.peek_pending(self.db, 2, source).get('impact'))
        self.accept(source)
        self.assertEqual(b.night(self.db, self.day)['walker'], 2)


if __name__ == '__main__': unittest.main()
