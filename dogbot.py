"""Honduitlaatbot: evening rota for two brothers. Telegram DMs, buttons only, long polling, SQLite."""
import fcntl, html, json, os, secrets, shutil, sqlite3, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Amsterdam")
CHORES = {"afwas": ("🍽", "Afwas", (18, 30)), "honden": ("🐕", "Honden", (21, 45))}  # emoji, label, card time
DOGS_FROM = 21   # ✅ Honden works from 21:00
GIVE_UNTIL = 23  # 🙅 works until 23:00
CLOSE = 3        # open chores count as forgotten at 03:00 the next morning
AHEAD = 14       # calendar horizon in days
MAX_PINGS = 2    # notifying messages per brother per evening
DAYS = "ma di wo do vr za zo".split()
MONTHS = "januari februari maart april mei juni juli augustus september oktober november december".split()
MENU_KEY = {"keyboard": [[{"text": "☰ Menu"}]], "resize_keyboard": True, "is_persistent": True,
            "input_field_placeholder": "Tik op ☰ Menu"}
DB = os.environ.get("DOGBOT_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "dogbot.db"))

# ---------- storage ----------

MIGRATIONS = [  # append only: each runs once, in order; PRAGMA user_version remembers how far a database got
    """
    CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY, name TEXT, role TEXT, joined INTEGER, lang TEXT DEFAULT 'nl');
    CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS tasks(day TEXT, chore TEXT, who INTEGER, payback INTEGER DEFAULT 0, done_at TEXT,
                                     missed INTEGER DEFAULT 0, PRIMARY KEY(day, chore));
    CREATE TABLE IF NOT EXISTS points(day TEXT, chore TEXT, uid INTEGER, n INTEGER);
    CREATE TABLE IF NOT EXISTS cards(uid INTEGER, day TEXT, msg INTEGER, pings INTEGER, PRIMARY KEY(uid, day));
    """,
]

def connect(path=DB):
    """Open the database and bring it up to date. An existing file is copied to <path>.bak-v<version> first."""
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    have = db.execute("PRAGMA user_version").fetchone()[0]
    if have < len(MIGRATIONS) and path != ":memory:" and os.path.getsize(path):
        shutil.copyfile(path, f"{path}.bak-v{have}")
    for version, sql in enumerate(MIGRATIONS[have:], have + 1):
        db.executescript(sql)
        db.execute(f"PRAGMA user_version={version}")
    db.commit()
    return db

def kv(db, k, v=None):
    if v is not None:
        db.execute("REPLACE INTO kv VALUES(?,?)", (k, v)); db.commit(); return v
    r = db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r and r[0]

def walkers(db):
    return [r[0] for r in db.execute("SELECT id FROM members WHERE role='walker' ORDER BY joined")]

def other(db, uid): return next((w for w in walkers(db) if w != uid), None)

def name(db, uid):
    r = db.execute("SELECT name FROM members WHERE id=?", (uid,)).fetchone()
    return html.escape(r[0] if r else "?")

# ---------- rota ----------

def rota(db, day):
    """Whose evening `day` is: om en om, the first walker on the day he joined."""
    w = walkers(db)
    if len(w) < 2: return w[0] if w else None
    start = datetime.fromtimestamp(db.execute("SELECT MIN(joined) FROM members WHERE role='walker'").fetchone()[0], TZ)
    return w[(day - start.date()).days % 2]

def task(db, day, chore):
    return db.execute("SELECT * FROM tasks WHERE day=? AND chore=?", (day.isoformat(), chore)).fetchone()

def who(db, day, chore):
    """Who has `chore` on `day`: the rota owner unless it changed hands. None: someone else does it."""
    t = task(db, day, chore)
    return t["who"] if t else rota(db, day)

def setrow(db, day, chore, **cols):
    db.execute(f"INSERT INTO tasks(day, chore, {', '.join(cols)}) VALUES(?,?{',?' * len(cols)}) ON CONFLICT(day, chore) "
               f"DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in cols)}", (day.isoformat(), chore, *cols.values()))
    db.commit()

def is_open(db, day, chore):
    t = task(db, day, chore)
    return not (t and (t["done_at"] or t["missed"]))

def mine(db, day, uid):
    """Chores of `day` that concern uid: his evening, or handed to him."""
    return [c for c in CHORES if rota(db, day) == uid or who(db, day, c) == uid]

def todo(db, day, uid):
    return [c for c in CHORES if who(db, day, c) == uid and is_open(db, day, c)]

def score(db, uid):
    return db.execute("SELECT COALESCE(SUM(n), 0) FROM points WHERE uid=?", (uid,)).fetchone()[0]

def point(db, day, chore, plus, minus):
    """Every point moves both ways: one brother +1, the other -1."""
    db.executemany("INSERT INTO points VALUES(?,?,?,?)", [(day.isoformat(), chore, plus, 1), (day.isoformat(), chore, minus, -1)])
    db.commit()

def settle(db, today):
    """Whoever is behind takes the other's next chores, from overmorgen on, until it's even again."""
    for uid in walkers(db):
        o = other(db, uid)
        if o is None: return
        owed = max(-score(db, uid), 0)
        pending = db.execute("SELECT day, chore FROM tasks WHERE who=? AND payback=1 AND done_at IS NULL AND missed=0 "
                             "AND day>=? ORDER BY day DESC, chore DESC", (uid, today.isoformat())).fetchall()
        extra = [p for p in pending if p["day"] > today.isoformat()][:max(len(pending) - owed, 0)]
        db.executemany("DELETE FROM tasks WHERE day=? AND chore=?", [tuple(p) for p in extra])
        need, d = owed - len(pending), today + timedelta(days=2)
        while need > 0 and d < today + timedelta(days=AHEAD):
            for chore in CHORES:
                if need > 0 and rota(db, d) == o and not task(db, d, chore):
                    setrow(db, d, chore, who=uid, payback=1); need -= 1
            d += timedelta(days=1)
    db.commit()

def close(db, day):
    """03:00: open chores that still had someone count as forgotten, a point to the other brother."""
    for chore in CHORES:
        uid = who(db, day, chore)
        if uid is None or not is_open(db, day, chore): continue
        setrow(db, day, chore, who=uid, missed=1)
        if other(db, uid): point(db, day, chore, other(db, uid), uid)
    refresh(db, day)

# ---------- text ----------

def at(day, hm): return datetime(day.year, day.month, day.day, *hm, tzinfo=TZ)

def fmt(d): return f"{DAYS[d.weekday()]} {d.day}"

def when(d):
    return {0: "vanavond", 1: "morgen"}.get((d - now().date()).days, fmt(d))

def noun(chore): return "de " + chore

def who_name(db, w, uid): return "jij" if w == uid else name(db, w) if w else "iemand anders"

def line(db, day, chore, uid):
    e, label, hm = CHORES[chore]
    t, w = task(db, day, chore), who(db, day, chore)
    done = t and t["done_at"]
    if w != uid: s = f" → {who_name(db, w, uid)}" + (" ✅" if done else "")
    elif done: s = f" ✅ {done}"
    elif t and t["missed"]: s = " ✕ vergeten"
    elif t and t["payback"]: s = " · inhaal"
    elif rota(db, day) != uid: s = " · +1"
    else: s = f" · {hm[0]}:{hm[1]:02}"
    return f"{e} {label}{s}"

def btn(text, data, style=None):
    return {"text": text, "callback_data": data, **({"style": style} if style else {})}

def kbd(rows): return {"inline_keyboard": [r for r in rows if r]}

def can_give(db, day, chore, uid):
    t = task(db, day, chore)
    return who(db, day, chore) == uid and is_open(db, day, chore) and not (t and t["payback"]) \
        and now().date() <= day < now().date() + timedelta(days=AHEAD) and now() < at(day, (GIVE_UNTIL, 0))

# ---------- views ----------

def card_view(db, uid, day, choose=False):
    """Tonight's card: every chore of the evening that concerns uid, ✅ per open one, 🙅 while it can still move."""
    give = [c for c in CHORES if can_give(db, day, c, uid)]
    if choose:
        return "<b>Wat lukt niet ?</b>", [[btn(f"{CHORES[c][0]} {CHORES[c][1]}", f"g:{day}:{c}") for c in give],
                                          [btn("« Terug", f"b:{day}")]]
    left = todo(db, day, uid)
    if left: title = "Tijd voor de honden 🐕" if "honden" in left and now() >= at(day, CHORES["honden"][2]) \
        else "Vanavond ben jij aan de beurt"
    else: title = "Alles gedaan, toppp 🫶" if any(who(db, day, c) == uid and task(db, day, c) and task(db, day, c)["done_at"]
                                                  for c in CHORES) else "Vanavond is geregeld 👍"
    kb = [[btn(f"✅ {CHORES[c][1]}", f"d:{day}:{c}", "success") for c in left], [btn("🙅 Ik kan niet", f"k:{day}")] if give else []]
    return f"<b>{title}</b>\n" + "\n".join(line(db, day, c, uid) for c in mine(db, day, uid)), kb

def menu_view(db, uid):
    today = now().date()
    def summary(d):
        rows = [(c, who(db, d, c), task(db, d, c)) for c in CHORES]
        tick = lambda r: f" ✅ {r['done_at']}" if r and r["done_at"] else ""
        if rows[0][1] == rows[1][1]:
            return who_name(db, rows[0][1], uid) + "".join(f" · {CHORES[c][0]}{tick(r)}" for c, _, r in rows if tick(r))
        return " · ".join(f"{CHORES[c][0]} {who_name(db, w, uid)}{tick(r)}" for c, w, r in rows)
    s = score(db, uid)
    stand = f"⚖️ {'gelijk' if s == 0 else f'jij {s:+d}'}"
    nxt = db.execute("SELECT day, chore FROM tasks WHERE who=? AND payback=1 AND done_at IS NULL AND missed=0 AND day>=? "
                     "ORDER BY day LIMIT 1", (uid, today.isoformat())).fetchone()
    if nxt: stand += f" · inhalen {when(date.fromisoformat(nxt['day']))} {CHORES[nxt['chore']][0]}"
    kb = [[btn("📅 Kalender", "cal")]]
    if len(walkers(db)) < 2:
        link = f"https://t.me/{kv(db, 'bot')}?start=w_{kv(db, 'code') or kv(db, 'code', secrets.token_hex(4))}"
        kb.append([{"text": "📤 Uitnodiging sturen", "url": "https://t.me/share/url?url=" + urllib.parse.quote(link, safe="")}])
    return f"<b>Vanavond</b>  {summary(today)}\n<b>Morgen</b>  {summary(today + timedelta(days=1))}\n{stand}", kb

def calendar_view(db, uid):
    """Every evening in the next two weeks that concerns uid. No emoji: both chores. One emoji: only that one."""
    today, row = now().date(), []
    for d in (today + timedelta(days=i) for i in range(AHEAD)):
        if not any(is_open(db, d, c) for c in mine(db, d, uid)) or (d == today and now() >= at(d, (GIVE_UNTIL, 0))): continue
        have = [c for c in CHORES if who(db, d, c) == uid]
        label = fmt(d) + ("" if len(have) == 2 else f" {CHORES[have[0]][0]}" if have else "")
        row.append(btn(label if have else f"✕ {label}", f"e:{d}", None if have else "danger"))
    return "<b>Jouw avonden</b>\nTik op een avond om iets af te zeggen", \
        [row[i:i + 4] for i in range(0, len(row), 4)] + [[btn("« Terug", "m")]]

def evening_view(db, uid, day):
    row = []
    for c in mine(db, day, uid):
        e, label, _ = CHORES[c]
        t, has = task(db, day, c), who(db, day, c) == uid
        if t and t["done_at"]: row.append(btn(f"{e} {label} ✅ {t['done_at']}", f"e:{day}"))
        else: row.append(btn(f"{e} {label} {'✅' if has else '✕'}", f"t:{day}:{c}", "success" if has else "danger"))
    return f"<b>{fmt(day).capitalize()} {MONTHS[day.month - 1]}</b>\nWat doe jij ?", [row, [btn("« Terug", "cal")]]

# ---------- telegram ----------

TOKEN = os.environ.get("DOGS_TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID") or 0)  # Michael: the only one who can start the bot without a link
RETRY = (0, 1, 3, 9)  # seconds between send attempts

def log(*a): print(datetime.now(TZ).strftime("%F %T"), *a, file=sys.stderr, flush=True)

def api(method, **params):
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}",
                                 data=json.dumps(params).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)["result"]

def send(chat, text, markup=None, silent=False):
    """Message id; False if the user blocked the bot (403); None on other failures. Only evening cards make noise."""
    p = {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_notification": silent,
         **({"reply_markup": markup} if markup else {})}
    for wait in RETRY:
        time.sleep(wait)
        try:
            return api("sendMessage", **p)["message_id"]
        except urllib.error.HTTPError as e:
            log("send", chat, e.code)
            if e.code == 403: return False
            if e.code == 429:
                time.sleep(min(json.loads(e.read() or b"{}").get("parameters", {}).get("retry_after", 1), 10))
                return None
            if e.code == 400: return None
        except Exception as e:
            log("send", chat, e)
    return None

def edit(chat, msg, text, rows=()):
    try:
        api("editMessageText", chat_id=chat, message_id=msg, text=text, parse_mode="HTML", reply_markup=kbd(rows))
    except urllib.error.HTTPError as e:
        if b"not modified" not in e.read(): log("edit", chat, e.code)
    except Exception as e:
        log("edit", chat, e)

def delete(chat, msg):
    try: api("deleteMessage", chat_id=chat, message_id=msg)
    except Exception as e: log("delete", chat, e)

def now(): return datetime.now(TZ)

def post_card(db, uid, day, ping):
    """Show uid's card for `day`. A ping sends it fresh at the bottom, at most MAX_PINGS a night; otherwise it's edited quietly."""
    text, kb = card_view(db, uid, day)
    c = db.execute("SELECT * FROM cards WHERE uid=? AND day=?", (uid, day.isoformat())).fetchone()
    ping = ping and (c["pings"] if c else 0) < MAX_PINGS
    if c and not ping: return edit(uid, c["msg"], text, kb)
    if c: delete(uid, c["msg"])
    m = send(uid, text, kbd(kb), silent=not ping)
    if m: db.execute("REPLACE INTO cards VALUES(?,?,?,?)", (uid, day.isoformat(), m, (c["pings"] if c else 0) + ping)); db.commit()

def refresh(db, day):
    for (uid,) in db.execute("SELECT uid FROM cards WHERE day=?", (day.isoformat(),)).fetchall():
        post_card(db, uid, day, False)

def give(db, uid, day, chore):
    """uid can't: the chore goes to the other brother, or to nobody if it was the other's to begin with.
    Once the evening has started the one who has to know gets his card with a ping, before that a quiet message."""
    owner = rota(db, day)
    to = other(db, uid) if owner == uid else None
    setrow(db, day, chore, who=to, payback=0)
    tell, text = (to, f"{name(db, uid)} kan {when(day)} {noun(chore)} niet, die doe jij 🙏") if to else \
        (owner, f"{name(db, uid)} kan {when(day)} {noun(chore)} ook niet, iemand anders moet 't doen 😭")
    if tell and tell != uid:
        if now() >= at(day, CHORES["afwas"][2]): post_card(db, tell, day, True)
        else: send(tell, text, silent=True)
    refresh(db, day)

def take_back(db, uid, day, chore):
    was = who(db, day, chore)
    setrow(db, day, chore, who=uid, payback=0)
    if was: send(was, f"{name(db, uid)} doet {when(day)} {noun(chore)} toch zelf 👍", silent=True)
    refresh(db, day)

def show_menu(db, uid, msg=None):
    """A fresh menu at the bottom; the previous one is deleted. With msg: edit that one in place."""
    text, kb = menu_view(db, uid)
    if msg: return edit(uid, msg, text, kb)
    old = kv(db, f"menu_{uid}")
    if old: delete(uid, int(old))
    m = send(uid, text, kbd(kb), silent=True)
    if m: kv(db, f"menu_{uid}", str(m))

def tick(db, t):
    """Cards at 18:30 to whoever has something open, the dogs card again at 21:45, yesterday closed at 03:00."""
    day = t.date()
    since = date.fromisoformat(kv(db, "since") or kv(db, "since", day.isoformat()))
    y = day - timedelta(days=1 if t.hour >= CLOSE else 2)
    if y >= since and not kv(db, f"closed_{y}"):
        kv(db, f"closed_{y}", "1"); close(db, y)
    if t >= at(day, CHORES["afwas"][2]):
        for uid in walkers(db):
            if todo(db, day, uid) and not db.execute("SELECT 1 FROM cards WHERE uid=? AND day=?", (uid, day.isoformat())).fetchone():
                post_card(db, uid, day, True)
    if t >= at(day, CHORES["honden"][2]) and not kv(db, f"dogs_{day}"):
        kv(db, f"dogs_{day}", "1")
        if who(db, day, "honden") and is_open(db, day, "honden"): post_card(db, who(db, day, "honden"), day, True)
    settle(db, day)

# ---------- handlers ----------

def on_button(db, q):
    """Handle the tap first, answer Telegram last: a failed answer (e.g. query too old) never loses the tap."""
    reply = {}
    def answer(text): reply["text"] = text
    try:
        handle_button(db, q, answer)
    except (ValueError, KeyError, IndexError) as e:  # malformed or outdated callback_data
        reply["text"] = "Die is verlopen"
        log("callback", q.get("data"), repr(e))
    except Exception:
        reply["text"] = "Oeps, probeer nog eens"
        raise
    finally:
        try: api("answerCallbackQuery", callback_query_id=q["id"], **reply)
        except Exception as e: log("answer", e)

def handle_button(db, q, answer):
    uid, msg, data = q["from"]["id"], q["message"]["message_id"], q["data"]
    if uid not in walkers(db): return answer("Deze bot is privé")
    if data == "m": return show_menu(db, uid, msg)
    if data == "cal": return edit(uid, msg, *calendar_view(db, uid))
    kind, day, chore = (data.split(":") + [""])[:3]
    day = date.fromisoformat(day)
    if chore and chore not in CHORES: raise ValueError(chore)
    if kind == "e": return edit(uid, msg, *evening_view(db, uid, day))
    if kind == "t":
        t, has = task(db, day, chore), who(db, day, chore) == uid
        if has and can_give(db, day, chore, uid): give(db, uid, day, chore)
        elif has and t and t["payback"] and is_open(db, day, chore): answer("Dit is een inhaalklus, die blijft van jou")
        elif not has and rota(db, day) == uid and is_open(db, day, chore) and now() < at(day, (GIVE_UNTIL, 0)):
            take_back(db, uid, day, chore)
        else: answer("Te laat ahah, regel 't even zelf")
        return edit(uid, msg, *evening_view(db, uid, day))
    if kind == "k": return edit(uid, msg, *card_view(db, uid, day, choose=True))
    if kind == "b": return edit(uid, msg, *card_view(db, uid, day))
    if kind == "g":
        if can_give(db, day, chore, uid): give(db, uid, day, chore)
        else: answer("Te laat ahah, regel 't even zelf")
        return edit(uid, msg, *card_view(db, uid, day))
    if kind == "d":
        t = now()
        if who(db, day, chore) != uid or not is_open(db, day, chore) or t >= at(day + timedelta(days=1), (CLOSE, 0)):
            return answer("Die is verlopen")
        if chore == "honden" and t < at(day, (DOGS_FROM, 0)): return answer("Nog even wachten, honden zijn om 21:45")
        setrow(db, day, chore, who=uid, done_at=t.strftime("%H:%M"))
        if rota(db, day) != uid: point(db, day, chore, uid, rota(db, day))
        return refresh(db, day)
    raise ValueError(kind)

def on_start(db, u, arg):
    uid, first, w = u["id"], u.get("first_name") or "?", walkers(db)
    if uid in w: return show_menu(db, uid)
    code = kv(db, "code")
    if uid != OWNER_ID and not (code and arg == f"w_{code}"): return send(uid, "Deze bot is privé")
    if len(w) >= 2: return send(uid, "Er zijn al twee lopers")
    db.execute("INSERT INTO members(id, name, role, joined) VALUES(?,?,'walker',?)", (uid, first, int(time.time()))); db.commit()
    send(uid, "Welkom bij Honduitlaatbot 🐕\n" + ("Je krijgt een berichtje als je aan de beurt bent" if w
                                                  else "Stuur de uitnodiging even naar je broer 🙏"), MENU_KEY)
    for x in w: send(x, f"{name(db, uid)} doet mee 🫶", silent=True)
    show_menu(db, uid)

def on_text(db, msg):
    """Buttons only: /start joins, anything else typed brings the menu back."""
    if msg["chat"]["type"] != "private" or "text" not in msg: return
    uid = msg["from"]["id"]
    if msg["text"].startswith("/start"): return on_start(db, msg["from"], msg["text"][6:].strip())
    if uid not in walkers(db): return send(uid, "Deze bot is privé")
    delete(uid, msg["message_id"])
    show_menu(db, uid)

def setup():
    """One-off bot profile: the name, and no commands anywhere."""
    log("bot", api("getMe")["username"])
    api("setMyName", name="Honduitlaatbot")
    for scope in ({"type": "default"}, {"type": "chat", "chat_id": OWNER_ID}):
        for lang in ({}, {"language_code": "nl"}):
            api("deleteMyCommands", scope=scope, **lang)

LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dogbot.lock")

def run():
    if not TOKEN: sys.exit("DOGS_TELEGRAM_BOT_TOKEN not set")
    lock = open(LOCK, "a+")
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: sys.exit(3)  # another instance is running; run.sh stops on 3
    lock.truncate(0); lock.write(str(os.getpid())); lock.flush()
    db = connect()
    kv(db, "bot", api("getMe")["username"])
    for uid in walkers(db):  # brothers from before the buttons-only version have no ☰ Menu key yet
        if not kv(db, f"key_{uid}") and send(uid, "Alles gaat nu met knoppen, tik op ☰ Menu 👇", MENU_KEY, silent=True):
            kv(db, f"key_{uid}", "1")
    log("polling")
    poll(db, 0)  # handle taps queued while down (e.g. ✅) before tick() can count them as forgotten
    while True:
        try: tick(db, now())
        except Exception as e: log("tick", repr(e))
        poll(db, 25)

def poll(db, timeout):
    offset = int(kv(db, "offset") or 0)
    try:
        ups = api("getUpdates", offset=offset, timeout=timeout, allowed_updates=["message", "callback_query"])
    except Exception as e:
        log("poll", e); time.sleep(5); return
    for up in ups:
        kv(db, "offset", str(up["update_id"] + 1))
        try:
            if "callback_query" in up: on_button(db, up["callback_query"])
            elif "message" in up: on_text(db, up["message"])
        except Exception as e:
            log("handler", repr(e))

if __name__ == "__main__":
    setup() if sys.argv[1:] == ["setup"] else run()
