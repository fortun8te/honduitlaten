import unittest
from datetime import date, datetime
import dogbot as b

T = date(2026, 10, 16)  # Friday: Michael's evening
D = lambda d: date(2026, 10, d)
M, C = 1, 2

class Base(unittest.TestCase):
    real_send = staticmethod(b.send)
    def setUp(self):
        self.db = b.connect(":memory:")
        j = int(datetime(2026, 10, 16, 9, tzinfo=b.TZ).timestamp())
        for row in [(M, "Michael", "walker", j), (C, "Christian", "walker", j + 1)]:
            self.db.execute("INSERT INTO members(id, name, role, joined) VALUES(?,?,?,?)", row)
        self.addCleanup(self.db.close)
        self.sent, self.edits, self.calls = [], [], []
        for k in ("send", "edit", "delete", "api", "now"):
            self.addCleanup(setattr, b, k, getattr(b, k))
        def send(chat, text, markup=None, silent=False):
            self.sent.append((chat, text, markup, silent)); return 100 + len(self.sent)
        b.send = send
        b.edit = lambda chat, msg, text, rows=(): self.edits.append((chat, msg, text, b.kbd(rows)))
        b.delete = lambda chat, msg: self.calls.append(("delete", chat, msg))
        b.api = lambda method, **p: self.calls.append((method, p))
        self.clock(T, 12)
    def clock(self, d, h, m=0):
        t = datetime(d.year, d.month, d.day, h, m, tzinfo=b.TZ)
        b.now = lambda: t
        return t
    def tick(self, d, h, m=0): b.tick(self.db, self.clock(d, h, m))
    def tap(self, uid, data, msg=1):
        b.on_button(self.db, {"id": "q", "from": {"id": uid}, "data": data, "message": {"chat": {"id": uid}, "message_id": msg}})
    def text(self, uid, text):
        b.on_text(self.db, {"from": {"id": uid, "first_name": "Kees"}, "chat": {"type": "private"}, "text": text, "message_id": 7})
    def answer(self): return next(p.get("text") for m, p in reversed(self.calls) if m == "answerCallbackQuery")
    def pings(self, uid): return [s for s in self.sent if s[0] == uid and not s[3]]
    def labels(self, markup): return [x["text"] for row in markup["inline_keyboard"] for x in row]
    def score(self): return b.score(self.db, M), b.score(self.db, C)

class Rota(Base):
    def test_om_en_om(self):
        self.assertEqual([b.rota(self.db, D(d)) for d in range(16, 20)], [M, C, M, C])
        self.assertEqual({b.who(self.db, D(17), c) for c in b.CHORES}, {C})
    def test_one_walker_does_all(self):
        self.db.execute("DELETE FROM members WHERE id=?", (C,))
        self.assertEqual({b.rota(self.db, D(d)) for d in range(16, 20)}, {M})

class Evening(Base):
    def test_card_at_1830_to_owner_only(self):
        self.tick(T, 18, 29)
        self.assertEqual(self.sent, [])
        self.tick(T, 18, 30); self.tick(T, 18, 31)
        self.assertEqual(len(self.pings(M)), 1)
        self.assertEqual(self.sent[0][1], "<b>Vanavond ben jij aan de beurt</b>\n🍽 Afwas · 18:30\n🐕 Honden · 21:45")
        self.assertEqual(self.labels(self.sent[0][2]), ["✅ Afwas", "✅ Honden", "🙅 Ik kan niet"])
    def test_max_two_pings(self):
        self.tick(T, 18, 30); self.tick(T, 21, 45)
        b.post_card(self.db, M, T, True)
        self.assertEqual(len(self.pings(M)), 2)
        self.assertTrue(self.pings(M)[1][1].startswith("<b>Tijd voor de honden 🐕</b>"))
        self.assertIn(("delete", M, 101), self.calls)
    def test_done(self):
        self.tick(T, 18, 30)
        self.clock(T, 18, 41); self.tap(M, f"d:{T}:afwas")
        self.clock(T, 21, 52); self.tap(M, f"d:{T}:honden")
        self.assertEqual(self.edits[-1][2], "<b>Alles gedaan, toppp 🫶</b>\n🍽 Afwas ✅ 18:41\n🐕 Honden ✅ 21:52")
        self.assertEqual(self.score(), (0, 0))
    def test_dogs_not_before_21(self):
        self.clock(T, 18, 40); self.tap(M, f"d:{T}:honden")
        self.assertEqual(self.answer(), "Nog even wachten, honden zijn om 21:45")
        self.assertTrue(b.is_open(self.db, T, "honden"))
    def test_cant_tonight(self):
        self.tick(T, 18, 30)
        self.tap(M, f"k:{T}")
        self.assertEqual(self.labels(self.edits[-1][3]), ["🍽 Afwas", "🐕 Honden", "« Terug"])
        self.tap(M, f"g:{T}:afwas")
        self.assertEqual(self.pings(C)[0][1], "<b>Vanavond ben jij aan de beurt</b>\n🍽 Afwas · +1")
        self.assertIn("🍽 Afwas → Christian", self.edits[-1][2])
        self.clock(T, 19); self.tap(C, f"d:{T}:afwas")
        self.assertEqual(self.score(), (-1, 1))
    def test_both_cant_is_nobody(self):
        self.tick(T, 18, 30)
        self.clock(T, 21); self.tap(M, f"g:{T}:honden"); self.tap(C, f"g:{T}:honden")
        self.assertIsNone(b.who(self.db, T, "honden"))
        self.assertIn("🐕 Honden → iemand anders", self.pings(M)[-1][1])
        self.clock(T, 22); self.tap(M, f"d:{T}:afwas")
        self.assertEqual(self.score(), (0, 0))
    def test_too_late_to_give(self):
        self.clock(T, 23, 5); self.tap(M, f"g:{T}:honden")
        self.assertEqual((self.answer(), b.who(self.db, T, "honden")), ("Te laat ahah, regel 't even zelf", M))
    def test_forgotten_at_3(self):
        self.tick(T, 18, 30); self.tick(D(17), 2, 59)
        self.assertEqual(self.score(), (0, 0))
        self.tick(D(17), 3)
        self.assertEqual(self.score(), (-2, 2))
        self.assertIn("🐕 Honden ✕ vergeten", self.edits[-1][2])
    def test_no_close_before_first_run(self):
        self.tick(D(17), 3)
        self.assertEqual(self.score(), (0, 0))
    def test_given_ahead_means_no_card(self):
        for c in b.CHORES: self.tap(M, f"t:{T}:{c}")
        self.assertTrue(all(s[3] for s in self.sent))
        self.tick(T, 18, 30)
        self.assertEqual((self.pings(M), len(self.pings(C))), ([], 1))

class Calendar(Base):
    def test_only_your_evenings(self):
        text, rows = b.calendar_view(self.db, M)
        self.assertEqual(self.labels(b.kbd(rows)), ["vr 16", "zo 18", "di 20", "do 22", "za 24", "ma 26", "wo 28", "« Terug"])
    def test_toggle_is_quiet_and_undoable(self):
        self.tap(M, "t:2026-10-18:afwas")
        self.assertEqual(self.sent[-1][::3], (C, True))
        self.assertEqual(self.sent[-1][1], "Michael kan zo 18 de afwas niet, die doe jij 🙏")
        self.assertIn("zo 18 🐕", self.labels(b.kbd(b.calendar_view(self.db, M)[1])))
        self.tap(M, "t:2026-10-18:afwas")
        self.assertEqual((self.sent[-1][1], b.who(self.db, D(18), "afwas")), ("Michael doet zo 18 de afwas toch zelf 👍", M))
    def test_whole_evening_off(self):
        for c in b.CHORES: self.tap(M, f"t:2026-10-18:{c}")
        row = b.calendar_view(self.db, M)[1][0]
        self.assertEqual((row[1]["text"], row[1]["style"]), ("✕ zo 18", "danger"))
    def test_taken_over_then_nobody(self):
        self.tap(C, "t:2026-10-17:afwas")
        self.assertEqual(self.sent[-1][1], "Christian kan morgen de afwas niet, die doe jij 🙏")
        self.assertIn("za 17 🍽", self.labels(b.kbd(b.calendar_view(self.db, M)[1])))
        self.tap(M, "t:2026-10-17:afwas")
        self.assertIsNone(b.who(self.db, D(17), "afwas"))
        self.assertEqual(self.sent[-1][:2], (C, "Michael kan morgen de afwas ook niet, iemand anders moet 't doen 😭"))

class Payback(Base):
    def owe(self):
        self.tick(T, 18, 30); self.tap(M, f"g:{T}:afwas")
        self.clock(T, 19); self.tap(C, f"d:{T}:afwas")
        b.settle(self.db, T)
    def test_debt_is_paid_back(self):
        self.owe()
        self.assertEqual((b.who(self.db, D(19), "afwas"), b.task(self.db, D(19), "afwas")["payback"]), (M, 1))
        self.assertIn("⚖️ jij -1 · inhalen ma 19 🍽", b.menu_view(self.db, M)[0])
        self.tap(M, "t:2026-10-19:afwas")
        self.assertEqual(self.answer(), "Dit is een inhaalklus, die blijft van jou")
        self.clock(D(19), 19); self.tap(M, "d:2026-10-19:afwas"); b.settle(self.db, D(19))
        self.assertEqual(self.score(), (0, 0))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM tasks WHERE payback=1 AND done_at IS NULL").fetchone()[0], 0)
    def test_released_when_even_again(self):
        self.owe()
        self.tap(C, "t:2026-10-17:afwas")
        self.clock(D(17), 19); self.tap(M, "d:2026-10-17:afwas"); b.settle(self.db, D(17))
        self.assertEqual((self.score(), b.who(self.db, D(19), "afwas")), ((0, 0), C))

class Menu(Base):
    def test_menu(self):
        self.text(M, "hoi")
        self.assertIn(("delete", M, 7), self.calls)
        self.assertEqual(self.sent[-1][1], "<b>Vanavond</b>  jij\n<b>Morgen</b>  Christian\n⚖️ gelijk")
        self.text(M, "☰ Menu")
        self.assertIn(("delete", M, 101), self.calls)
    def test_split_evening(self):
        self.tap(M, f"t:{T}:afwas")
        self.assertTrue(b.menu_view(self.db, M)[0].startswith("<b>Vanavond</b>  🍽 Christian · 🐕 jij"))

class Start(Base):
    def test_stranger(self):
        self.text(9, "/start")
        self.assertEqual(self.sent[-1][1], "Deze bot is privé")
    def test_invite_and_full(self):
        self.db.execute("DELETE FROM members WHERE id=?", (C,))
        rows = b.menu_view(self.db, M)[1]
        self.assertIn("start%3Dw_", rows[-1][0]["url"])
        self.text(3, f"/start w_{b.kv(self.db, 'code')}")
        self.assertIn(3, b.walkers(self.db))
        self.assertEqual(self.sent[0][1], "Welkom bij Honduitlaatbot 🐕\nJe krijgt een berichtje als je aan de beurt bent")
        self.assertEqual(self.sent[1][:2], (M, "Kees doet mee 🫶"))
        self.text(4, f"/start w_{b.kv(self.db, 'code')}")
        self.assertEqual(self.sent[-1][1], "Er zijn al twee lopers")
    def test_no_code_no_entry(self):
        self.db.execute("DELETE FROM members WHERE id=?", (C,))
        self.text(3, "/start w_None")
        self.assertNotIn(3, b.walkers(self.db))

class Infra(Base):
    def test_tap_survives_failed_answer(self):
        def api(method, **p):
            if method == "answerCallbackQuery": raise OSError("query too old")
        b.api = api
        self.clock(T, 18, 40); self.tap(M, f"d:{T}:afwas")
        self.assertFalse(b.is_open(self.db, T, "afwas"))
    def test_malformed_callback(self):
        for data in ("d:x", "d:2026-10-16:fiets", "zz:2026-10-16"):
            self.tap(M, data)
            self.assertEqual(self.answer(), "Die is verlopen")
    def test_429_waits_once(self):
        import io, urllib.error
        slept, calls = [], []
        def api(method, **p):
            calls.append(1)
            raise urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b'{"parameters": {"retry_after": 30}}'))
        self.addCleanup(setattr, b.time, "sleep", b.time.sleep)
        b.api, b.send, b.time.sleep = api, Base.real_send, slept.append
        self.assertIsNone(b.send(1, "x"))
        self.assertEqual((len(calls), slept[-1]), (1, 10))
    def test_lock_single_instance(self):
        import fcntl, tempfile
        path = tempfile.mktemp()
        self.addCleanup(setattr, b, "LOCK", b.LOCK); self.addCleanup(setattr, b, "TOKEN", b.TOKEN)
        b.LOCK, b.TOKEN = path, "x"
        held = open(path, "a+"); fcntl.flock(held, fcntl.LOCK_EX)
        with self.assertRaises(SystemExit) as e: b.run()
        self.assertEqual(e.exception.code, 3)
        held.close()

if __name__ == "__main__":
    unittest.main()
