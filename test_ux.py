"""Offline checks of usable navigation and accurate family chore views."""
import unittest
from unittest.mock import patch
from datetime import date, datetime, timedelta
import dogbot as b

DAY = date(2026, 10, 23)
TIME = datetime(2026, 10, 23, 21, 50, tzinfo=b.TZ)


def actions(markup):
    return [button['callback_data'] for row in markup['inline_keyboard'] for button in row]


class FamilyUX(unittest.TestCase):
    def setUp(self):
        self.db = b.connect(':memory:')
        self.addCleanup(self.db.close)
        for uid, label, role in [(1, 'Michael', 'walker'), (2, 'Christian', 'walker'), (3, 'Mum', 'parent')]:
            self.db.execute('INSERT INTO members(id,name,role,joined,lang) VALUES(?,?,?,?,?)', (uid,label,role,uid,'nl'))
        self.db.commit()
        clock = patch.object(b, 'now', return_value=TIME)
        clock.start(); self.addCleanup(clock.stop)

    def test_week_exposes_both_jobs_and_actual_completion(self):
        self.db.execute("INSERT INTO nights(day,chore,walker,status,done_at) VALUES(?,'dishes',2,'done','19:10')", (str(DAY),))
        self.db.execute('INSERT INTO off VALUES(?,?)', (1,str(DAY)))
        b.kv(self.db,'p_2_88', '{"type":"swap","owners":{"2026-10-23":1}}')
        text, kb = b.week_view(self.db, DAY, 'nl', uid=1)
        self.assertEqual(text.count('🍽'), 7)
        self.assertEqual(text.count('🐕'), 7)
        self.assertIn('19:10', text)
        self.assertIn('Christian', text)
        self.assertIn('Michael', text)
        self.assertIn(b.tr('nl','pending_status'), text)
        self.assertIn('home', actions(kb))
        self.assertNotIn('more', actions(kb))
        self.assertIn('more', actions(b.home_view(self.db,1)[1]))
        self.assertIn('help', actions(b.more_view(self.db,1)[1]))

    def test_week_is_compact_and_settled_day_has_no_edit_controls(self):
        text, _ = b.week_view(self.db, DAY, 'nl', uid=1)
        self.assertLessEqual(len([line for line in text.splitlines() if line]), 8)
        home, _ = b.home_view(self.db,1)
        self.assertIn('18:30', home)
        self.assertIn('21:45', home)
        for status in ('done', 'parent'):
            self.db.execute("REPLACE INTO nights(day,chore,walker,status) VALUES(?,'dogs',1,?)", (str(DAY),status))
            _, kb = b.night_view(self.db, 1, DAY, 0)
            self.assertFalse(any(c.split(':')[0] in ('noff','nin','nswap','ntake') for c in actions(kb)))

    def test_month_pages_cover_exact_horizon_with_no_empty_button_rows(self):
        seen = []
        with patch.object(b, 'AHEAD', 31):
            for page in range(5):
                _, kb = b.week_view(self.db, DAY, 'nl', page=page, uid=1)
                self.assertTrue(all(kb['inline_keyboard']))
                callbacks = actions(kb)
                days = [date.fromisoformat(c.split(':')[1]) for c in callbacks if c.startswith('wk:')]
                self.assertEqual(len(days), 3 if page == 4 else 7)
                seen.extend(days)
                self.assertEqual('wp:' + str(page-1) in callbacks, page > 0)
                self.assertEqual('wp:' + str(page+1) in callbacks, page < 4)
            self.assertEqual(seen, [DAY + timedelta(days=i) for i in range(31)])
            self.assertEqual(b.week_view(self.db, DAY, 'nl', page=99, uid=1), b.week_view(self.db, DAY, 'nl', page=4, uid=1))

    def test_points_remain_accessible_through_more_and_command(self):
        self.db.execute("INSERT INTO nights(day,chore,walker,status,done_at) VALUES(?,'dogs',1,'done','22:10')", (str(DAY),))
        home, kb = b.home_view(self.db, 1)
        self.assertNotIn(b.tr('nl','points_own',points=1), home)
        self.assertIn('more', actions(kb))
        self.assertIn('points', actions(b.more_view(self.db,1)[1]))
        detail, _ = b.points_view(self.db, 1)
        self.assertIn('jij: 1', detail)
        self.assertIn('Christian: 0', detail)
        self.assertNotIn('Mum:', detail)
        self.assertIn('1 punt per afgeronde taak', b.help_view(self.db,1)[0])
        with patch.object(b,'send',return_value=99) as send:
            b.on_text(self.db,{'from':{'id':1},'chat':{'type':'private'},'text':'/points'})
        self.assertEqual(send.call_args.args[1], detail)

    def test_solo_walker_has_both_chores(self):
        self.db.execute('DELETE FROM members WHERE id=2')
        text, _ = b.night_view(self.db, 1, DAY, 0)
        self.assertEqual(text.count(' · jij'), 2)

    def test_parent_can_read_day_without_changing_planning(self):
        self.db.execute("INSERT INTO nights(day,chore,walker,status) VALUES(?,'dogs',1,'on')",(str(DAY),))
        _, kb = b.night_view(self.db, 3, DAY, 0)
        callbacks = actions(kb)
        self.assertFalse(any(c.split(':')[0] in ('noff','nin','ntake','nswap') for c in callbacks))
        self.assertIn('pcover:dogs:2026-10-23', callbacks)
        self.assertIn('wp:0', callbacks)

    def test_home_actions_bind_specific_date_and_owner(self):
        self.db.execute("INSERT INTO nights(day,chore,walker,status) VALUES(?,'dogs',1,'on')", (str(DAY),))
        self.db.execute("INSERT INTO nights(day,chore,walker,status) VALUES(?,'dishes',1,'on')", (str(DAY),))
        own = actions(b.home_view(self.db,1)[1])
        other = actions(b.home_view(self.db,2)[1])
        self.assertIn('done:dogs:2026-10-23', own)
        self.assertIn('cant:dogs:2026-10-23', own)
        self.assertIn('done:dishes:2026-10-23', own)
        self.assertNotIn('cant:dishes:2026-10-23', own)
        self.assertFalse(any(c.startswith(('done:','cant:')) for c in other))

    def test_parent_takeover_is_not_completion_and_only_coverer_can_finish(self):
        self.db.execute("INSERT INTO nights(day,chore,walker,status,cover_id) VALUES(?,'dogs',NULL,'parent',3)", (str(DAY),))
        text, kb = b.home_view(self.db, 3)
        self.assertIn('Mum', text)
        self.assertIn('neemt over', text)
        self.assertNotIn('✅', text)
        self.assertNotIn(3, {row['id'] for row in b.monthly_points(self.db, DAY)})
        self.assertIn('pdone:dogs:2026-10-23', actions(kb))
        self.assertNotIn('pdone:dogs:2026-10-23', actions(b.home_view(self.db,1)[1]))

    def test_midnight_keeps_yesterdays_unfinished_action_dated(self):
        self.db.execute("INSERT INTO nights(day,chore,walker,status) VALUES('2026-10-22','dogs',1,'on')")
        with patch.object(b,'now',return_value=TIME.replace(hour=1)):
            text, kb = b.home_view(self.db,1)
        self.assertIn('done:dogs:2026-10-22', actions(kb))
        self.assertIn('Do 22', text)
        with patch.object(b,'now',return_value=TIME.replace(hour=3)):
            self.assertNotIn('done:dogs:2026-10-22', actions(b.home_view(self.db,1)[1]))

    def test_after_cutoff_day_still_readable(self):
        with patch.object(b,'now',return_value=TIME.replace(hour=23,minute=30)):
            text,kb = b.view(self.db,1,0,DAY)
        self.assertEqual(text.count('🐕'),1)
        self.assertFalse(any(c.startswith('nswap:') for c in actions(kb)))

    def test_failed_delivery_preserves_live_overview(self):
        self.db.execute("INSERT INTO weekmsg(id,msg,page,day,sig) VALUES(1,42,0,NULL,'old')")
        with patch.object(b,'send',return_value=None), patch.object(b,'api') as api:
            b.open_home(self.db,1)
        self.assertEqual(self.db.execute('SELECT msg FROM weekmsg WHERE id=1').fetchone()[0],42)
        api.assert_not_called()

    def test_failed_refresh_is_retried(self):
        self.db.execute("INSERT INTO weekmsg(id,msg,page,day,sig) VALUES(1,42,-1,NULL,'old')")
        with patch.object(b,'edit',return_value=None) as edit:
            b.refresh_weeks(self.db); b.refresh_weeks(self.db)
        self.assertEqual(edit.call_count,2)
        self.assertEqual(self.db.execute('SELECT sig FROM weekmsg').fetchone()[0],'old')

    def test_registered_start_goes_home_and_unknown_text_has_menu(self):
        with patch.object(b,'open_home') as home:
            b.on_start(self.db,{'id':1},'')
        home.assert_called_once_with(self.db,1)
        with patch.object(b,'send',return_value=99) as send:
            b.on_text(self.db,{'from':{'id':1},'chat':{'type':'private'},'text':'what?'})
        self.assertIn('home',actions(send.call_args.args[2]))

    def test_commands_have_localized_visible_menu(self):
        with patch.object(b,'api',return_value={'username':'test'}) as api:
            b.setup()
        commands=[call.kwargs['commands'] for call in api.call_args_list if call.args[0]=='setMyCommands']
        self.assertTrue(commands)
        for menu in commands:
            self.assertTrue({'today','week','points','help','lang'} <= {x['command'] for x in menu})


if __name__ == '__main__': unittest.main()
