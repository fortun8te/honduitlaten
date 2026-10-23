import unittest
from unittest.mock import patch
import dogbot as b
from test_dogbot import Base, T


class Navigation(Base):
    def test_navigation_from_ack_becomes_the_live_panel(self):
        self.text(1, '/today')
        previous = self.db.execute('SELECT msg FROM weekmsg WHERE id=1').fetchone()[0]
        with patch.object(b, 'api', return_value=True) as api:
            self.tap(1, 'points', 500)
        panel = self.db.execute('SELECT * FROM weekmsg WHERE id=1').fetchone()
        self.assertEqual((panel['msg'], panel['page']), (500, -3))
        api.assert_any_call('editMessageReplyMarkup', chat_id=1, message_id=previous, reply_markup={'inline_keyboard': []})
        self.night(T, 1, 'done')
        b.refresh_weeks(self.db)
        self.assertEqual(self.edits[-1][1], 500)
        self.assertIn('you: 1', self.edits[-1][2])

    def test_opening_new_view_does_not_remove_private_approval(self):
        self.text(1, '/today')
        self.text(1, 'not tomorrow')
        proposal = b.all_pending(self.db)[0]
        self.text(1, '/points')
        self.assertIn(proposal, b.all_pending(self.db))
        self.assertFalse(b.is_off(self.db, 1, T))


if __name__ == '__main__': unittest.main()
