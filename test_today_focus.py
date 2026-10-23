"""Today answers what this person needs next, without changing the schedule."""
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
import dogbot as b


class TodayFocus(unittest.TestCase):
    def setUp(self):
        self.db=b.connect(':memory:');self.addCleanup(self.db.close)
        self.clock=datetime(2026,10,23,17,tzinfo=b.TZ)
        for uid,label,role in [(1,'Michael','walker'),(2,'Christian','walker'),(3,'Mum','parent'),(4,'Dad','parent')]:
            self.db.execute('INSERT INTO members(id,name,role,joined,lang) VALUES(?,?,?,?,?)',(uid,label,role,int((self.clock-timedelta(days=2)).timestamp())+uid,'nl'))
        self.db.commit()
        self.sent=[]
        def send(chat,text,markup=None,**kwargs):self.sent.append((chat,text,markup));return 100+len(self.sent)
        for key,value in [('now',lambda:self.clock),('OWNER_ID',1),('send',send),('api',lambda *a,**k:True)]:
            context=patch.object(b,key,value);context.start();self.addCleanup(context.stop)
        context=patch('urllib.request.urlopen',side_effect=AssertionError('No networking'))
        context.start();self.addCleanup(context.stop)

    def row(self,chore='dogs',who=1,status='on',day=None,cover=None):
        self.db.execute('INSERT INTO nights(day,chore,walker,status,cover_id) VALUES(?,?,?,?,?)',
                        (str(day or self.clock.date()),chore,who,status,cover));self.db.commit()

    def actions(self,uid):
        return [x['callback_data'] for r in b.home_view(self.db,uid)[1]['inline_keyboard'] for x in r]

    def focus(self,uid):return b.home_view(self.db,uid)[0].splitlines()[1]

    def test_next_task_is_personal_and_both_actual_assignments_remain_visible(self):
        self.assertIn('21:45',self.focus(1))
        self.assertIn('18:30',self.focus(2))
        text,kb=b.home_view(self.db,1)
        self.assertIn('Afwas 18:30 · Christian',text)
        self.assertIn('Honden 21:45 · jij',text)
        self.assertIn('done:dogs:2026-10-23',self.actions(1))
        self.assertNotIn('done:dishes:2026-10-23',self.actions(1))

    def test_solo_next_task_changes_after_first_completion(self):
        self.db.execute('DELETE FROM members WHERE id=2')
        self.assertIn('18:30',self.focus(1))
        self.row('dishes',1,'done')
        self.assertIn('21:45',self.focus(1))
        self.row('dogs',1,'done')
        self.assertEqual(self.focus(1),b.tr('nl','focus_done'))

    def test_due_task_is_unconfirmed_not_asserted_undone(self):
        self.clock=self.clock.replace(hour=22)
        self.row()
        self.assertEqual(self.focus(1),b.tr('nl','focus_open',chore=b.tr('nl','dogs_label')))

    def test_unavailable_does_not_hide_existing_assigned_task(self):
        day=self.clock.date()
        b.apply_off(self.db,1,[day])
        self.assertEqual(self.focus(1),b.tr('nl','focus_off'))
        self.row()
        self.assertEqual(self.focus(1),b.tr('nl','focus_open',chore=b.tr('nl','dogs_label')))
        self.assertIn('done:dogs:2026-10-23',self.actions(1))

    def test_pending_request_is_personal_and_keeps_task_buttons(self):
        day=self.clock.date()
        b.pending(self.db,2,700,{'type':'swap','from':1,'to':2,'owners':{str(day):b.owner(self.db,day,day)},'back':None})
        self.assertEqual(self.focus(2),b.tr('nl','requests_waiting',count=1))
        self.assertIn('requests',self.actions(2))
        self.assertIn('done:dishes:2026-10-23',self.actions(2))
        self.assertNotIn('Ruilverzoeken',self.focus(1))

    def test_yesterdays_work_outweighs_new_day_and_pending_request(self):
        yesterday=self.clock.date()-timedelta(days=1)
        self.row(day=yesterday)
        self.clock=self.clock.replace(hour=1)
        day=self.clock.date()
        b.pending(self.db,1,700,{'type':'swap','from':2,'to':1,'owners':{str(day):b.owner(self.db,day,day)},'back':None})
        text,kb=b.home_view(self.db,1)
        self.assertIn('Do 22',self.focus(1))
        actions=self.actions(1)
        self.assertEqual(actions[0],'done:dogs:2026-10-22')
        self.assertIn('requests',actions)
        self.assertIn('Ruilverzoeken om te beantwoorden',text)
        self.clock=self.clock.replace(hour=3)
        self.assertNotIn('Do 22',self.focus(1))
        self.assertNotIn('done:dogs:2026-10-22',self.actions(1))

    def test_parent_assignment_and_completion_have_distinct_summaries(self):
        self.assertEqual(self.focus(3),b.tr('nl','focus_assigned'))
        self.row('dogs',1,'done');self.row('dishes',2,'done')
        self.assertEqual(self.focus(3),b.tr('nl','focus_family_done'))

    def test_parent_takeover_does_not_claim_completion(self):
        self.row('dogs',None,'parent',cover=3)
        self.assertEqual(self.focus(3),b.tr('nl','focus_parent_own',chore=b.tr('nl','dogs_label')))
        self.assertIn('pdone:dogs:2026-10-23',self.actions(3))
        self.assertNotEqual(self.focus(4),b.tr('nl','focus_family_done'))

    def test_parent_help_prioritizes_unassigned_and_overdue(self):
        self.row('dogs',None,'nobody')
        self.assertIn('Hulp nodig',self.focus(3));self.assertIn('Honden',self.focus(3))
        self.db.execute('DELETE FROM nights')
        self.row('dishes',2,'on');self.clock=self.clock.replace(hour=21)
        self.assertEqual(self.focus(3),b.tr('nl','focus_help',chore=b.tr('nl','dishes_label')))

    def test_parent_both_off_does_not_say_everything_assigned(self):
        b.apply_off(self.db,1,[self.clock.date()]);b.apply_off(self.db,2,[self.clock.date()])
        self.assertIn('Hulp nodig',self.focus(3))
        self.assertNotEqual(self.focus(3),b.tr('nl','focus_assigned'))

    def test_parent_yesterday_unconfirmed_outweighs_new_plan(self):
        yesterday=self.clock.date()-timedelta(days=1)
        self.row(day=yesterday)
        self.clock=self.clock.replace(hour=1)
        self.assertIn('Do 22',self.focus(3));self.assertIn('hulp nodig',self.focus(3))
        self.assertEqual(self.actions(3)[0],'pcover:dogs:2026-10-22')

    def test_setup_shortcut_only_for_owner_until_second_walker_joins(self):
        self.db.execute('DELETE FROM members WHERE id=2')
        self.assertIn('family',self.actions(1))
        self.assertIn('tweede loper',b.home_view(self.db,1)[0])
        self.assertNotIn('family',self.actions(3))
        self.db.execute("INSERT INTO members(id,name,role,joined) VALUES(2,'Christian','walker',2)")
        self.assertNotIn('family',self.actions(1))

    def test_first_home_explains_use_without_extra_welcome_card(self):
        self.db.execute('DELETE FROM members')
        b.on_start(self.db,{'id':1,'first_name':'Michael','language_code':'nl'},'')
        self.assertEqual(len(self.sent),1)
        self.assertIn(b.tr('nl','first_home_walker'),self.sent[0][1])
        self.assertIn('Vandaag',self.sent[0][1])
        self.assertIn('family',self.actions(1))
        self.clock+=timedelta(days=1)
        self.assertNotIn(b.tr('nl','first_home_walker'),b.home_view(self.db,1)[0])

    def test_yesterday_missing_record_is_unknown_not_planned(self):
        yesterday=self.clock.date()-timedelta(days=1)
        self.row(day=yesterday)
        self.clock=self.clock.replace(hour=1)
        text,_=b.home_view(self.db,1)
        self.assertIn(b.tr('nl','past_unrecorded'),text)
        self.assertEqual(b.chore_status(self.db,1,yesterday,'dishes',None,'nl'),b.tr('nl','past_unrecorded'))

    def test_rendering_does_not_write_any_state(self):
        self.db.execute('DELETE FROM members WHERE id=2');self.db.commit()
        before=self.db.total_changes
        for uid in (1,3,4):
            b.home_view(self.db,uid);b.home_focus(self.db,uid,self.clock)
        self.assertEqual(before,self.db.total_changes)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM nights').fetchone()[0],0)


if __name__=='__main__':unittest.main()
