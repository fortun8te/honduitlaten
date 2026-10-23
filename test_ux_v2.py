"""Private confirmation, stable family setup and compact navigation journeys."""
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
import dogbot as b

TIME = datetime(2026,10,23,20,0,tzinfo=b.TZ)


def callbacks(kb):
    return [button['callback_data'] for row in kb['inline_keyboard'] for button in row]


class UXJourneys(unittest.TestCase):
    def setUp(self):
        self.db = b.connect(':memory:'); self.addCleanup(self.db.close)
        for uid,name,role in [(1,'Michael','walker'),(2,'Christian','walker'),(3,'Mum','parent')]:
            self.db.execute('INSERT INTO members(id,name,role,joined,lang) VALUES(?,?,?,?,?)',(uid,name,role,uid,'nl'))
        self.db.commit()
        b.kv(self.db,'bot','offline_demo')
        self.sent, self.edited = [], []
        def send(chat,text,markup=None,**kw):
            self.sent.append((chat,text,markup)); return 100+len(self.sent)
        def edit(chat,msg,text,markup=None,**kw):
            self.edited.append((chat,msg,text,markup)); return True
        for key,value in [('OWNER_ID',1),('now',lambda:TIME),('send',send),('edit',edit)]:
            obj=patch.object(b,key,value);obj.start();self.addCleanup(obj.stop)
        obj=patch('urllib.request.urlopen',side_effect=AssertionError('Network forbidden'))
        obj.start();self.addCleanup(obj.stop)

    def ui(self,kind,uid=1,msg=8,arg=''):
        answers=[]
        b.handle_ui_button(self.db,uid,kind,arg,uid,msg,lambda *a,**kw:answers.append(a))
        return answers

    def test_primary_navigation_consistent_and_secondary_in_more(self):
        for uid in (1,2,3):
            self.assertEqual(callbacks(b.menu_markup(self.db,uid)),['home'])
            self.assertTrue({'plan','more'}<=set(callbacks(b.home_view(self.db,uid)[1])))
            self.assertTrue({'points','history'}<=set(callbacks(b.more_view(self.db,uid)[1])))
            self.assertLessEqual(len(b.menu_markup(self.db,uid)['inline_keyboard']),2)
            self.assertTrue({'help','language','family'} <= set(callbacks(b.more_view(self.db,uid)[1])))

    def test_family_links_stable_and_private(self):
        first,_=b.family_view(self.db,1);code=b.kv(self.db,'code')
        second,_=b.family_view(self.db,1)
        self.assertEqual(first,second)
        self.assertEqual(code,b.kv(self.db,'code'))
        self.assertIn('Michael',first);self.assertIn('Christian',first);self.assertIn('Mum',first)
        self.assertIn('lopers: 0 · ouders: 1',first)
        for uid in (2,3):
            text,kb=b.family_view(self.db,uid)
            self.assertNotIn('https://',text)
            self.assertNotIn('rotate_links',callbacks(kb))

    def test_invite_command_does_not_revoke_links(self):
        message={'from':{'id':1},'chat':{'type':'private'},'text':'/invite'}
        b.on_text(self.db,message);code=b.kv(self.db,'code')
        b.on_text(self.db,message)
        self.assertEqual(code,b.kv(self.db,'code'))

    def test_rotation_preview_private_and_cancel_has_no_effect(self):
        b.family_view(self.db,1);code=b.kv(self.db,'code')
        b.open_home(self.db,1)
        tracked=dict(self.db.execute('SELECT * FROM weekmsg WHERE id=1').fetchone())
        self.ui('rotate_links');msg=100+len(self.sent)
        self.assertEqual(code,b.kv(self.db,'code'))
        self.assertEqual(self.sent[-1][0],1)
        self.assertEqual(dict(self.db.execute('SELECT * FROM weekmsg WHERE id=1').fetchone()),tracked)
        self.assertEqual(callbacks(self.sent[-1][2]),['rotate_confirm','rotate_cancel'])
        self.ui('rotate_cancel',msg=msg)
        self.assertEqual(code,b.kv(self.db,'code'))
        self.assertIsNone(b.peek_pending(self.db,1,msg))

    def test_rotation_requires_current_owner_proposal_and_is_once_only(self):
        b.family_view(self.db,1);original=b.kv(self.db,'code')
        self.ui('rotate_confirm');self.assertEqual(original,b.kv(self.db,'code'))
        self.ui('rotate_links',uid=2);self.assertFalse(self.sent)
        self.ui('rotate_links');msg=100+len(self.sent)
        self.ui('rotate_confirm',uid=2,msg=msg);self.assertEqual(original,b.kv(self.db,'code'))
        self.ui('rotate_confirm',msg=msg);changed=b.kv(self.db,'code')
        self.assertNotEqual(original,changed)
        self.ui('rotate_confirm',msg=msg);self.assertEqual(changed,b.kv(self.db,'code'))
        self.assertTrue(all(row[0]==1 for row in self.sent))

    def test_expired_and_superseded_rotation_cannot_change_links(self):
        b.family_view(self.db,1)
        self.ui('rotate_links');msg=100+len(self.sent)
        with patch.object(b,'now',return_value=TIME+timedelta(hours=2)):
            self.ui('rotate_confirm',msg=msg)
        old=b.kv(self.db,'code')
        self.assertNotIn('https://',self.sent[-1][1])
        b.kv(self.db,'code','newer-existing-link')
        self.ui('rotate_confirm',msg=msg)
        self.assertEqual('newer-existing-link',b.kv(self.db,'code'))
        self.assertNotEqual(old,b.kv(self.db,'code'))

    def test_join_has_one_actionable_home(self):
        self.db.execute('DELETE FROM members WHERE id=2')
        b.kv(self.db,'code','joincode')
        b.on_start(self.db,{'id':4,'first_name':'New walker','language_code':'nl'},'walker_joincode')
        own=[entry for entry in self.sent if entry[0]==4]
        self.assertEqual(len(own),1)
        self.assertIn('Vandaag',own[0][1])
        self.assertTrue({'plan','more'}<=set(callbacks(own[0][2])))

    def test_points_previous_month_and_recent_history_owner_boundaries(self):
        for day, chore, owner, status in [('2026-09-30','dogs',1,'done'),('2026-10-16','dogs',1,'done'),
                                         ('2026-10-17','dogs',1,'done'),('2026-10-23','dishes',1,'on'),
                                         ('2026-10-22','dogs',2,'done')]:
            self.db.execute('INSERT INTO nights(day,chore,walker,status,done_at) VALUES(?,?,?,?,?)',(day,chore,owner,status,'22:00'))
        previous,kb=b.points_view(self.db,1,previous=True)
        self.assertIn('sep 2026',previous);self.assertIn('jij: 1',previous)
        self.assertIn('points_month:current',callbacks(kb))
        history,kb=b.history_view(self.db,1)
        actions=callbacks(kb)
        self.assertIn('correction:2026-10-17:dogs:undo',actions)
        self.assertIn('correction:2026-10-23:dishes:done',actions)
        self.assertFalse(any('2026-10-16' in action or '2026-10-22' in action for action in actions))
        labels=[button['text'] for row in kb['inline_keyboard'] for button in row]
        self.assertTrue(any('✓' in label for label in labels))
        self.assertEqual({row['id']:row['points'] for row in b.monthly_points(self.db,TIME.date())}[1],2)

    def test_navigation_helper_edits_without_new_chat_messages(self):
        for kind in ('more','family','history'):
            self.ui(kind)
        self.ui('points_month',arg='previous')
        self.assertEqual(len(self.edited),4)
        self.assertFalse(self.sent)

    def test_pending_swap_recipient_has_home_entry(self):
        today=TIME.date()
        b.pending(self.db,2,700,{'type':'swap','from':1,'to':2,'owners':{str(today):b.owner(self.db,today,today)},'back':None})
        text,kb=b.home_view(self.db,2)
        self.assertTrue(any(button['callback_data']=='requests' and '(1)' in button['text'] for row in kb['inline_keyboard'] for button in row))
        self.assertIn('requests',callbacks(kb))
        self.assertNotIn('Ruilverzoeken om te beantwoorden',b.home_view(self.db,1)[0])


if __name__ == '__main__': unittest.main()
