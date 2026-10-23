"""Ensure the simulator uses temporary state and real bot callbacks offline."""
import unittest
from unittest.mock import patch
import preview
import dogbot


class OfflinePreview(unittest.TestCase):
    def setUp(self):
        self.network = patch('urllib.request.urlopen',side_effect=AssertionError('Network forbidden'))
        self.network.start(); self.addCleanup(self.network.stop)
        self.demo = preview.Demo(); self.addCleanup(self.demo.close)

    def test_all_clock_scenarios_render_without_network(self):
        for clock in preview.CLOCKS:
            self.demo.reset(clock)
            for uid in preview.PERSONAS:
                page = self.demo.page(uid)
                self.assertIn('Offline demo',page)
                self.assertIn('method="post"',page)
                self.assertIn('Afwas',page)
                self.assertIn('Honden',page)
        self.assertEqual(self.demo.db.execute('PRAGMA database_list').fetchone()[2],'')

    def test_real_done_callback_updates_chore(self):
        self.demo.reset('dogs')
        chore = dogbot.night(self.demo.db,self.demo.time.date(),'dogs')
        uid = chore['walker']
        message = next(m for m in self.demo.messages[uid] if any(
            x.get('callback_data','').startswith('done:dogs:') for row in m['markup'].get('inline_keyboard',[]) for x in row))
        self.demo.action(uid,{'action':'tap','message':str(message['id']),'data':'done:dogs:2026-10-23'})
        self.assertEqual(dogbot.night(self.demo.db,self.demo.time.date(),'dogs')['status'],'done')

    def test_only_actual_buttons_can_be_clicked(self):
        msg = self.demo.messages[1][-1]
        with self.assertRaises(ValueError): self.demo.action(1,{'action':'tap','message':str(msg['id']),'data':'destroy'})

    def test_bot_transport_fails_closed(self):
        with self.assertRaises(RuntimeError): self.demo.api('sendMessage',chat_id=1,text='not allowed')

    def test_untrusted_text_is_escaped(self):
        self.demo.send(1,'<script>alert(1)</script>')
        self.assertNotIn('<script>',self.demo.page(1))
        self.assertEqual(preview.formatted('<b>Fine</b><img src=x onerror=bad>',True),'<b>Fine</b>')


if __name__ == '__main__': unittest.main()
