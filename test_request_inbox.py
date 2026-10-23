"""Bounded request inbox; decisions require inspecting one stored proposal."""
import json
import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
import dogbot as b


def callbacks(markup):
    return [button['callback_data'] for row in markup['inline_keyboard'] for button in row]


class RequestInbox(unittest.TestCase):
    def setUp(self):
        self.db=b.connect(':memory:');self.addCleanup(self.db.close)
        self.clock=datetime(2026,10,23,20,tzinfo=b.TZ)
        joined=int((self.clock-timedelta(days=2)).timestamp())
        for uid,label,role in [(1,'Michael','walker'),(2,'Christian','walker'),(3,'Mum','parent')]:
            self.db.execute('INSERT INTO members(id,name,role,joined,lang) VALUES(?,?,?,?,?)',(uid,label,role,joined+uid,'nl'))
        self.db.commit()
        context=patch.object(b,'now',lambda:self.clock);context.start();self.addCleanup(context.stop)
        context=patch('urllib.request.urlopen',side_effect=AssertionError('No Telegram'));context.start();self.addCleanup(context.stop)
        self.days=[self.clock.date()+timedelta(days=i) for i in range(31)]
        self.owners={str(day):owner for day,owner in b.week(self.db,self.clock.date(),n=31)}
        self.impact=b.swap_impact(self.db,1,self.days,self.clock)

    def request(self,recipient=1,source=100,days=None):
        selected=days or self.days
        proposal={'type':'swap','from':2 if recipient==1 else 1,'to':recipient,'back':None,
                  'owners':{str(day):self.owners[str(day)] for day in selected},'impact':self.impact}
        b.pending(self.db,recipient,source,proposal)
        return proposal

    def select(self,viewer,recipient=1,source=100):
        b.kv(self.db,f'request_view_{viewer}',json.dumps({'recipient':recipient,'source':source}))

    def test_six_summaries_per_page_no_decision_or_withdraw_controls(self):
        for source in range(100,113):self.request(source=source)
        seen=[]
        for page,expected in [(0,6),(1,6),(2,1)]:
            b.kv(self.db,'requests_page_1',str(page))
            before=self.db.total_changes
            text,kb=b.requests_view(self.db,1)
            actions=callbacks(kb)
            reviews=[action for action in actions if action.startswith('request_open:')]
            self.assertEqual(len(reviews),expected);seen.extend(reviews)
            self.assertFalse(any(action.startswith(('swap_reply:','withdraw:')) for action in actions))
            self.assertEqual('requests:'+str(page-1) in actions,page>0)
            self.assertEqual('requests:'+str(page+1) in actions,page<2)
            self.assertNotIn('Nu → na akkoord',text)
            self.assertIn('31 dagen',text)
            self.assertEqual(before,self.db.total_changes)
            self.assertTrue(all(kb['inline_keyboard']))
        self.assertEqual(len(set(seen)),13)

    def test_long_names_and_full_month_requests_fit_telegram(self):
        self.db.execute('UPDATE members SET name=? WHERE id=2',('<b>🐕&</b>'*1000,))
        for source in range(100,113):self.request(source=source)
        text,kb=b.requests_view(self.db,1)
        self.assertLess(len(text.encode('utf-16-le'))//2,4096)
        self.assertTrue(all(len(action.encode())<=64 for action in callbacks(kb)))
        self.select(1)
        detail,_=b.request_detail_view(self.db,1)
        self.assertLess(len(detail.encode('utf-16-le'))//2,4096)

    def test_missing_or_extreme_page_is_clamped_without_writing(self):
        for source in range(100,107):self.request(source=source)
        for value,expected in [('999','2/2'),('-2','1/2'),('bad','1/2')]:
            b.kv(self.db,'requests_page_1',value)
            before=self.db.total_changes
            self.assertIn(expected,b.requests_view(self.db,1)[0])
            self.assertEqual(before,self.db.total_changes)

    def test_incoming_detail_uses_saved_impact_before_decisions(self):
        proposal=self.request();self.select(1)
        b.apply_claim(self.db,1,[self.days[0]],'dishes') # dog ownership still valid; live dishes differ
        stored=b.peek_pending(self.db,1,100)
        before=self.db.total_changes
        with patch.object(b,'swap_impact',side_effect=AssertionError('Never recompute a saved review during rendering')):
            text,kb=b.request_detail_view(self.db,1)
        self.assertIn(b.swap_impact_text(self.db,1,proposal['impact']),text)
        self.assertIn('swap_reply:100:accept',callbacks(kb));self.assertIn('swap_reply:100:no',callbacks(kb))
        self.assertFalse(any(action.startswith('withdraw:') for action in callbacks(kb)))
        self.assertEqual(b.peek_pending(self.db,1,100),stored)
        self.assertEqual(before,self.db.total_changes)

    def test_outgoing_detail_allows_withdraw_only(self):
        self.request(recipient=2);self.select(1,recipient=2)
        text,kb=b.request_detail_view(self.db,1)
        self.assertIn('Jouw verzoek aan Christian',text)
        self.assertIn('withdraw:2:100',callbacks(kb))
        self.assertFalse(any(action.startswith('swap_reply:') for action in callbacks(kb)))

    def test_expired_detail_has_back_and_no_commit_controls(self):
        self.request();self.select(1)
        b.pending(self.db,1,100)
        text,kb=b.request_detail_view(self.db,1)
        self.assertIn('verlopen',text)
        self.assertIn('requests:0',callbacks(kb))
        self.assertFalse(any(action.startswith(('swap_reply:','withdraw:')) for action in callbacks(kb)))

    def test_missing_impact_cannot_be_accepted_from_detail(self):
        self.request();self.select(1)
        proposal=b.peek_pending(self.db,1,100);proposal.pop('impact');b.pending(self.db,1,100,proposal)
        with patch.object(b,'swap_impact',side_effect=AssertionError('No new approval context on read')):
            text,kb=b.request_detail_view(self.db,1)
        self.assertIn('geen opgeslagen overzicht',text)
        self.assertNotIn('swap_reply:100:accept',callbacks(kb))

    def test_open_validates_involvement_then_changes_only_display_state(self):
        self.request()
        pending=b.peek_pending(self.db,1,100)
        rows=[tuple(row) for row in self.db.execute('SELECT * FROM nights')]
        with patch.object(b,'show') as show:
            b.on_open_request(self.db,1,1,100,999,lambda *a:None)
            show.assert_called_once_with(self.db,1,999,-10)
        self.assertEqual(json.loads(b.kv(self.db,'request_view_1')),{'recipient':1,'source':100,'page':None})
        self.assertEqual(b.peek_pending(self.db,1,100),pending)
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM nights')],rows)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM off').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM overrides').fetchone()[0],0)

    def test_unrelated_and_parent_cannot_open_or_render_request(self):
        self.request()
        self.db.execute("INSERT INTO members(id,name,role,joined) VALUES(4,'Other','walker',999)")
        for uid in (3,4):
            answers=[]
            with patch.object(b,'show') as show:
                b.on_open_request(self.db,uid,1,100,999,lambda *args:answers.append(args))
                show.assert_not_called()
            self.assertEqual(answers,[('private',)])
            self.assertIsNone(b.kv(self.db,f'request_view_{uid}'))
            self.select(uid)
            text,kb=b.request_detail_view(self.db,uid)
            self.assertNotIn('Nu → na akkoord',text)
            self.assertNotIn('swap_reply:100:accept',callbacks(kb))
            self.assertFalse(any(a.startswith('request_open:') for a in callbacks(b.requests_view(self.db,uid)[1])))

    def test_real_list_to_detail_route_preserves_page_and_escapes_names(self):
        self.db.execute("UPDATE members SET name='<b>Christian</b>' WHERE id=2")
        for source in range(100,107):self.request(source=source)
        edited=[]
        def tap(data):
            b.on_button(self.db,{'id':'offline','from':{'id':1},'data':data,
                                'message':{'chat':{'id':1,'type':'private'},'message_id':900}})
        def edit(chat,msg,text,markup=None,**kwargs):
            edited.append((text,markup));return True
        with patch.object(b,'api',return_value=True),patch.object(b,'edit',side_effect=edit):
            tap('requests:1')
            self.assertIn('request_open:1:106',callbacks(edited[-1][1]))
            tap('request_open:1:106')
        text,kb=edited[-1]
        self.assertIn('&lt;b&gt;Christian&lt;/b&gt;',text)
        self.assertNotIn('<b>Christian</b>',text)
        self.assertIn('swap_reply:106:accept',callbacks(kb))
        self.assertIn('requests:1',callbacks(kb))
        self.assertEqual(b.kv(self.db,'requests_page_1'),'1')
        self.assertIsNotNone(b.peek_pending(self.db,1,106))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM off').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM overrides').fetchone()[0],0)

    def test_full_impact_pages_reach_every_saved_date_without_mutation(self):
        self.request()
        saved=b.peek_pending(self.db,1,100)
        seen=[]
        for page in range((len(self.impact)+6)//7):
            with patch.object(b,'show'):
                b.on_request_page(self.db,1,1,100,page,999,lambda *args:None)
            before=self.db.total_changes
            with patch.object(b,'swap_impact',side_effect=AssertionError('Read only cached impact')):
                text,kb=b.request_detail_view(self.db,1)
            expected=self.impact[page*7:page*7+7]
            displayed_dates=re.findall(r'^(\d{1,2}/\d{1,2}) ·',text,re.MULTILINE)
            self.assertEqual(displayed_dates,[f"{datetime.fromisoformat(item['day']).day}/{datetime.fromisoformat(item['day']).month}" for item in expected])
            self.assertLessEqual(len(displayed_dates),7)
            self.assertIn(b.swap_impact_text(self.db,1,self.impact,page=page),text)
            for item in expected:
                day=datetime.fromisoformat(item['day'])
                self.assertIn(f'{day.day}/{day.month}',text)
                seen.append(item['day'])
            self.assertIn('swap_reply:100:accept',callbacks(kb))
            self.assertIn('swap_reply:100:no',callbacks(kb))
            self.assertIn('request_open:1:100',callbacks(kb))
            self.assertNotIn('requests:0',callbacks(kb))  # full pages return via Summary
            self.assertEqual(f'request_page:1:100:{page-1}' in callbacks(kb),page>0)
            self.assertEqual(f'request_page:1:100:{page+1}' in callbacks(kb),page<(len(self.impact)-1)//7)
            self.assertEqual(before,self.db.total_changes)
        self.assertEqual(seen,[item['day'] for item in self.impact])
        self.assertEqual(b.peek_pending(self.db,1,100),saved)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM overrides').fetchone()[0],0)
        with patch.object(b,'show'):
            b.on_open_request(self.db,1,1,100,999,lambda *args:None)
        self.assertIsNone(json.loads(b.kv(self.db,'request_view_1'))['page'])
        summary,kb=b.request_detail_view(self.db,1)
        self.assertIn('request_page:1:100:0',callbacks(kb))

    def test_later_effects_have_an_optional_full_view_even_for_one_selected_day(self):
        impact=b.swap_impact(self.db,2,[self.days[0]],self.clock)
        self.assertTrue(any(not item['selected'] for item in impact))
        self.request(days=[self.days[0]])
        proposal=b.peek_pending(self.db,1,100);proposal['impact']=impact;b.pending(self.db,1,100,proposal)
        self.select(1)
        text,kb=b.request_detail_view(self.db,1)
        self.assertIn('request_page:1:100:0',callbacks(kb))
        self.assertIn('swap_reply:100:accept',callbacks(kb))
        self.assertLessEqual(len(text.splitlines()),16)

    def test_outgoing_full_pages_preserve_withdraw_and_reject_other_viewers(self):
        self.request(recipient=2)
        with patch.object(b,'show'):
            b.on_request_page(self.db,1,2,100,999,999,lambda *args:None)
        selection=json.loads(b.kv(self.db,'request_view_1'))
        self.assertEqual(selection['page'],(len(self.impact)-1)//7)
        _,kb=b.request_detail_view(self.db,1)
        self.assertIn('withdraw:2:100',callbacks(kb))
        self.assertFalse(any(cb.startswith('swap_reply:') for cb in callbacks(kb)))
        for viewer in (3,99):
            answers=[]
            with patch.object(b,'show') as show:
                b.on_request_page(self.db,viewer,2,100,0,999,lambda *args:answers.append(args))
                show.assert_not_called()
            self.assertEqual(answers,[('private',)])
            self.assertIsNone(b.kv(self.db,f'request_view_{viewer}'))

    def test_closed_or_invalid_request_never_creates_display_selection(self):
        for source in (100,101):
            if source==101:
                proposal=self.request(source=source);b.apply_claim(self.db,2,[self.days[0]])
            answers=[]
            with patch.object(b,'show') as show:
                b.on_open_request(self.db,1,1,source,999,lambda *args:answers.append(args))
                show.assert_not_called()
            self.assertEqual(answers,[('old',)])
            self.assertIsNone(b.kv(self.db,'request_view_1'))


if __name__=='__main__':unittest.main()
