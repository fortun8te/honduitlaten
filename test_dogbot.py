import unittest
from datetime import date, datetime, timedelta
import dogbot as b

T = date(2026, 10, 15)  # Thursday
D = lambda d: date(2026, 10, d)

class Parser(unittest.TestCase):
    def check(self, text, days):
        self.assertEqual(b.parse_days(text, T), days, text)
    def test_single(self):
        for text, days in [("not fri", [D(16)]), ("kan niet vrijdag", [D(16)]), ("out tonight", [T]),
                           ("morgen niet", [D(16)]), ("busy 24th", [D(24)]), ("busy 3rd", [date(2026, 11, 3)]),
                           ("not 1/11", [date(2026, 11, 1)]), ("weg 2 nov", [date(2026, 11, 2)]), ("not thu", [T])]:
            self.check(text, days)
    def test_multi(self):
        self.check("kan niet weekend", [D(17), D(18)])
        self.check("busy sat sun", [D(17), D(18)])
        self.check("I do mon wed fri next week", [D(19), D(21), D(23)])
    def test_ranges(self):
        self.check("away fri-sun", [D(16), D(17), D(18)])
        self.check("off 20-23 oct", [D(20), D(21), D(22), D(23)])
        self.check("sat until mon", [D(17), D(18), D(19)])
        r = b.parse_days("vakantie tot 28 okt", T)
        self.assertEqual((r[0], r[-1], len(r)), (T, D(28), 14))
    def test_nothing(self):
        self.check("lol ok", [])
        self.check("i do not know", [])
    def test_claims(self):
        c = lambda s: b.parse_claim(s, 1, 2, "Christian")
        self.assertEqual([c("I do mon wed fri next week"), c("Christian takes the weekend"), c("ik doe dinsdag")], [1, 2, 1])
        self.assertEqual([c("kan niet weekend"), c("not fri")], [None, None])

class Base(unittest.TestCase):
    real_send = staticmethod(b.send)
    def setUp(self):
        self.db = b.connect(":memory:")
        j = int(datetime(2026, 10, 15, 9, tzinfo=b.TZ).timestamp())  # joined this morning
        for row in [(1, "Michael", "walker", j), (2, "Christian", "walker", j + 1), (3, "Mum", "parent", j + 2)]:
            self.db.execute("INSERT INTO members(id, name, role, joined) VALUES(?,?,?,?)", row)
        self.addCleanup(self.db.close)
        self.sent, self.edits, self.answers = [], [], []
        for k in ("send", "edit", "api", "now"):
            self.addCleanup(setattr, b, k, getattr(b, k))
        b.send = lambda chat, text, markup=None, **k: self.sent.append((chat, text)) or 100 + len(self.sent)
        b.edit = lambda chat, msg, text, markup=None, **k: self.edits.append((chat, msg, text)) or True
        b.api = lambda method, **p: self.answers.append(p.get("text"))
        b.now = lambda: datetime(2026, 10, 15, 21, 50, tzinfo=b.TZ)
    def night(self, d, w, status="done", msg=None):
        self.db.execute("INSERT INTO nights(day, walker, status, msg) VALUES(?,?,?,?)", (d.isoformat(), w, status, msg))
    def off(self, u, d): self.db.execute("INSERT INTO off VALUES(?,?)", (u, d.isoformat()))
    def plan(self, n=7): return [w for _, w in b.week(self.db, T)][:n]
    def tap(self, uid, data, msg=1):
        b.on_button(self.db, {"id": "q", "from": {"id": uid}, "data": data,
                              "message": {"chat": {"id": uid}, "message_id": msg}})
    def text(self, uid, text):
        b.on_text(self.db, {"from": {"id": uid}, "chat": {"type": "private"}, "text": text})
    def dogs(self): return [x for x in self.sent if "🐕" in x[1]]
    def at(self, d, h, m=0): return datetime(d.year, d.month, d.day, h, m, tzinfo=b.TZ)

class Rotation(Base):
    def test_alternation(self):
        self.assertEqual(self.plan(), [1, 2, 1, 2, 1, 2, 1])
        self.night(D(14), 1)
        self.assertEqual(b.pick(self.db, T), 2)  # covering counts as a turn
    def test_off_days(self):
        self.off(2, D(16))
        self.assertEqual(self.plan(3), [1, 1, 2])
    def test_both_off_fewer_walks(self):
        self.night(D(12), 2); self.night(D(13), 2); self.night(D(14), 1)
        self.off(1, T); self.off(2, T)
        self.assertEqual(b.pick(self.db, T), 1)
    def test_nobody_night_skipped(self):
        self.night(D(14), 1); self.night(T, None, "nobody")
        self.assertEqual(b.week(self.db, T)[1][1], 2)
    def test_override_beats_off(self):
        self.off(1, T); b.apply_claim(self.db, 1, [T])
        self.assertEqual(b.pick(self.db, T), 1)

class Round4(Base):
    def test_tap_survives_failed_answer(self):
        self.night(T, 1, "on", 1)
        def api(method, **p):
            if method == "answerCallbackQuery": raise OSError("query too old")
        b.api = api
        self.tap(1, "done")
        self.assertEqual(b.night(self.db, T)["status"], "done")
    def test_ask_network_error_says_retry(self):
        b.send = lambda chat, text, markup=None: None
        self.tap(1, "nswap:2026-10-16:0")
        self.assertEqual(self.answers[-1], "couldn't reach Christian, try again")
    def test_429_waits_once(self):
        import io, urllib.error
        slept, calls = [], []
        def api(method, **p):
            calls.append(1)
            raise urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b'{"parameters": {"retry_after": 30}}'))
        for k in ("RETRY",): self.addCleanup(setattr, b, k, getattr(b, k))
        self.addCleanup(setattr, b.time, "sleep", b.time.sleep)
        b.api, b.send, b.time.sleep = api, Base.real_send, slept.append
        self.assertIsNone(b.send(1, "x"))
        self.assertEqual((len(calls), slept[-1]), (1, 10))
    def test_cross_month_ranges(self):
        r = b.parse_days("weg 30 dec - 2 jan", T)
        self.assertEqual((r[0], r[-1], len(r)), (date(2026, 12, 30), date(2027, 1, 2), 4))
        r = b.parse_days("not 28-3 jan", T)
        self.assertEqual((r[0], r[-1], len(r)), (date(2026, 12, 28), date(2027, 1, 3), 7))
    def test_long_unclear_is_huh(self):
        self.text(1, "20-30 oct")
        self.assertEqual(self.sent[-1][1], 'didn\'t get that, try "not fri"')
    def test_preview_months_when_spanning(self):
        b.now = lambda: self.at(date(2026, 10, 25), 12)
        self.text(1, "not 31 oct - 1 nov")
        self.assertEqual(self.sent[-1][1], "off: Sat 31 Oct, Sun 1 Nov")
    def test_two_weeks_max(self):
        self.text(1, "away 30 oct")
        self.assertEqual(self.sent[-1][1], "max 2 weeks ahead")
        self.tap(1, "noff:2026-10-29:1")
        self.assertEqual((self.answers[-1], b.is_off(self.db, 1, D(29))), ("that one's old", False))
    def test_lock_single_instance(self):
        import fcntl, tempfile
        path = tempfile.mktemp()
        self.addCleanup(setattr, b, "LOCK", b.LOCK); self.addCleanup(setattr, b, "TOKEN", b.TOKEN)
        b.LOCK, b.TOKEN = path, "x"
        held = open(path, "a+"); fcntl.flock(held, fcntl.LOCK_EX)
        with self.assertRaises(SystemExit) as e: b.run()
        self.assertEqual(e.exception.code, 3)
        held.close()

class Dishes(Base):
    def test_dishes_rule(self):
        self.assertEqual(b.dishes(self.db, T, 1), 2)
        self.off(2, T); self.assertEqual(b.dishes(self.db, T, 1), 1)  # off counts for both chores
        self.off(1, T); self.assertEqual(b.dishes(self.db, T, 1), 2)  # both off: dishes to the other
    def test_dishes_message_at_1830(self):
        b.tick(self.db, self.at(T, 18, 29)); self.assertEqual(self.sent, [])
        b.tick(self.db, self.at(T, 18, 30))
        self.assertEqual(self.sent, [(2, "🍽 dishes are yours tonight")])
    def test_both_off_note(self):
        self.off(1, T); self.off(2, T)
        b.tick(self.db, self.at(T, 18, 30))
        self.assertEqual(self.sent[-1][1], "🍽 dishes are yours tonight\nyou're both off, so dishes are yours")
    def dish_night(self, w=2, msg=5):
        self.db.execute("INSERT INTO nights(day, chore, walker, status, msg) VALUES(?,?,?,?,?)",
                        (T.isoformat(), "dishes", w, "on", msg))
    def test_done_no_parent_ping(self):
        self.dish_night()
        b.now = lambda: self.at(T, 20, 10)
        self.tap(2, "done:dishes", msg=5)
        self.assertEqual((b.night(self.db, T, "dishes")["status"], self.edits[-1][2], self.sent), ("done", "✅ done 20:10", []))
    def test_cant_passes_only_dishes(self):
        self.dish_night(); self.night(T, 1, "on", 7)
        b.now = lambda: self.at(T, 20, 0)
        self.tap(2, "cant:dishes", msg=5)
        self.assertEqual(self.sent[-1], (1, "🍽 Christian can't, dishes are yours"))
        self.assertEqual((b.night(self.db, T, "dishes")["walker"], b.night(self.db, T)["walker"]), (1, 1))
    def test_cant_until_21(self):
        self.dish_night()
        b.now = lambda: self.at(T, 21, 0)
        self.tap(2, "cant:dishes", msg=5)
        self.assertEqual(self.answers[-1], "too late to pass, sort it irl aha")
    def test_late_alert_once_with_cover(self):
        self.dish_night()
        b.tick(self.db, self.at(T, 21, 1)); b.tick(self.db, self.at(T, 21, 2))
        self.assertEqual(self.sent.count((3, "dishes still not done")), 1)
        self.tap(3, "pcover:dishes:" + T.isoformat(), msg=60)
        self.assertEqual(b.night(self.db, T, "dishes")["status"], "parent")
        self.assertIn((1, "Mum's got the dishes tonight"), self.sent)
    def test_swap_trades_both(self):
        self.tap(1, "nswap:2026-10-16:0"); self.tap(2, "accept", msg=100 + len(self.sent))
        self.assertEqual((b.owner(self.db, D(16), T), b.dishes(self.db, D(16), 1)), (1, 2))
    def test_migration(self):
        import sqlite3, tempfile
        path = tempfile.mktemp()
        old = sqlite3.connect(path)
        old.executescript("CREATE TABLE nights(day TEXT PRIMARY KEY, walker INTEGER, status TEXT, cant TEXT DEFAULT '', "
                          "msg INTEGER, done_at TEXT); INSERT INTO nights(day, walker, status) VALUES('2026-10-01', 1, 'done');"
                          "CREATE TABLE overrides(day TEXT PRIMARY KEY, walker INTEGER); INSERT INTO overrides VALUES('2026-10-20', 2);")
        old.commit(); old.close()
        db = b.connect(path)
        self.assertEqual(tuple(db.execute("SELECT chore, walker FROM nights").fetchone()), ("dogs", 1))
        self.assertEqual(tuple(db.execute("SELECT chore, walker FROM overrides").fetchone()), ("dogs", 2))
        db.close()

class OneOff(Base):
    def test_both_chore_overrides_give_one_person_both(self):
        for chore in ("dogs", "dishes"): b.apply_claim(self.db, 1, [D(16)], chore)
        dog = b.owner(self.db, D(16), T)
        self.assertEqual((dog, b.dishes(self.db, D(16), dog), b.owner(self.db, D(17), T)), (1, 1, 2))

class Round8(Base):
    def test_claim_clears_dishes_pin(self):
        b.apply_claim(self.db, 1, [D(16)], "dishes")
        b.apply_claim(self.db, 1, [D(16)])
        self.assertEqual(b.dishes(self.db, D(16), 1), 2)
    def test_ignored_messages(self):
        for extra in ({"sticker": {}}, {"text": "not fri", "forward_origin": {}}):
            b.on_text(self.db, {"from": {"id": 1}, "chat": {"type": "private"}, **extra})
        self.assertEqual(self.sent, [])
    def test_malformed_callback(self):
        for data in ("wk:garbage", "wp:x", "pcover:dogs:notadate"):
            self.tap(1, data)
            self.assertEqual(self.answers[-1], "that one's old")
    def test_property_random_sequences(self):
        """300 seeded runs of off/claim/swap/decline/Can't/Done/tick over several days.
        A chore row is history once it's settled or past its Can't cutoff; everything else must hold."""
        import random
        sent = {}
        def send(chat, text, markup=None):
            sent[len(sent) + 1000] = (chat, markup); return len(sent) + 999
        b.send = send
        for seed in range(300):
            rng, db = random.Random(seed), self.db
            for table in ("nights", "overrides", "off", "kv"): db.execute(f"DELETE FROM {table}")
            clock = [datetime(2026, 10, 20, 18, tzinfo=b.TZ)]
            b.now = lambda: clock[0]
            for step in range(30):
                clock[0] += b.timedelta(minutes=rng.choice((5, 20, 60, 180)))
                t, u, op = clock[0], rng.choice((1, 2)), rng.choice("ocswxdtie")
                today = t.date(); d = today + b.timedelta(days=rng.randrange(4))
                if op == "o": b.confirm_off(db, u, [d])
                elif op == "c": b.confirm_walk(db, u, [d])
                elif op in "ie": self.tap(u, ("nin:" if op == "i" else "ntake:") + f"{d}:0")
                elif op in "sw":
                    before = max(sent, default=0)
                    b.on_night_action(db, u, "nswap", d, u, 5, lambda *a, **k: None, 0)
                    asks = [(m, c) for m, (c, mk) in sent.items() if m > before and "accept" in str(mk)]
                    if asks:
                        m, c = asks[-1]
                        self.tap(c, "accept" if op == "s" else "no", msg=m)
                elif op in "xd":
                    for chore in b.CHORES:
                        n = b.night(db, today, chore)
                        if n and n["walker"] and n["msg"]:
                            self.tap(n["walker"], ("cant:" if op == "x" else "done:") + chore, msg=n["msg"])
                b.tick(db, t)
                for day, dog in b.week(db, today):
                    own = {}
                    for chore, planned in (("dogs", dog), ("dishes", b.dishes(db, day, dog))):
                        n = b.night(db, day, chore)
                        live = not n or (n["status"] == "on" and b.can_pass(day, t, chore) and not n["cant"])
                        own[chore] = (n["walker"] if n else planned, live)
                        if live: self.assertIn(own[chore][0], (1, 2), (seed, step, day, chore))
                    offs = [w for w in (1, 2) if b.is_off(db, w, day)]
                    (dw, dl), (sw, sl) = own["dogs"], own["dishes"]
                    if dl and sl and dw == sw and len(offs) != 2:
                        self.assertEqual(len(offs), 1, (seed, step, day, "same person, nobody off"))
                        self.assertNotIn(dw, offs, (seed, step, day, "off walker holds both"))
                    if len(offs) == 1:
                        for chore, (w, live) in own.items():
                            if live: self.assertNotIn(w, offs, (seed, step, day, chore, "off walker owns"))

class Round7(Base):
    def test_join_lists(self):
        self.addCleanup(setattr, b, "WALKER_IDS", b.WALKER_IDS)
        self.addCleanup(setattr, b, "PARENT_IDS", b.PARENT_IDS)
        b.WALKER_IDS, b.PARENT_IDS = [5], [8]
        db = b.connect(":memory:")
        b.on_start(db, {"id": 9, "first_name": "Gran"}, "")
        self.assertEqual(self.sent[-1], (9, "this bot's private"))  # on neither list
        b.on_start(db, {"id": 8, "first_name": "Mum"}, "parent_abc")  # old link args are ignored
        b.on_start(db, {"id": 5, "first_name": "M"}, "")
        self.assertEqual((b.role_of(db, 5), b.role_of(db, 8)), ("walker", "parent"))
        b.on_start(db, {"id": 8, "first_name": "Mum"}, "")
        self.assertEqual(self.sent[-1], (8, "you're already in, /week shows the plan"))
    def test_unknown_commands(self):
        self.text(2, "/nope"); self.text(2, "/foo"); self.text(3, "/bar")
        self.assertEqual([x[1] for x in self.sent], ["/week · /lang"] * 3)
    def test_walker_welcome(self):
        db = b.connect(":memory:")
        self.addCleanup(setattr, b, "WALKER_IDS", b.WALKER_IDS)
        b.WALKER_IDS = [5]
        b.on_start(db, {"id": 5, "first_name": "M"}, "")
        self.assertIn("dishes 18:30, dogs 21:45,", self.sent[-1][1])
        self.assertLessEqual(self.sent[-1][1].count("\n"), 5)

class Round6(Base):
    def test_both_off_note_not_on_pass(self):
        self.off(1, T); self.off(2, T); self.night(T, 1, "on", 1)
        self.tap(1, "cant")
        self.assertEqual(self.sent[-1], (2, "🐕 Michael can't, dogs are yours"))
    def test_old_done_callback_is_dogs(self):
        self.night(T, 1, "on", 1)
        self.tap(1, "done")
        self.assertEqual(b.night(self.db, T)["status"], "done")

class Round5(Base):
    def test_run_drains_before_tick(self):
        import tempfile
        order = []
        for k in ("tick", "connect", "LOCK", "TOKEN"): self.addCleanup(setattr, b, k, getattr(b, k))
        def api(method, **p):
            if method == "getMe": return {"username": "u"}
            order.append(("poll", p.get("timeout")))
            if len(order) > 2: raise SystemExit
            return []
        b.api, b.connect, b.LOCK, b.TOKEN = api, lambda: self.db, tempfile.mktemp(), "x"
        b.tick = lambda db, t: order.append(("tick", None))
        with self.assertRaises(SystemExit): b.run()
        self.assertEqual(order[:3], [("poll", 0), ("tick", None), ("poll", 25)])
    def test_cant_other_blocked(self):
        self.night(T, 1, "on", 1)
        b.send = lambda chat, text, markup=None: False if chat == 2 else self.sent.append((chat, text)) or 9
        self.tap(1, "cant")
        self.assertEqual(self.answers[-1], "can't reach Christian")
        self.assertIn((3, "can't reach Christian"), self.sent)
        self.assertEqual(b.night(self.db, T)["walker"], 1)
    def test_crash_answers_with_error(self):
        self.addCleanup(setattr, b, "handle_button", b.handle_button)
        def boom(*a): raise RuntimeError("x")
        b.handle_button = boom
        with self.assertRaises(RuntimeError): self.tap(1, "done")
        self.assertEqual(self.answers[-1], "oops, try again")
    def test_prune_late_keys(self):
        b.kv(self.db, "late_dogs_2026-10-10", "1"); b.kv(self.db, "late_dogs_2026-10-14", "1")
        b.prune(self.db, self.at(T, 12))
        self.assertEqual([r[0] for r in self.db.execute("SELECT k FROM kv WHERE k LIKE 'late%'")], ["late_dogs_2026-10-14"])

class Week(Base):
    def test_day_colours(self):
        self.off(1, D(20))  # Michael off Tue 20, so Christian walks it
        days = {x["text"]: x.get("style") for r in b.week_view(self.db, T, uid=1)[1]["inline_keyboard"][:2] for x in r}
        self.assertEqual(days, {"thu 15": "success", "fri 16": None, "sat 17": "success", "sun 18": None,
                                "mon 19": "success", "tue 20": "danger", "wed 21": "success"})
    def test_view(self):
        text, kb = b.week_view(self.db, T, uid=1)
        self.assertEqual(text.split("\n")[:4], ["<b>week 15–21 oct</b>", "", "<b>thu 15  you</b>", "fri 16  Christian"])
        self.assertEqual(b.week_view(self.db, T, "nl", page=1)[0].split("\n")[0], "<b>week 22–28 okt</b>")
        k = kb["inline_keyboard"]
        self.assertEqual(([len(r) for r in k], k[0][1]), ([4, 3, 1], {"text": "fri 16", "callback_data": "wk:2026-10-16:0"}))
        self.assertEqual(k[2][0]["callback_data"], "wp:1")
        self.assertEqual(b.week_view(self.db, T, page=1)[1]["inline_keyboard"][2][0]["callback_data"], "wp:0")
    def test_marks(self):
        self.off(2, D(16))
        self.tap(1, "nswap:2026-10-17:0")
        lines = b.week_view(self.db, T, "nl", uid=2)[0].split("\n")[2:5]
        self.assertEqual(lines, ["<b>do 15  Michael</b>", "vr 16  Michael 🚫", "za 17  ⇄ jij"])
    def test_one_walker(self):
        self.db.execute("DELETE FROM members WHERE id=2")
        self.assertEqual(b.week_view(self.db, T, uid=1)[0].split("\n")[1], "<i>other walker's not in yet, you've got both</i>")
    def test_week_message_tracked_and_refreshed(self):
        self.text(1, "/week")
        m = 100 + len(self.sent)
        b.confirm_off(self.db, 1, [D(17)])
        b.refresh_weeks(self.db)
        self.assertEqual(self.edits[-1][:2], (1, m))
        self.assertIn("🚫", self.edits[-1][2])
        n = len(self.edits); b.refresh_weeks(self.db)
        self.assertEqual(len(self.edits), n)  # unchanged: no edit
        b.edit = lambda *a, **k: False  # user deleted it
        b.confirm_off(self.db, 1, [D(18)]); b.refresh_weeks(self.db)
        self.assertIsNone(self.db.execute("SELECT * FROM weekmsg").fetchone())
    def test_paging(self):
        self.tap(1, "wp:1")
        self.assertTrue(self.edits[-1][2].startswith("<b>week 22–28 oct</b>"))
        self.tap(1, "wp:9")
        self.assertTrue(self.edits[-1][2].startswith("<b>week 22–28 oct</b>"))
    def test_nobody_night_taken_directly(self):
        self.night(T, None, "nobody")
        self.tap(1, "ntake:2026-10-15:0")
        self.assertEqual((self.answers[-1], self.sent), ("Thu 15's yours", []))
        self.assertEqual(b.night(self.db, T)["walker"], 1)
    def test_no_swap_after_23(self):
        b.now = lambda: self.at(T, 23, 5)
        self.tap(1, "nswap:2026-10-15:0")
        self.assertEqual((self.answers[-1], self.sent), ("too late to pass, sort it irl aha", []))
    def test_swap_expires_when_owner_changes(self):
        self.tap(1, "nswap:2026-10-16:0")
        m = 100 + len(self.sent)
        b.apply_claim(self.db, 1, [D(16)])  # Fri changed hands meanwhile
        self.tap(2, "accept", msg=m)
        self.assertEqual(self.answers[-1], "that one's old")
    def test_swap_expires_at_night_start_and_pruned(self):
        self.tap(2, "nswap:2026-10-15:0")
        b.tick(self.db, self.at(T, 23, 1))
        self.assertEqual(b.all_pending(self.db), [])
    def test_swap_accepted(self):
        self.tap(1, "nswap:2026-10-16:0")  # Christian's Fri, Michael wants it
        self.assertEqual((self.answers[-1], self.sent[-1]), ("asked Christian", (2, "Michael wants your Fri 16")))
        self.assertEqual(self.plan(2)[1], 2)  # nothing changes until accepted
        self.tap(2, "accept", msg=100 + len(self.sent))
        self.assertEqual(self.plan(), [1, 1, 2, 1, 2, 1, 2])
        self.assertIn((1, "👍 Christian said yes, Fri 16 goes to Michael"), self.sent)
    def test_swap_declined(self):
        self.tap(1, "nswap:2026-10-15:0")
        self.assertEqual(self.sent[-1], (2, "Michael asks: can you take Thu 15?"))
        self.tap(2, "no", msg=100 + len(self.sent))
        self.assertEqual((self.plan(1), self.sent[-1]), ([1], (1, "Christian said no to Thu 15")))
    def test_swap_moves_live_message(self):
        self.night(T, 1, "on", 7)
        self.tap(1, "nswap:2026-10-15:0"); self.tap(2, "accept", msg=100 + len(self.sent))
        self.assertIn((1, 7, "passed to Christian"), self.edits)
        self.assertEqual(self.sent[-2], (2, "🐕 dogs are yours tonight"))
    def test_old_button(self):
        self.tap(1, "nswap:2026-10-14:0")
        self.assertEqual(self.answers, ["that one's old"])

class Night(Base):
    def test_done(self):
        self.night(T, 1, "on", 1)
        self.tap(1, "done")
        self.assertEqual(self.edits[-1][2], "✅ walked 21:50")
        self.assertIn((3, "✅ dogs are out, Michael (21:50)"), self.sent)
    def test_windows(self):
        self.assertTrue(b.can_pass(T, self.at(T, 22, 59)))
        self.assertFalse(b.can_pass(T, self.at(T, 23)))
        self.assertTrue(b.done_open(T, self.at(D(16), 2, 59)))
        self.assertFalse(b.done_open(T, self.at(D(16), 3)))
    def test_too_late_to_pass(self):
        self.night(T, 1, "on", 1)
        b.now = lambda: self.at(T, 23, 10)
        self.tap(1, "cant")
        self.assertEqual(self.answers, ["too late to pass, sort it irl aha"])
    def test_cant(self):
        self.night(T, 1, "on", 1)
        self.tap(1, "cant")
        self.assertEqual(self.sent[-1], (2, "🐕 Michael can't, dogs are yours"))
        self.tap(2, "cant", msg=101)
        self.assertIn((3, "no one's free for the dogs tonight"), self.sent)
    def test_send_once_in_window(self):
        b.tick(self.db, self.at(T, 21, 40))
        self.assertEqual(self.dogs(), [])
        b.tick(self.db, self.at(T, 22, 30)); b.tick(self.db, self.at(T, 22, 31))  # restart mid-evening
        self.assertEqual(self.dogs(), [(1, "🐕 dogs are yours tonight")])
    def test_down_all_evening(self):
        b.tick(self.db, self.at(T, 23, 5))
        self.assertEqual(self.sent, [(3, "dogs not done yet"), (3, "dishes still not done")])  # no walker messages
    def test_transient_failure_retries_next_tick(self):
        b.send = lambda chat, text, markup=None: None
        b.tick(self.db, self.at(T, 21, 45))
        self.assertIsNone(b.night(self.db, T)["msg"])
        b.send = lambda chat, text, markup=None, **k: self.sent.append((chat, text)) or 300
        b.tick(self.db, self.at(T, 21, 46))
        self.assertEqual(self.dogs(), [(1, "🐕 dogs are yours tonight")])
    def test_off_tonight_passes_live_message(self):
        self.night(T, 1, "on", 7)
        self.text(1, "not tonight"); self.tap(1, "confirm", msg=100 + len(self.sent))
        self.assertIn((1, 7, "passed to Christian"), self.edits)
        self.assertEqual(b.night(self.db, T)["walker"], 2)
    def test_resend_if_crashed_before_sent(self):
        self.night(T, 1, "on")  # row written, msg never sent
        b.tick(self.db, self.at(T, 22, 0))
        self.assertEqual(self.dogs(), [(1, "🐕 dogs are yours tonight")])
    def test_unreachable_walker(self):
        b.send = lambda chat, text, markup=None: False if chat == 1 else self.sent.append((chat, text)) or 200
        b.tick(self.db, self.at(T, 21, 45))
        self.assertIn((3, "can't reach Michael"), self.sent)
        self.assertIn((2, "🐕 can't reach Michael, dogs are yours"), self.sent)
        self.assertEqual(b.week(self.db, T)[0][1], 2)
    def test_send_retries(self):
        calls = []
        def flaky(method, **p):
            calls.append(1)
            if len(calls) < 3: raise OSError("net")
            return {"message_id": 5}
        self.addCleanup(setattr, b, "RETRY", b.RETRY)
        b.api, b.RETRY, b.send = flaky, (0, 0, 0, 0), Base.real_send
        self.assertEqual((b.send(1, "x"), len(calls)), (5, 3))
    def test_only_403_is_unreachable(self):
        import urllib.error
        def fail(code):
            def f(method, **p): raise urllib.error.HTTPError("u", code, "x", {}, None)
            return f
        self.addCleanup(setattr, b, "RETRY", b.RETRY)
        b.RETRY, b.send = (0, 0), Base.real_send
        b.api = fail(403); self.assertIs(b.send(1, "x"), False)
        b.api = fail(502); self.assertIsNone(b.send(1, "x"))
    def test_cant_network_error_keeps_night(self):
        self.night(T, 1, "on", 1)
        b.send = lambda chat, text, markup=None: None
        self.tap(1, "cant")
        n = b.night(self.db, T)
        self.assertEqual((self.answers, n["walker"], n["status"], n["cant"]), (["couldn't reach Christian, try again"], 1, "on", ""))
    def test_tick_errors_dont_crash(self):
        b.TOKEN, calls = "x", []
        self.addCleanup(setattr, b, "TOKEN", "")
        def boom(db, t): raise RuntimeError("x")
        def api(method, **p):
            calls.append(method)
            if method == "getMe": return {"username": "u"}
            if len(calls) > 3: raise SystemExit
            return []
        for k in ("tick", "connect", "LOCK"): self.addCleanup(setattr, b, k, getattr(b, k))
        import tempfile; b.LOCK = tempfile.mktemp()
        b.tick, b.api, b.connect = boom, api, lambda: self.db
        with self.assertRaises(SystemExit): b.run()
        self.assertGreater(calls.count("getUpdates"), 1)
    def test_missed_yesterday_once(self):
        self.db.execute("UPDATE members SET joined=joined-86400*3")
        b.tick(self.db, self.at(T, 10)); b.tick(self.db, self.at(T, 11))
        self.assertEqual(self.sent.count((3, "bot was down last night, nothing went out")), 1)
    def test_overdue_once(self):
        self.night(T, 1, "on", 1)
        self.assertIsNone(b.overdue(self.db, self.at(T, 22, 30)))
        b.tick(self.db, self.at(T, 23, 1)); b.tick(self.db, self.at(T, 23, 2))
        self.assertEqual(self.sent.count((3, "dogs not done yet")), 1)
    def test_parent_cover(self):
        self.night(T, 1, "on", 7)
        self.tap(3, "pcover:" + T.isoformat(), msg=50)
        self.assertIn((1, 7, "Mum's got it"), self.edits)
        self.assertIn((2, "Mum's got the dogs tonight"), self.sent)
        self.tap(3, "pcover:" + T.isoformat(), msg=50)
        self.assertEqual((self.answers[-1], self.edits[-1][2]), ("already sorted", "already sorted"))

class Chat(Base):
    def last(self): return 100 + len(self.sent)
    def test_off_day_preview(self):
        self.text(2, "not fri")
        self.assertEqual(self.sent[-1], (2, "off: Fri 16"))
        self.assertEqual(self.plan(2)[1], 2)  # not saved yet
        self.tap(2, "confirm", msg=self.last())
        self.assertEqual((self.edits[-1][2], self.plan(2)[1]), ("👍 saved", 1))
    def test_claim_confirm(self):
        self.off(2, D(18))
        self.text(1, "he does the weekend")
        self.assertEqual(self.sent[-1][1], "Christian walks: Sat 17, Sun 18")
        self.tap(1, "confirm", msg=self.last())
        self.assertEqual(self.sent[-1], (2, "Michael asks: can you take Sat 17?"))  # Sun skipped, he's off
        self.assertEqual(self.plan(3)[2], 1)  # nothing until he accepts
        self.tap(2, "accept", msg=self.last())
        self.assertEqual(self.plan(3)[2], 2)
    def test_unclear_asks(self):
        self.text(1, "fri")
        self.assertEqual(self.sent[-1][1], "Fri 16: off or walking?")
        m = self.last()
        self.tap(1, "walk", msg=m)
        self.assertEqual(self.edits[-1][2], "Michael walks: Fri 16")
        self.tap(1, "confirm", msg=m)
        self.assertEqual(self.plan(2), [1, 1])
    def test_intent(self):
        i = lambda s: b.intent(s, 1, 2, "Christian")
        self.assertEqual([i("I can do mon but not tue"), i("ik kan vrijdag wel lopen"), i("kan vrijdag")],
                         [(None, None)] * 3)
        self.assertEqual([i("kan niet vrijdag"), i("he does sat"), i("I do mon")], [("off", 1), ("walk", 2), ("walk", 1)])
        self.assertEqual(b.parse_days("vrij", T), [])
    def test_mixed_asks_per_day(self):
        self.text(1, "I can do mon but not tue")
        m = self.last()
        self.assertEqual(self.sent[-1][1], "Mon 19: off or walking?")
        self.tap(1, "walk", msg=m)
        self.assertEqual(self.edits[-1][2], "Tue 20: off or walking?")
        self.tap(1, "off", msg=m)
        self.assertEqual(self.edits[-1][2], "off: Tue 20\nMichael walks: Mon 19")
    def test_cancel_then_stale(self):
        self.text(1, "ik doe vrijdag")
        m = self.last()
        self.tap(1, "cancel", msg=m)
        self.assertEqual((self.edits[-1][2], self.plan(2)[1]), ("cancelled", 2))
        self.tap(1, "confirm", msg=m)
        self.assertEqual(self.answers[-1], "that one's old")
    def test_parent_join(self):
        self.addCleanup(setattr, b, "PARENT_IDS", b.PARENT_IDS)
        b.PARENT_IDS = [9]
        b.on_start(self.db, {"id": 9, "first_name": "Dad"}, "")
        self.assertIn((9, b.tr("en", "hi_parent")), self.sent)
        self.assertIn((1, "Dad joined"), self.sent)
        self.assertNotIn((3, "Dad joined"), self.sent)  # parents don't hear about parents
    def test_invite_is_gone(self):
        self.text(1, "/invite")  # just an unknown command now
        self.assertEqual(self.sent[-1], (1, "/week · /lang"))

class Language(Base):
    def test_toggle_and_dutch(self):
        self.text(2, "/lang")
        self.tap(2, "lang:nl")
        self.assertEqual(self.edits[-1][2], "Taal")
        self.text(2, "kan niet vrijdag")  # parser stays bilingual
        self.assertEqual(self.sent[-1], (2, "kan niet: Vr 16"))
    def test_bad_lang_falls_back(self):
        self.tap(2, "lang:xx")
        self.assertEqual((b.lang_of(self.db, 2), self.edits[-1][2]), ("en", "Language"))
    def test_both_off_note_needs_two_walkers(self):
        self.db.execute("DELETE FROM members WHERE id=2"); self.off(1, T)
        b.say_on(self.db, 1, T.isoformat(), "dogs")
        self.assertNotIn("both off", self.sent[-1][1])
    def test_night_menu(self):
        marks = []
        b.edit = lambda chat, msg, text, markup=None, **k: (self.edits.append((chat, msg, text)), marks.append(markup))
        self.tap(1, "wk:2026-10-16:0")  # Michael's night: off / swap / back
        kb = marks[-1]["inline_keyboard"]
        self.assertEqual([[x["callback_data"] for x in r] for r in kb], [["noff:2026-10-16:0", "nswap:2026-10-16:0"], ["wp:0"]])
        self.assertEqual([x["style"] for x in kb[0]], ["danger", "primary"])
        self.tap(1, "noff:2026-10-16:0")
        self.assertEqual((self.answers[-1], b.is_off(self.db, 1, D(16)), self.edits[-1][2]), ("👍 saved", True, b.week_view(self.db, T, uid=1)[0]))
        self.tap(1, "wk:2026-10-16:0")
        self.assertEqual(marks[-1]["inline_keyboard"][0][0]["callback_data"], "nin:2026-10-16:0")
        self.tap(1, "nin:2026-10-16:0")
        self.assertFalse(b.is_off(self.db, 1, D(16)))
    def test_take_needs_empty_night(self):
        d = next(d for d, w in b.week(self.db, T) if w == 2)
        self.tap(1, f"ntake:{d}:0")  # Christian's night: no taking without his yes
        self.assertEqual(b.owner(self.db, d, T), 2)
    def test_plan_button(self):
        self.assertEqual(len(b.chore_buttons(self.db, 1, "dogs")["inline_keyboard"]), 2)  # reminders: done and can't, one per row
        self.tap(1, "plan")
        self.assertTrue(self.sent[-1][1].startswith("<b>week 15–21 oct</b>"))
        self.assertTrue(all(len(x["callback_data"].encode()) <= 64 for r in b.week_view(self.db, T)[1]["inline_keyboard"] for x in r))
    def test_button_colours(self):
        k = [r[0] for r in b.chore_buttons(self.db, 1, "dogs")["inline_keyboard"]]
        self.assertEqual([(x["callback_data"], x["style"]) for x in k], [("done:dogs", "success"), ("cant:dogs", "danger")])
        self.assertEqual(b.plan_button("en")["style"], "primary")
        self.assertNotIn("style", b.buttons(self.db, 1, "cancel")["inline_keyboard"][0][0])  # neutral stays neutral
        self.assertEqual(b.buttons(self.db, 1, "confirm", "cancel")["inline_keyboard"][0][0]["style"], "success")
    def test_word_date_range(self):
        for s in ("away 20 to 27 oct", "away 20-27 oct", "weg 20 t/m 27 okt"):
            d = b.parse_days(s, date(2026, 10, 15))
            self.assertEqual((d[0], d[-1], len(d)), (date(2026, 10, 20), date(2026, 10, 27), 8), s)
    def test_strings_complete(self):
        for key, pair in b.S.items():
            if isinstance(pair, str): pair = (pair,)
            else: self.assertEqual(len(pair), 2, key)
            for s in pair: self.assertNotIn("—", s, key)

if __name__ == "__main__":
    unittest.main()
