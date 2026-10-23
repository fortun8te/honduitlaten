"""Minimal secondary views keep all destinations and private decision gates."""
import json
import unittest
from datetime import datetime,timedelta
from unittest.mock import patch
import dogbot as b


def buttons(markup):return [button for row in markup['inline_keyboard'] for button in row]
def actions(markup):return [button['callback_data'] for button in buttons(markup)]


class MinimalSecondary(unittest.TestCase):
    def setUp(self):
        self.db=b.connect(':memory:');self.addCleanup(self.db.close)
        self.clock=datetime(2026,10,23,20,tzinfo=b.TZ)
        joined=int((self.clock-timedelta(days=2)).timestamp())
        for uid,name,role in [(1,'Michael','walker'),(2,'Christian','walker'),(3,'Mum','parent')]:
            self.db.execute('INSERT INTO members(id,name,role,joined,lang) VALUES(?,?,?,?,?)',(uid,name,role,joined+uid,'nl'))
        self.db.commit();b.kv(self.db,'bot','offline');b.kv(self.db,'code','existinglink')
        self.sent=[]
        def send(chat,text,markup=None,**kw):self.sent.append((chat,text,markup));return 100+len(self.sent)
        for target,value in [('now',lambda:self.clock),('OWNER_ID',1),('send',send),('edit',lambda *a,**k:True),('api',lambda *a,**k:True)]:
            obj=patch.object(b,target,value);obj.start();self.addCleanup(obj.stop)
        obj=patch('urllib.request.urlopen',side_effect=AssertionError('No Telegram'));obj.start();self.addCleanup(obj.stop)

    def task(self,days_ago=0,chore='dogs',who=1,status='done'):
        day=self.clock.date()-timedelta(days=days_ago)
        self.db.execute('INSERT INTO nights(day,chore,walker,status) VALUES(?,?,?,?)',(str(day),chore,who,status));self.db.commit()
        return day

    def request(self,recipient=1):
        days=[self.clock.date()+timedelta(days=i) for i in range(31)]
        impact=b.swap_impact(self.db,recipient,days,self.clock)
        b.pending(self.db,recipient,500,{'type':'swap','from':2 if recipient==1 else 1,'to':recipient,
                                        'owners':{str(d):w for d,w in b.week(self.db,self.clock.date(),n=31)},'impact':impact,'back':None})

    def select(self,viewer,recipient=1,page=None):
        b.kv(self.db,f'request_view_{viewer}',json.dumps({'recipient':recipient,'source':500,'page':page}))

    def test_more_has_five_destinations_and_one_back(self):
        for uid in (1,2,3):
            text,kb=b.more_view(self.db,uid)
            self.assertEqual(set(actions(kb)),{'points','history','family','language','help','home'})
            self.assertEqual(len(buttons(kb)),6)
            self.assertEqual(len(text.splitlines()),1)

    def test_points_is_totals_with_three_controls(self):
        self.task()
        for previous in (False,True):
            text,kb=b.points_view(self.db,1,previous)
            self.assertLessEqual(len([line for line in text.splitlines() if line]),3)
            self.assertEqual(actions(kb),['points_month:current' if previous else 'points_month:previous','history','more'])
            self.assertNotIn(b.tr('nl','points_rule'),text)
        self.assertIn('1 punt per afgeronde taak',b.help_view(self.db,1)[0])
        self.assertIn('7 dagen',b.help_view(self.db,1)[0])
        self.assertEqual(len(b.help_view(self.db,1)[0].splitlines()),5)
        self.assertEqual(len(b.help_view(self.db,3)[0].splitlines()),4)

    def test_help_and_family_have_only_contextual_navigation(self):
        self.assertEqual(actions(b.help_view(self.db,1)[1]),['more'])
        self.assertEqual(actions(b.family_view(self.db,1)[1]),['rotate_links','more'])
        self.assertEqual(actions(b.family_view(self.db,2)[1]),['more'])
        self.assertEqual(actions(b.family_view(self.db,3)[1]),['more'])

    def test_history_not_duplicated_and_status_visible_on_every_task(self):
        day=self.task();self.task(1,'dishes',1,'on');self.task(2,'dogs',2,'done')
        text,kb=b.history_view(self.db,1)
        self.assertEqual(len([line for line in text.splitlines() if line]),2)
        self.assertNotIn(b.fmt(day,'nl'),text)
        task_buttons=[button for button in buttons(kb) if button['callback_data'].startswith('correction:')]
        self.assertEqual(len(task_buttons),2)
        self.assertIn('✓ klaar',task_buttons[0]['text'])
        self.assertIn(b.tr('nl','history_open'),task_buttons[1]['text'])
        self.assertTrue(task_buttons[0]['callback_data'].endswith(':undo'))
        self.assertTrue(task_buttons[1]['callback_data'].endswith(':done'))
        self.assertEqual(actions(kb)[-1],'more')

    def test_history_task_still_opens_private_preview_without_changing_completion(self):
        day=self.task()
        _,kb=b.history_view(self.db,1)
        action=next(cb for cb in actions(kb) if cb.startswith('correction:'))
        b.on_button(self.db,{'id':'test','from':{'id':1},'data':action,
                            'message':{'chat':{'id':1,'type':'private'},'message_id':99}})
        self.assertEqual(b.night(self.db,day)['status'],'done')
        self.assertEqual(len(self.sent),1);self.assertEqual(self.sent[0][0],1)
        self.assertIn('correct_confirm',actions(self.sent[0][2]))
        self.assertEqual(b.monthly_points(self.db,day)[0]['points'],1)

    def test_inbox_only_reviews_and_back_to_planning(self):
        self.request()
        text,kb=b.requests_view(self.db,1)
        self.assertEqual(actions(kb),['request_open:1:500','plan'])
        self.assertNotIn('Nu → na akkoord',text)

    def test_request_detail_has_one_back_at_each_level_and_decisions_preserved(self):
        self.request();self.select(1)
        _,kb=b.request_detail_view(self.db,1)
        summary=actions(kb)
        self.assertEqual(set(summary),{'request_page:1:500:0','swap_reply:500:accept','swap_reply:500:no','requests:0'})
        self.select(1,page=1)
        _,kb=b.request_detail_view(self.db,1)
        full=actions(kb)
        self.assertIn('request_open:1:500',full)
        self.assertFalse(any(cb.startswith('requests:') for cb in full))
        self.assertTrue({'request_page:1:500:0','request_page:1:500:2','swap_reply:500:accept','swap_reply:500:no'}<=set(full))
        self.assertFalse({'home','plan','points','more'}&set(full))

    def test_outgoing_retains_withdraw_and_expired_retains_return(self):
        self.request(recipient=2);self.select(1,recipient=2,page=1)
        _,kb=b.request_detail_view(self.db,1)
        self.assertIn('withdraw:2:500',actions(kb));self.assertIn('request_open:2:500',actions(kb))
        self.assertFalse(any(cb.startswith('swap_reply:') for cb in actions(kb)))
        b.pending(self.db,2,500)
        text,kb=b.request_detail_view(self.db,1)
        self.assertIn('verlopen',text)
        self.assertEqual(actions(kb),['requests:0'])

    def test_rendering_keeps_chore_and_request_state_unchanged(self):
        self.task();self.request();self.select(1)
        before=self.db.total_changes
        proposal=b.peek_pending(self.db,1,500)
        for fn in (b.more_view,b.points_view,b.history_view,b.help_view,b.family_view,b.requests_view,b.request_detail_view):
            fn(self.db,1)
        self.assertEqual(self.db.total_changes,before)
        self.assertEqual(b.peek_pending(self.db,1,500),proposal)
        self.assertEqual(b.night(self.db,self.clock.date())['status'],'done')


if __name__=='__main__':unittest.main()
