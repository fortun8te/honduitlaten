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
    def schedule_snapshot(self):
        return {table: [tuple(row) for row in self.db.execute(f"SELECT * FROM {table} ORDER BY 1,2")]
                for table in ("off", "overrides", "nights")}
    def request_swap(self, uid, day):
        """Explicit initiator review/confirm; deliberately does not accept for the recipient."""
        before, sent_before = self.schedule_snapshot(), len(self.sent)
        self.tap(uid, f"nswap:{day}:0")
        self.assertEqual(self.schedule_snapshot(), before)
        self.assertTrue(all(chat == uid for chat, _ in self.sent[sent_before:]))
        previews = [(key, data) for key, data in b.all_pending(self.db)
                    if key.startswith(f"p_{uid}_") and data.get("type") == "request_preview" and data["day"] == str(day)]
        self.assertTrue(previews, "Initiator must see a private request preview")
        self.tap(uid, "request_confirm", int(previews[-1][0].rsplit("_", 1)[1]))
        self.assertEqual(self.schedule_snapshot(), before, "Sending a request must not change the plan")
        requests = [(key, data) for key, data in b.all_pending(self.db)
                    if data.get("type") == "swap" and data["from"] == uid and str(day) in data["owners"]]
        self.assertTrue(requests)
        key = requests[-1][0].split("_")
        return int(key[1]), int(key[2])
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
    def test_both_off_never_assigns_unavailable_walkers(self):
        self.night(D(12), 2); self.night(D(13), 2); self.night(D(14), 1)
        self.off(1, T); self.off(2, T)
        self.assertIsNone(b.pick(self.db, T))
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
        self.tap(1, "nswap:2026-10-16:0")
        msg = 100 + len(self.sent)
        b.send = lambda chat, text, markup=None: None
        self.tap(1, "request_confirm", msg)
        self.assertEqual(self.answers[-1], "couldn't reach Christian, try again")
        self.assertEqual(b.peek_pending(self.db, 1, msg)["type"], "request_preview")
        self.assertEqual(self.plan(2)[1], 2)
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
        self.text(1, "20-28 oct")
        self.assertEqual(self.sent[-1][1], b.tr("en", "huh"))
    def test_range_crossing_planning_horizon_is_not_partially_saved(self):
        self.text(1, "away 10-16 nov")
        self.assertEqual(self.sent[-1][1], b.tr("en", "too_far"))
        self.assertEqual(b.all_pending(self.db), [])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM off").fetchone()[0], 0)
    def test_preview_months_when_spanning(self):
        b.now = lambda: self.at(date(2026, 10, 25), 12)
        self.text(1, "not 31 oct - 1 nov")
        self.assertIn("Sat 31 Oct, Sun 1 Nov", self.sent[-1][1])
        self.assertFalse(b.is_off(self.db, 1, date(2026, 10, 31)))
    def test_month_planning_limit(self):
        self.text(1, "away 15 nov")
        self.assertEqual(self.sent[-1][1], b.tr("en", "too_far"))
        self.tap(1, "noff:2026-11-15:4")
        self.assertEqual((self.answers[-1], b.is_off(self.db, 1, date(2026, 11, 15))), (b.tr("en", "old"), False))
    def test_lock_single_instance(self):
        import fcntl, tempfile
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = folder.name + "/run.lock"
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
        self.assertEqual(self.sent[-1], (3, b.tr("en", "nobody_parents_dishes")))
        self.assertEqual(b.night(self.db, T, "dishes")["status"], "nobody")
        self.assertIsNone(b.night(self.db, T, "dishes")["walker"])
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
        self.assertEqual(self.sent.count((3, b.tr("en", "late_dishes"))), 1)
        self.tap(3, "pcover:dishes:" + T.isoformat(), msg=60)
        self.assertEqual(b.night(self.db, T, "dishes")["status"], "parent")
        self.assertIn((1, "Mum's got the dishes tonight"), self.sent)
    def test_swap_trades_both(self):
        recipient, request = self.request_swap(1, D(16))
        self.tap(recipient, "accept", msg=request)
        self.assertEqual((b.owner(self.db, D(16), T), b.dishes(self.db, D(16), 1)), (1, 2))
    def test_migration(self):
        import sqlite3, tempfile
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = folder.name + "/old.db"
        old = sqlite3.connect(path)
        old.executescript("CREATE TABLE nights(day TEXT PRIMARY KEY, walker INTEGER, status TEXT, cant TEXT DEFAULT '', "
                          "msg INTEGER, done_at TEXT); INSERT INTO nights(day, walker, status) VALUES('2026-10-01', 1, 'done');"
                          "CREATE TABLE overrides(day TEXT PRIMARY KEY, walker INTEGER); INSERT INTO overrides VALUES('2026-10-20', 2);")
        old.commit(); old.close()
        db = b.connect(path)
        self.addCleanup(db.close)
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
            self.tap(3 if data.startswith("pcover") else 1, data)
            self.assertEqual(self.answers[-1], b.tr("en", "old"))
    def test_invite_note(self):
        self.addCleanup(setattr, b, "OWNER_ID", b.OWNER_ID)
        b.OWNER_ID = 1; b.kv(self.db, "bot", "u")
        self.text(1, "/invite")
        self.assertIn(b.tr("en", "family_links"), self.sent[-1][1])
    def test_property_random_sequences(self):
        """300 seeded runs of off/claim/swap/decline/Can't/Done/tick over several days.
        A chore row is history once it's settled or past its Can't cutoff; everything else must hold."""
        import random
        sent = {}
        def send(chat, text, markup=None, **kwargs):
            sent[len(sent) + 1000] = (chat, markup); return len(sent) + 999
        b.send = send
        counts = {key: 0 for key in ("availability", "claim", "request", "accept", "decline")}
        def owned_pending(uid, kind):
            return [(int(key.rsplit("_", 1)[1]), proposal) for key, proposal in b.all_pending(self.db)
                    if key.startswith(f"p_{uid}_") and proposal.get("type") == kind]
        def reply_to_request(uid, day, accept):
            matches = [(key, proposal) for key, proposal in b.all_pending(self.db)
                       if proposal.get("type") == "swap" and proposal["from"] == uid and str(day) in proposal["owners"]]
            if matches:
                key, proposal = matches[-1]
                recipient, message = map(int, key.split("_")[1:])
                self.assertTrue(b.swap_valid(self.db, proposal, b.now()))
                self.tap(recipient, "accept" if accept else "no", msg=message)
                if accept:
                    for day_text in proposal["owners"]:
                        self.assertEqual(b.owner(self.db, date.fromisoformat(day_text), b.now().date()), proposal["to"])
                self.assertIsNone(b.peek_pending(self.db, recipient, message))
                counts["accept" if accept else "decline"] += 1
        for seed in range(300):
            rng, db = random.Random(seed), self.db
            for table in ("nights", "overrides", "off", "kv", "outbox"): db.execute(f"DELETE FROM {table}")
            clock = [datetime(2026, 10, 20, 18, tzinfo=b.TZ)]
            b.now = lambda: clock[0]
            for step in range(30):
                clock[0] += b.timedelta(minutes=rng.choice((5, 20, 60, 180)))
                t, u, op = clock[0], rng.choice((1, 2)), rng.choice("ocswxdtie")
                today = t.date(); d = today + b.timedelta(days=rng.randrange(4))
                if op in "oi":
                    before = self.schedule_snapshot()
                    previous_messages = max(sent, default=0)
                    if op == "o": self.text(u, f"not {d.day} {b.month(d, 'en')}")
                    else: self.tap(u, f"nin:{d}:0")
                    self.assertEqual(self.schedule_snapshot(), before, (seed, step, "availability before confirm"))
                    reviews = [(message, proposal) for message, proposal in owned_pending(u, "availability")
                               if message > previous_messages]
                    if reviews:
                        message, proposal = reviews[-1]
                        self.assertEqual(proposal["stage"], "review")
                        self.assertTrue(all(chat == u for mid, (chat, _) in sent.items() if mid > previous_messages))
                        self.tap(u, "av:confirm", msg=message)
                        if b.peek_pending(db, u, message) is None: counts["availability"] += 1
                elif op == "c":
                    before = self.schedule_snapshot()
                    previous_messages = max(sent, default=0)
                    self.text(u, f"I do {d.day} {b.month(d, 'en')}")
                    self.assertEqual(self.schedule_snapshot(), before, (seed, step, "claim before confirm"))
                    reviews = [(message, proposal) for message, proposal in owned_pending(u, "preview")
                               if message > previous_messages]
                    if reviews:
                        self.tap(u, "confirm", msg=reviews[-1][0])
                        counts["claim"] += 1
                        reply_to_request(u, d, rng.choice((True, False)))
                elif op == "e": self.tap(u, f"ntake:{d}:0")
                elif op in "sw":
                    before = self.schedule_snapshot()
                    previous_messages = max(sent, default=0)
                    self.tap(u, f"nswap:{d}:0")
                    self.assertEqual(self.schedule_snapshot(), before, (seed, step, "swap before review confirm"))
                    self.assertTrue(all(chat == u for mid, (chat, _) in sent.items() if mid > previous_messages))
                    reviews = [(message, proposal) for message, proposal in owned_pending(u, "request_preview")
                               if proposal["day"] == str(d)]
                    if reviews:
                        self.tap(u, "request_confirm", msg=reviews[-1][0])
                        self.assertEqual(self.schedule_snapshot(), before, (seed, step, "swap before other person's consent"))
                        counts["request"] += 1
                        reply_to_request(u, d, op == "s")
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
                        if live:
                            if all(b.is_off(db, w, day) for w in (1, 2)):
                                self.assertIsNone(own[chore][0], (seed, step, day, chore, "both unavailable"))
                            else:
                                self.assertIn(own[chore][0], (1, 2), (seed, step, day, chore))
                    offs = [w for w in (1, 2) if b.is_off(db, w, day)]
                    (dw, dl), (sw, sl) = own["dogs"], own["dishes"]
                    if dl and sl and dw is not None and dw == sw and len(offs) != 2:
                        self.assertEqual(len(offs), 1, (seed, step, day, "same person, nobody off"))
                        self.assertNotIn(dw, offs, (seed, step, day, "off walker holds both"))
                    if len(offs) == 1:
                        for chore, (w, live) in own.items():
                            if live: self.assertNotIn(w, offs, (seed, step, day, chore, "off walker owns"))
        for operation, count in counts.items():
            self.assertGreater(count, 100, (operation, "random coverage disappeared", counts))


class Round7(Base):
    def test_parent_cap_and_code_rotation(self):
        self.addCleanup(setattr, b, "OWNER_ID", b.OWNER_ID)
        b.OWNER_ID = 1
        b.kv(self.db, "bot", "u")
        self.text(1, "/invite"); old = b.kv(self.db, "code")
        self.text(1, "/invite")
        self.assertEqual(old, b.kv(self.db, "code"))
        self.tap(1, "rotate_links")
        preview = 100 + len(self.sent)
        self.assertEqual(old, b.kv(self.db, "code"))
        self.tap(1, "rotate_confirm", msg=preview)
        self.assertNotEqual(old, b.kv(self.db, "code"))
        b.on_start(self.db, {"id": 8, "first_name": "Dad"}, "parent_" + old)
        self.assertEqual(self.sent[-1], (8, "this bot's private"))
        b.on_start(self.db, {"id": 8, "first_name": "Dad"}, "parent_" + b.kv(self.db, "code"))
        b.on_start(self.db, {"id": 9, "first_name": "Gran"}, "parent_" + b.kv(self.db, "code"))
        self.assertEqual(self.sent[-1], (9, "already 2 parents"))
    def test_unknown_commands(self):
        self.text(2, "/invite"); self.text(2, "/foo"); self.text(3, "/bar")
        self.assertEqual([x[1] for x in self.sent], [b.tr("en", "commands")] * 3)
    def test_walker_welcome(self):
        db = b.connect(":memory:")
        self.addCleanup(db.close)
        self.addCleanup(setattr, b, "OWNER_ID", b.OWNER_ID)
        b.OWNER_ID = 5
        b.on_start(db, {"id": 5, "first_name": "M"}, "")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0], 5)
        self.assertIn("Today", self.sent[0][1])
        self.assertIn("18:30", self.sent[-1][1])
        self.assertIn("21:45", self.sent[-1][1])
        self.assertIn(b.tr("en", "solo"), self.sent[-1][1])

class Round6(Base):
    def test_pass_respects_other_walkers_unavailability(self):
        self.off(1, T); self.off(2, T); self.night(T, 1, "on", 1)
        self.tap(1, "cant")
        self.assertEqual(self.sent[-1], (3, b.tr("en", "nobody_parents")))
        self.assertEqual(b.night(self.db, T)["status"], "nobody")
        self.assertIsNone(b.night(self.db, T)["walker"])
    def test_old_done_callback_is_dogs(self):
        self.night(T, 1, "on", 1)
        self.tap(1, "done")
        self.assertEqual(b.night(self.db, T)["status"], "done")

class Round5(Base):
    def test_run_drains_before_tick(self):
        import tempfile
        order = []
        for k in ("tick", "connect", "LOCK", "TOKEN", "OWNER_ID", "HEALTH", "STOP"): self.addCleanup(setattr, b, k, getattr(b, k))
        def api(method, **p):
            if method == "getMe": return {"username": "u"}
            order.append(("poll", p.get("timeout")))
            if len(order) > 2: raise SystemExit
            return []
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        b.api, b.connect, b.LOCK, b.TOKEN = api, lambda: self.db, folder.name + "/run.lock", "x"
        b.HEALTH, b.OWNER_ID = folder.name + "/health.json", 1
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
    def test_owner_full(self):
        self.addCleanup(setattr, b, "OWNER_ID", b.OWNER_ID)
        b.OWNER_ID = 99
        b.on_start(self.db, {"id": 99, "first_name": "X"}, "")
        self.assertEqual(self.sent[-1], (99, "both spots are taken"))
    def test_prune_late_keys(self):
        b.kv(self.db, "late_dogs_2026-10-10", "1"); b.kv(self.db, "late_dogs_2026-10-14", "1")
        b.prune(self.db, self.at(T, 12))
        self.assertEqual([r[0] for r in self.db.execute("SELECT k FROM kv WHERE k LIKE 'late%'")], ["late_dogs_2026-10-14"])

class Week(Base):
    def test_view(self):
        text, kb = b.week_view(self.db, T, uid=1)
        self.assertIn(b.fmt(T), text)
        self.assertIn(b.fmt(D(21)), text)
        self.assertIn("Christian", text)
        nl = b.week_view(self.db, T, "nl", page=1)[0]
        self.assertIn(b.fmt(D(22), "nl"), nl)
        self.assertIn(b.fmt(D(28), "nl"), nl)
        k = kb["inline_keyboard"]
        self.assertEqual(([len(r) for r in k[:3]], k[0][1]), ([4, 3, 1], {"text": b.fmt(D(16)), "callback_data": "wk:2026-10-16:0"}))
        self.assertEqual(k[2][0]["callback_data"], "wp:1")
        self.assertEqual(k[-2:], b.menu_markup(self.db, 1)["inline_keyboard"])
        self.assertEqual([x["callback_data"] for x in k[3]], ["availability", "requests"])
        self.assertEqual(b.week_view(self.db, T, page=1)[1]["inline_keyboard"][2][0]["callback_data"], "wp:0")
    def test_marks(self):
        self.off(2, D(16))
        self.request_swap(1, D(17))
        friday = "\n".join(b.day_details(self.db, 2, D(16), b.owner(self.db, D(16), T), "nl"))
        saturday = "\n".join(b.day_details(self.db, 2, D(17), b.owner(self.db, D(17), T), "nl"))
        self.assertIn(b.tr("nl", "off_status", names="Christian"), friday)
        self.assertIn("Michael", friday)
        self.assertIn(b.tr("nl", "pending_status"), saturday)
    def test_one_walker(self):
        self.db.execute("DELETE FROM members WHERE id=2")
        self.assertIn(b.tr("en", "solo"), b.week_view(self.db, T, uid=1)[0])
    def test_week_message_tracked_and_refreshed(self):
        self.text(1, "/week")
        m = 100 + len(self.sent)
        b.confirm_off(self.db, 1, [D(17)])
        b.refresh_weeks(self.db)
        self.assertEqual(self.edits[-1][:2], (1, m))
        self.assertIn("Michael", self.edits[-1][2])
        self.assertEqual(self.edits[-1][2], b.week_view(self.db, T, uid=1)[0])
        n = len(self.edits); b.refresh_weeks(self.db)
        self.assertEqual(len(self.edits), n)  # unchanged: no edit
        b.edit = lambda *a, **k: False  # user deleted it
        b.confirm_off(self.db, 1, [D(18)]); b.refresh_weeks(self.db)
        self.assertIsNone(self.db.execute("SELECT * FROM weekmsg").fetchone())
    def test_paging(self):
        self.tap(1, "wp:1")
        self.assertEqual(self.edits[-1][2], b.week_view(self.db, T, page=1, uid=1)[0])
        self.tap(1, "wp:9")
        self.assertEqual(self.edits[-1][2], b.week_view(self.db, T, page=4, uid=1)[0])
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
        recipient, m = self.request_swap(1, D(16))
        b.apply_claim(self.db, 1, [D(16)])  # Fri changed hands meanwhile
        self.tap(2, "accept", msg=m)
        self.assertEqual(self.answers[-1], "that one's old")
    def test_swap_expires_at_night_start_and_pruned(self):
        self.request_swap(2, T)
        b.tick(self.db, self.at(T, 23, 1))
        self.assertEqual(b.all_pending(self.db), [])
    def test_swap_accepted(self):
        recipient, request = self.request_swap(1, D(16))
        self.assertEqual(self.sent[-1], (2, b.tr("en", "ask_give", name="Michael", day="Fri 16")))
        self.assertEqual(self.plan(2)[1], 2)  # nothing changes until accepted
        self.tap(2, "accept", msg=100 + len(self.sent))
        self.assertEqual(self.plan(), [1, 1, 2, 1, 2, 1, 2])
        self.assertIn((1, "👍 Christian said yes, Fri 16 goes to Michael"), self.sent)
    def test_swap_declined(self):
        recipient, request = self.request_swap(1, T)
        self.assertEqual(self.sent[-1], (2, b.tr("en", "ask_take", name="Michael", day="Thu 15")))
        self.tap(2, "no", msg=100 + len(self.sent))
        self.assertEqual((self.plan(1), self.sent[-1]), ([1], (1, "Christian said no to Thu 15")))
    def test_swap_moves_live_message(self):
        self.night(T, 1, "on", 7)
        recipient, request = self.request_swap(1, T)
        self.tap(recipient, "accept", msg=request)
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
        self.assertEqual(self.sent, [(3, b.tr("en", "late")), (3, b.tr("en", "late_dishes"))])  # no walker messages
    def test_transient_failure_retries_next_tick(self):
        b.send = lambda chat, text, markup=None: None
        b.tick(self.db, self.at(T, 21, 45))
        self.assertIsNone(b.night(self.db, T)["msg"])
        b.send = lambda chat, text, markup=None, **k: self.sent.append((chat, text)) or 300
        b.tick(self.db, self.at(T, 21, 46))
        self.assertEqual(self.dogs(), [(1, "🐕 dogs are yours tonight")])
    def test_off_tonight_passes_live_message(self):
        self.night(T, 1, "on", 7)
        self.text(1, "not tonight")
        self.assertEqual(b.night(self.db, T)["walker"], 1)
        self.tap(1, "av:confirm", msg=100 + len(self.sent))
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
        calls = []
        self.addCleanup(setattr, b, "TOKEN", b.TOKEN)
        b.TOKEN = "x"
        def boom(db, t): raise RuntimeError("x")
        def api(method, **p):
            calls.append(method)
            if method == "getMe": return {"username": "u"}
            if len(calls) > 3: raise SystemExit
            return []
        for k in ("tick", "connect", "LOCK", "OWNER_ID", "HEALTH", "STOP"): self.addCleanup(setattr, b, k, getattr(b, k))
        import tempfile
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        b.LOCK, b.HEALTH, b.OWNER_ID = folder.name + "/run.lock", folder.name + "/health.json", 1
        b.tick, b.api, b.connect = boom, api, lambda: self.db
        with self.assertRaises(SystemExit): b.run()
        self.assertGreater(calls.count("getUpdates"), 1)
    def test_missed_yesterday_once(self):
        self.db.execute("UPDATE members SET joined=joined-86400*3")
        b.tick(self.db, self.at(T, 10)); b.tick(self.db, self.at(T, 11))
        notices = [text for uid, text in self.sent if uid == 3]
        self.assertEqual(len(notices), 2)
        for chore in b.CHORES:
            self.assertEqual(sum(b.tr("en", chore + "_label") in text for text in notices), 1)
            self.assertEqual(b.night(self.db, D(14), chore)["status"], "missed")
    def test_overdue_once(self):
        self.night(T, 1, "on", 1)
        self.assertIsNone(b.overdue(self.db, self.at(T, 22, 30)))
        b.tick(self.db, self.at(T, 23, 1)); b.tick(self.db, self.at(T, 23, 2))
        self.assertEqual(self.sent.count((3, b.tr("en", "late"))), 1)
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
        self.assertEqual(self.sent[-1][0], 2)
        self.assertIn("Fri 16", self.sent[-1][1])
        self.assertFalse(b.is_off(self.db, 2, D(16)))
        self.assertEqual(self.plan(2)[1], 2)  # not saved yet
        self.tap(2, "av:confirm", msg=self.last())
        self.assertTrue(b.is_off(self.db, 2, D(16)))
        self.assertEqual(self.plan(2)[1], 1)
    def test_claim_confirm(self):
        self.off(2, D(18))
        self.text(1, "he does the weekend")
        self.assertEqual(self.sent[-1][1], "Christian walks: Sat 17, Sun 18")
        self.tap(1, "confirm", msg=self.last())
        self.assertEqual(self.sent[-1], (2, b.tr("en", "ask_take", name="Michael", day="Sat 17")))  # Sun skipped, he's off
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
        self.assertEqual(self.plan(2), [1, 2], "Other walker must still consent")
        self.tap(2, "accept", msg=self.last())
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
        b.kv(self.db, "code", "abc")
        b.on_start(self.db, {"id": 9, "first_name": "Dad"}, "parent_abc")
        own = [text for uid, text in self.sent if uid == 9]
        self.assertEqual(len(own), 1)
        self.assertIn("Today", own[0])
        self.assertIn((1, "Dad joined"), self.sent)
        self.assertNotIn((3, "Dad joined"), self.sent)  # parents don't hear about parents
    def test_only_owner_starts(self):
        db = b.connect(":memory:")
        self.addCleanup(db.close)
        self.addCleanup(setattr, b, "OWNER_ID", b.OWNER_ID)
        b.OWNER_ID = 42
        b.on_start(db, {"id": 9, "first_name": "X"}, "")
        self.assertEqual(self.sent[-1], (9, "this bot's private"))
        b.on_start(db, {"id": 42, "first_name": "Michael"}, "")
        self.assertEqual(b.role_of(db, 42), "walker")
        b.kv(db, "bot", "honduitlatenbot")
        b.on_text(db, {"from": {"id": 42}, "chat": {"type": "private"}, "text": "/invite"})
        self.assertIn("start=walker_", self.sent[-1][1])
        n = len(self.sent)
        b.on_start(db, {"id": 7, "first_name": "Christian"}, "walker_" + b.kv(db, "code"))
        b.on_text(db, {"from": {"id": 7}, "chat": {"type": "private"}, "text": "/invite"})
        self.assertNotIn("start=", self.sent[-1][1])
        self.assertGreater(len(self.sent), n)
    def test_unknown_rejected(self):
        b.on_start(self.db, {"id": 9, "first_name": "X"}, "walker_nope")
        self.assertEqual(self.sent, [(9, "this bot's private")])

class Language(Base):
    def test_toggle_and_dutch(self):
        self.text(2, "/lang")
        self.tap(2, "lang:nl")
        self.assertEqual(b.lang_of(self.db, 2), "nl")
        self.assertIn(b.tr("nl", "today", day=b.fmt(T, "nl")), self.edits[-1][2])
        self.text(2, "kan niet vrijdag")  # parser stays bilingual
        self.assertEqual(self.sent[-1][0], 2)
        self.assertIn("Vr 16", self.sent[-1][1])
        self.assertEqual(b.peek_pending(self.db, 2, 100 + len(self.sent))["mode"], "off")
    def test_bad_lang_falls_back(self):
        self.tap(2, "lang:xx")
        self.assertEqual(b.lang_of(self.db, 2), "en")
        self.assertIn(b.tr("en", "today", day=b.fmt(T)), self.edits[-1][2])
    def test_both_off_note_needs_two_walkers(self):
        self.db.execute("DELETE FROM members WHERE id=2"); self.off(1, T)
        b.say_on(self.db, 1, T.isoformat(), "dogs")
        self.assertNotIn("both off", self.sent[-1][1])
    def test_night_menu(self):
        marks = []
        b.edit = lambda chat, msg, text, markup=None, **k: (self.edits.append((chat, msg, text)), marks.append(markup))
        self.tap(1, "wk:2026-10-16:0")  # Michael's night: off / swap / back
        kb = marks[-1]["inline_keyboard"]
        self.assertEqual([[x["callback_data"] for x in r] for r in kb[:2]], [["noff:2026-10-16:0", "nswap:2026-10-16:0"], ["wp:0"]])
        self.assertEqual(kb[2:], b.menu_markup(self.db, 1)["inline_keyboard"])
        self.tap(1, "noff:2026-10-16:0")
        self.assertFalse(b.is_off(self.db, 1, D(16)))
        self.tap(1, "av:confirm", msg=100 + len(self.sent))
        self.assertTrue(b.is_off(self.db, 1, D(16)))
        self.tap(1, "wk:2026-10-16:0")
        self.assertEqual(marks[-1]["inline_keyboard"][0][0]["callback_data"], "nin:2026-10-16:0")
        self.tap(1, "nin:2026-10-16:0")
        self.assertTrue(b.is_off(self.db, 1, D(16)))
        self.tap(1, "av:confirm", msg=100 + len(self.sent))
        self.assertFalse(b.is_off(self.db, 1, D(16)))
    def test_take_needs_empty_night(self):
        d = next(d for d, w in b.week(self.db, T) if w == 2)
        self.tap(1, f"ntake:{d}:0")  # Christian's night: no taking without his yes
        self.assertEqual(b.owner(self.db, d, T), 2)
    def test_plan_button(self):
        self.assertEqual(len(b.chore_buttons(self.db, 1, "dogs")["inline_keyboard"]), 1)  # reminders: done/can't only
        self.tap(1, "plan")
        self.assertFalse(self.sent)
        self.assertEqual(self.edits[-1][2], b.week_view(self.db, T, uid=1)[0])
        self.assertTrue(all(len(x["callback_data"].encode()) <= 64 for r in b.week_view(self.db, T)[1]["inline_keyboard"] for x in r))
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
