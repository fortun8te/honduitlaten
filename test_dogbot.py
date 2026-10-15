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
            self.sent.append((chat, text, markup, silent, b.now().date())); return 100 + len(self.sent)
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
    def test_fixed_start_whoever_joined_first(self):
        self.addCleanup(setattr, b, "OWNER_ID", b.OWNER_ID); b.OWNER_ID = M
        self.db.execute("UPDATE members SET joined=0 WHERE id=?", (C,))
        self.assertEqual([b.rota(self.db, D(d)) for d in (16, 17, 31)], [M, C, C])
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
        self.assertEqual(self.answer(), "Nog even wachten 🙏")
        self.assertTrue(b.is_open(self.db, T, "honden"))
        self.tap(M, "d:2026-10-18:afwas")
        self.assertEqual((self.answer(), b.is_open(self.db, D(18), "afwas")), ("Nog even wachten 🙏", True))
    def test_cant_tonight(self):
        self.tick(T, 18, 30)
        self.tap(M, f"k:{T}")
        self.assertEqual(self.labels(self.edits[-1][3]), ["🍽 Afwas", "🐕 Honden", "Allebei", "« Terug"])
        self.tap(M, f"g:{T}:afwas")
        self.assertEqual(self.pings(C)[0][1], "<b>Vanavond ben jij aan de beurt</b>\n🍽 Afwas · +1")
        self.assertIn("🍽 Afwas → Christian", self.edits[-1][2])
        self.clock(T, 19); self.tap(C, f"d:{T}:afwas")
        self.assertEqual(self.score(), (-1, 1))
    def test_allebei_is_one_ping(self):
        self.tick(T, 18, 30); self.tap(M, f"g:{T}:")
        self.assertEqual({b.who(self.db, T, c) for c in b.CHORES}, {C})
        self.assertEqual([s[1] for s in self.pings(C)], ["<b>Vanavond ben jij aan de beurt</b>\n🍽 Afwas · +1\n🐕 Honden · +1"])
        self.clock(T, 18, 31); self.tap(C, f"k:{T}")
        self.assertEqual(self.labels(self.edits[-1][3]), ["🍽 Afwas", "🐕 Honden", "Allebei", "« Terug"])
    def test_only_dishes_tonight(self):
        self.tick(T, 18, 30); self.clock(T, 21); self.tap(M, f"g:{T}:honden")
        self.assertEqual((b.who(self.db, T, "afwas"), b.who(self.db, T, "honden")), (M, C))
        self.assertEqual(self.labels(self.edits[-1][3]), ["✅ Afwas", "🙅 Ik kan niet"])
    def test_both_cant_is_nobody(self):
        self.tick(T, 18, 30)
        self.clock(T, 21); self.tap(M, f"g:{T}:honden"); self.tap(C, f"g:{T}:honden")
        self.assertIsNone(b.who(self.db, T, "honden"))
        self.assertEqual(len(self.pings(M)), 1)  # quiet: nothing for Michael to do
        self.assertEqual(self.sent[-1][::3], (M, True))
        self.assertIn("🐕 Honden → iemand anders", [e for e in self.edits if e[0] == M][-1][2])
        self.clock(T, 22); self.tap(M, f"d:{T}:afwas")
        self.assertEqual(self.score(), (0, 0))
    def test_nobody_keeps_the_2145_reminder(self):
        self.tick(T, 18, 30); self.clock(T, 19)
        self.tap(M, f"g:{T}:afwas"); self.tap(C, f"g:{T}:afwas")
        self.tick(T, 21, 45)
        self.assertEqual(len(self.pings(M)), 2)
    def test_late_start_one_ping(self):
        self.tick(T, 22)
        self.assertEqual(len(self.pings(M)), 1)
        self.assertNotIn("delete", [c[0] for c in self.calls])
    def test_failed_send_keeps_card_and_retries(self):
        self.tick(T, 18, 30)
        real, b.send = b.send, lambda *a, **k: None
        self.clock(T, 19); self.tap(M, f"g:{T}:afwas")
        b.send = real
        self.assertNotIn("delete", [c[0] for c in self.calls])
        self.tick(T, 19, 1)
        self.assertEqual(self.pings(C)[0][1], "<b>Vanavond ben jij aan de beurt</b>\n🍽 Afwas · +1")
    def test_after_23_no_more_can_t(self):
        self.tick(T, 18, 30); self.tick(T, 23)
        self.assertEqual(self.labels(self.edits[-1][3]), ["✅ Afwas", "✅ Honden"])
        self.tap(M, f"k:{T}")
        self.assertEqual(self.answer(), "Te laat ahah, regel 't even zelf")
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
    def test_released_on_the_day_itself_before_1830(self):
        self.owe()  # Michael -1, payback: ma 19 afwas
        self.clock(T, 19, 5); self.tap(M, "t:2026-10-18:afwas")  # Christian takes zo 18 afwas and forgets it
        b.setrow(self.db, D(18), "honden", who=M, done_at="21:50")
        self.clock(D(19), 3); b.close(self.db, D(18))
        self.assertEqual((self.score(), b.who(self.db, D(19), "afwas")), ((0, 0), C))
    def test_no_extra_payback_after_midnight(self):
        self.owe()  # payback ma 19 afwas, still open until 03:00 on the 20th
        self.clock(D(20), 0, 5); b.settle(self.db, D(20))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM tasks WHERE payback=1").fetchone()[0], 1)
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

class Random(Base):
    def test_three_weeks_of_random_taps(self):
        """Both brothers tapping anything at any time never breaks the rules."""
        import collections, random
        rnd, kinds = random.Random(7), ["d", "k", "g", "b", "t", "e"]
        for i in range(21):
            day = b.timedelta(days=i) + T
            for h, m in [(12, 0), (18, 30), (19, 10), (21, 0), (21, 45), (22, 15), (23, 30)]:
                self.tick(day, h, m)
                for _ in range(rnd.randint(0, 3)):
                    d = day + b.timedelta(days=rnd.choice([0, 0, 1, 3, 13, -1]))
                    self.tap(rnd.choice([M, C]), f"{rnd.choice(kinds)}:{d}:{rnd.choice(list(b.CHORES))}")
                    self.assertNotEqual(self.answer(), "Oeps, probeer nog eens")
                    self.assertEqual(sum(self.score()), 0)
            self.tick(day + b.timedelta(days=1), 3)
            for r in self.db.execute("SELECT * FROM tasks WHERE payback=1").fetchall():
                self.assertNotEqual(b.rota(self.db, date.fromisoformat(r["day"])), r["who"])
        loud = collections.Counter((s[0], s[4]) for s in self.sent if not s[3])
        self.assertLessEqual(max(loud.values()), b.MAX_PINGS)

class Upgrade(Base):
    OLD = """
    CREATE TABLE members(id INTEGER PRIMARY KEY, name TEXT, role TEXT, joined INTEGER, lang TEXT DEFAULT 'en');
    CREATE TABLE off(id INTEGER, day TEXT, PRIMARY KEY(id, day));
    CREATE TABLE kv(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE nights(day TEXT, chore TEXT DEFAULT 'dogs', walker INTEGER, status TEXT, cant TEXT DEFAULT '',
                        msg INTEGER, done_at TEXT, PRIMARY KEY(day, chore));
    INSERT INTO members VALUES(1, 'Michael', 'walker', 1760000000, 'en'), (2, 'Christian', 'walker', 1760000001, 'nl'),
                              (3, 'Mum', 'parent', 1760000002, 'en');
    INSERT INTO kv VALUES('offset', '4242');
    """
    def file_db(self, script=""):
        import os, sqlite3, tempfile
        path = os.path.join(tempfile.mkdtemp(), "dogbot.db")
        old = sqlite3.connect(path); old.executescript(script); old.close()
        return path
    def test_old_database_upgrades_with_backup(self):
        import os
        path = self.file_db(self.OLD)
        db = b.connect(path); self.addCleanup(db.close)
        self.assertTrue(os.path.exists(path + ".bak-v0"))
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], len(b.MIGRATIONS))
        self.assertEqual((b.walkers(db), b.kv(db, "offset")), ([M, C], "4242"))
        self.db = db
        self.tick(T, 3, 30); self.tick(T, 18, 30)  # yesterday was the old version: not forgotten
        self.assertEqual((len(self.pings(b.rota(db, T))), self.score()), (1, (0, 0)))
    def test_daily_backup(self):
        import os, sqlite3
        path = self.file_db(self.OLD)
        self.db = b.connect(path); self.addCleanup(self.db.close)
        self.tick(T, 12); self.tap(M, f"t:{T}:afwas")
        copy = sqlite3.connect(path + ".bak-vr"); self.addCleanup(copy.close)
        self.assertEqual(copy.execute("SELECT COUNT(*) FROM members").fetchone()[0], 3)
    def test_second_start_changes_nothing(self):
        import os
        path = self.file_db()
        b.connect(path).close(); b.connect(path).close()
        self.assertEqual([f for f in os.listdir(os.path.dirname(path)) if ".bak" in f], [])
    def test_restart_mid_evening_sends_nothing_twice(self):
        path = self.file_db(self.OLD)
        self.db = b.connect(path)
        self.tick(T, 18, 30); self.tick(T, 21, 45)
        self.db.close(); self.db = b.connect(path); self.addCleanup(self.db.close)
        self.tick(T, 21, 50); self.tick(T, 22)
        self.assertEqual(len(self.pings(b.rota(self.db, T))), 2)

class Infra(Base):
    def test_tap_survives_failed_answer(self):
        def api(method, **p):
            if method == "answerCallbackQuery": raise OSError("query too old")
        b.api = api
        self.clock(T, 18, 40); self.tap(M, f"d:{T}:afwas")
        self.assertFalse(b.is_open(self.db, T, "afwas"))
    def test_malformed_callback(self):
        for data in ("d:x", "d:2026-10-16:fiets", "zz:2026-10-16", "t:2026-10-16", "d:2026-10-16", "d:9999-12-31:afwas"):
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
