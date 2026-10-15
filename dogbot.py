"""Dog-walk rotation bot. Telegram DMs, long polling, SQLite."""
import fcntl, html, json, os, re, sqlite3, sys, time, urllib.error, urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Amsterdam")
# chore: (message time, hour until which Can't is allowed; parents alerted then if not done)
CHORES = {"dogs": ((21, 45), 23), "dishes": ((18, 30), 21)}
DONE_UNTIL = 3      # Done allowed until 03:00 next morning
DB = os.environ.get("DOGBOT_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "dogbot.db"))

S = {  # key: (English, Nederlands)
    "days": ("Mon Tue Wed Thu Fri Sat Sun", "Ma Di Wo Do Vr Za Zo"),
    "b_done": ("✅ done", "✅ klaar"),
    "b_cant": ("🙅 can't", "🙅 kan niet"),
    "b_pcover": ("🙋 i got it", "🙋 ik doe 't"),
    "b_confirm": ("yep", "jep"),
    "b_cancel": ("nah", "laat maar"),
    "b_off": ("can't", "kan niet"),
    "b_walk": ("i'll walk", "ik loop"),
    "b_accept": ("yes", "ja"),
    "b_no": ("no", "nee"),
    "on": ("🐕 dogs are yours tonight", "🐕 honden zijn voor jou vanavond"),
    "on_dishes": ("🍽 dishes are yours tonight", "🍽 afwas is voor jou vanavond"),
    "on_passed_dishes": ("🍽 {name} can't, dishes are yours", "🍽 {name} kan niet, afwas is voor jou"),
    "on_unreachable_dishes": ("🍽 can't reach {name}, dishes are yours", "🍽 {name} is onbereikbaar, afwas is voor jou"),
    "both_off": ("\nyou're both off, so dogs are yours", "\njullie kunnen allebei niet, dus honden zijn voor jou"),
    "both_off_dishes": ("\nyou're both off, so dishes are yours", "\njullie kunnen allebei niet, dus afwas is voor jou"),
    "walked_dishes": ("✅ done {hm}", "✅ klaar {hm}"),
    "nobody_either_dishes": ("{name} can't either, no one on dishes", "{name} kan ook niet, niemand op de afwas"),
    "nobody_parents_dishes": ("no one's free for dishes tonight", "niemand kan de afwas vanavond"),
    "late_dishes": ("dishes still not done", "afwas is nog niet gedaan"),
    "pcover_all_dishes": ("{name}'s got the dishes tonight", "{name} doet de afwas vanavond"),
    "on_passed": ("🐕 {name} can't, dogs are yours", "🐕 {name} kan niet, honden zijn voor jou"),
    "on_unreachable": ("🐕 can't reach {name}, dogs are yours", "🐕 {name} is onbereikbaar, honden zijn voor jou"),
    "unreachable": ("can't reach {name}", "{name} is onbereikbaar"),
    "walked": ("✅ walked {hm}", "✅ gelopen {hm}"),
    "parent_done": ("✅ dogs are out, {name} ({hm})", "✅ honden zijn uit, {name} ({hm})"),
    "passed": ("passed to {name}", "naar {name}"),
    "nobody": ("no one's free tonight", "niemand kan vanavond"),
    "nobody_either": ("{name} can't either, no one on dogs", "{name} kan ook niet, niemand op de honden"),
    "nobody_parents": ("no one's free for the dogs tonight", "niemand kan de honden vanavond"),
    "too_late": ("too late to pass, sort it irl aha", "te laat, regel het even zelf"),
    "old": ("that one's old", "die is verlopen"),
    "settled": ("tonight's sorted", "vanavond is al geregeld"),
    "late": ("dogs not done yet", "honden nog niet gedaan"),
    "pcover_me": ("🙋 you're on it, thanks!", "🙋 jij doet 't, top!"),
    "pcover_all": ("{name}'s got the dogs tonight", "{name} doet de honden vanavond"),
    "pcover_live": ("{name}'s got it", "{name} doet 't"),
    "sorted": ("already sorted", "al geregeld"),
    "months": ("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec", "jan feb mrt apr mei jun jul aug sep okt nov dec"),
    "week": ("week {span}", "week {span}"),
    "you": ("you", "jij"),
    "solo": ("other walker's not in yet, you've got both", "andere loper zit er nog niet in, jij doet alles"),
    "too_far": ("max 2 weeks ahead", "max 2 weken vooruit"),
    "b_next": ("next week ▶", "volgende week ▶"),
    "b_prev": ("◀ this week", "◀ deze week"),
    "commands": ("/week · /lang", "/week · /lang"),
    "taken": ("{day}'s yours", "{day} is van jou"),
    "target_off": ("{name} can't then", "{name} kan dan niet"),
    "asked": ("asked {name}", "{name} gevraagd"),
    "ask_take": ("{name} asks: can you take {day}?", "{name} vraagt: kan jij {day}?"),
    "ask_give": ("{name} wants your {day}", "{name} wil jouw {day}"),
    "declined": ("no swap", "niet geruild"),
    "req_yes": ("👍 {name} said yes, {day} goes to {walker}", "👍 {name} zei ja, {day} is voor {walker}"),
    "req_no": ("{name} said no to {day}", "{name} zei nee op {day}"),
    "preview_off": ("off: {days}", "kan niet: {days}"),
    "preview_claim": ("{name} walks: {days}", "{name} loopt: {days}"),
    "which": ("{day}: off or walking?", "{day}: kan je niet of loop je?"),
    "saved": ("👍 saved", "👍 opgeslagen"),
    "huh": ("didn't get that, try \"not fri\"", "snap 'm niet, probeer \"kan niet vr\""),
    "retry": ("couldn't reach {name}, try again", "{name} niet bereikt, nog een keer?"),
    "missed": ("bot was down last night, nothing went out", "bot lag eruit gisteravond, niks verstuurd"),
    "cant_reach": ("can't reach {name}", "{name} is onbereikbaar"),
    "error": ("oops, try again", "oeps, probeer nog eens"),
    "swapped": ("👍 {day} goes to {walker}", "👍 {day} is voor {walker}"),
    "swapped_dogs": ("🐕 {day} goes to {walker}", "🐕 {day} is voor {walker}"),
    "cancelled": ("cancelled", "geannuleerd"),
    "private": ("this bot's private", "deze bot is privé"),
    "already_in": ("you're already in, /week shows the plan", "je zit er al in, /week voor de planning"),
    "hi_walker": "Heyyy! dog and dish bot here 🐕 dishes 18:30, dogs 21:45, hit done when u did it, "
                 "can't just passes that one job on aha, other one taps start first 🙏",
    "hi_parent": "Heyyy! dog and dish bot here 🐕 you'll hear when the dogs are out, or if something's left",
    "joined": ("{name} joined", "{name} doet mee"),
    "lang": ("Language", "Taal"),
    "b_plan": ("📅 plan", "📅 planning"),
    "b_noff": ("i'm off", "ik kan niet"),
    "b_ntake": ("i'll take it", "ik doe 'm"),
    "b_nswap": ("swap", "ruilen"),
    "b_nin": ("🚫 i'm in", "🚫 ik kan toch"),
    "b_back": ("← back", "← terug"),
}
LANGS = ("en", "nl")

# ---------- storage ----------

TABLES = {
    "nights": "day TEXT, chore TEXT DEFAULT 'dogs', walker INTEGER, status TEXT, cant TEXT DEFAULT '', "
              "msg INTEGER, done_at TEXT, PRIMARY KEY(day, chore)",
    "overrides": "day TEXT, chore TEXT DEFAULT 'dogs', walker INTEGER, PRIMARY KEY(day, chore)",
    "weekmsg": "id INTEGER PRIMARY KEY, msg INTEGER, page INTEGER, day TEXT, sig TEXT",
}

def connect(path=DB):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY, name TEXT, role TEXT, joined INTEGER, lang TEXT DEFAULT 'en');
    CREATE TABLE IF NOT EXISTS off(id INTEGER, day TEXT, PRIMARY KEY(id, day));
    CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
    """)
    migrate(db)
    for table, cols in TABLES.items(): db.execute(f"CREATE TABLE IF NOT EXISTS {table}({cols})")
    return db

def migrate(db):
    """Pre-dishes databases: add the chore column (existing rows are dogs)."""
    for table, cols in (("nights", "day, walker, status, cant, msg, done_at"), ("overrides", "day, walker")):
        have = [c[1] for c in db.execute(f"PRAGMA table_info({table})")]
        if not have or "chore" in have: continue
        db.execute(f"ALTER TABLE {table} RENAME TO old_{table}")
        db.execute(f"CREATE TABLE {table}({TABLES[table]})")
        db.execute(f"INSERT INTO {table}({cols}) SELECT {cols} FROM old_{table}")
        db.execute(f"DROP TABLE old_{table}")
    db.commit()

def kv(db, k, v=None):
    if v is not None:
        db.execute("REPLACE INTO kv VALUES(?,?)", (k, v)); db.commit(); return v
    r = db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r and r[0]

def members(db, role):
    return db.execute("SELECT * FROM members WHERE role=? ORDER BY joined", (role,)).fetchall()

def col(db, uid, column):
    r = db.execute(f"SELECT {column} FROM members WHERE id=?", (uid,)).fetchone()
    return r and r[0]

def name(db, uid): return col(db, uid, "name") or "?"

# ---------- rotation ----------

def walks_in_month(db, uid, day, chore="dogs"):
    return db.execute("SELECT COUNT(*) FROM nights WHERE walker=? AND chore=? AND status='done' AND substr(day,1,7)=?",
                      (uid, chore, day.isoformat()[:7])).fetchone()[0]

def is_off(db, uid, day):
    return db.execute("SELECT 1 FROM off WHERE id=? AND day=?", (uid, day.isoformat())).fetchone() is not None

def pick(db, day, last=None, extra_counts=None):
    """Walker for `day`. `last` = who walked the previous night (defaults to history)."""
    o = db.execute("SELECT walker FROM overrides WHERE day=? AND chore='dogs'", (day.isoformat(),)).fetchone()
    if o: return o[0]
    w = [m["id"] for m in members(db, "walker")]
    if not w: return None
    if len(w) == 1: return w[0]
    a, b = w[:2]
    if last is None:
        r = db.execute("SELECT walker FROM nights WHERE day<? AND chore='dogs' AND walker IS NOT NULL ORDER BY day DESC LIMIT 1",
                       (day.isoformat(),)).fetchone()
        last = r[0] if r else b
    base = a if last == b else b
    other = a if base == b else b
    off_base, off_other = is_off(db, base, day), is_off(db, other, day)
    if off_base and not off_other: return other
    if off_base and off_other:
        c = extra_counts or {}
        cb, co = walks_in_month(db, base, day) + c.get(base, 0), walks_in_month(db, other, day) + c.get(other, 0)
        return other if co < cb else base
    return base

def week(db, today, n=7, skip=0):
    """Planned walker per night for `n` nights starting `skip` days after today."""
    out, last, counts = [], None, {}
    for i in range(skip + n):
        d = today + timedelta(days=i)
        row = db.execute("SELECT walker FROM nights WHERE day=? AND chore='dogs'", (d.isoformat(),)).fetchone()
        uid = row[0] if row else pick(db, d, last, counts)
        counts[uid] = counts.get(uid, 0) + 1
        out.append((d, uid)); last = uid or last
    return out[skip:]

def dishes(db, day, dog, sent=True):
    """Dishes go to whoever isn't on dogs, unless they're off and the dog walker isn't.
    sent=False ignores a dishes message already out, to see who should have it now."""
    for table in ("nights", "overrides")[0 if sent else 1:]:
        r = db.execute(f"SELECT walker FROM {table} WHERE day=? AND chore='dishes'", (day.isoformat(),)).fetchone()
        if r: return r[0]
    o = next((m["id"] for m in members(db, "walker") if m["id"] != dog), None)
    if not o or (is_off(db, o, day) and not is_off(db, dog, day)): return dog
    return o

# ---------- parser ----------

WD = {"mon": 0, "monday": 0, "ma": 0, "maandag": 0, "tue": 1, "tues": 1, "tuesday": 1, "di": 1, "dinsdag": 1,
      "wed": 2, "wednesday": 2, "wo": 2, "woensdag": 2, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
      "do": 3, "donderdag": 3, "fri": 4, "friday": 4, "vr": 4, "vrijdag": 4, "sat": 5,
      "saturday": 5, "za": 5, "zaterdag": 5, "sun": 6, "sunday": 6, "zo": 6, "zondag": 6}
MONTHS = {m: i + 1 for i, ms in enumerate(["jan", "feb", "mar maa", "apr", "may mei", "jun", "jul", "aug",
          "sep", "oct okt", "nov", "dec"]) for m in ms.split()}

RANGE_WORDS = r"(?:-|to|t/m|tm|tot|until|till|through)"

def date_range(a, b):
    return [a + timedelta(days=i) for i in range(min((b - a).days + 1, 60))]

def parse_ranges(t, today):
    """Expand ranges; return (days, text with ranges removed)."""
    days = []
    def wd(m):
        a, b = m.group(1), m.group(2)
        if a not in WD or b not in WD or len(a) < 3 or len(b) < 3: return m.group(0)
        start = today + timedelta(days=(WD[a] - today.weekday()) % 7)
        days.extend(date_range(start, start + timedelta(days=(WD[b] - WD[a]) % 7)))
        return " "
    def dd(m):
        d1, m1, d2, m2 = int(m.group(1)), MONTHS.get((m.group(2) or "")[:3]), int(m.group(3)), MONTHS.get(m.group(4)[:3])
        if not m2 or (m.group(2) and not m1): return m.group(0)
        m1 = m1 or (m2 if d1 <= d2 else m2 - 1 or 12)
        try:
            b = date(today.year, m2, d2)
            if b < today: b = b.replace(year=b.year + 1)
            a = date(b.year - (m1 > m2), m1, d1)
        except ValueError:
            return m.group(0)
        days.extend(d for d in date_range(a, b) if d >= today)
        return " "
    t = re.sub(r"\b(\d{1,2})(?:\s+([a-z]{3})[a-z]*)?\s*%s\s*(\d{1,2})\s+([a-z]+)" % RANGE_WORDS, dd, t)
    t = re.sub(r"\b([a-z]+)\s*%s\s*([a-z]+)\b" % RANGE_WORDS, wd, t)
    m = re.search(r"\b(?:tot|t/m|tm|until|till|through)\b(.*)", t)
    if m:
        end = parse_days(m.group(1), today)
        if end:
            start = parse_days(t[:m.start()], today)
            days.extend(date_range(start[0] if start else today, end[-1]))
            t = " "
    return days, t

def parse_days(text, today):
    found = set()
    days, t = parse_ranges(text.lower(), today)
    found.update(days)
    def add(d):
        if d >= today: found.add(d)
    if re.search(r"\b(tonight|today|vanavond|vandaag)\b", t): add(today)
    if re.search(r"\b(tomorrow|tmrw|morgen)\b", t): add(today + timedelta(days=1))
    if re.search(r"\b(weekend|wknd)\b", t):
        sat = today + timedelta(days=(5 - today.weekday()) % 7)
        if today.weekday() == 6: sat = today - timedelta(days=1)
        add(sat); add(sat + timedelta(days=1))
    nxt = re.search(r"\b(next week|volgende week)\b", t)
    for w in re.findall(r"[a-z]+", t):
        if w in WD and not (w in ("do", "ma", "di", "zo") and not re.search(r"\b%s\b(?!\s+[a-z]{3,})" % w, t)):
            if nxt: add(today + timedelta(days=7 - today.weekday() + WD[w]))
            else: add(today + timedelta(days=(WD[w] - today.weekday()) % 7))
    def month_day(dn, mo):
        try:
            d = date(today.year, mo, dn)
        except ValueError:
            return
        if d < today: d = d.replace(year=today.year + 1)
        add(d)
    for dn, mo in re.findall(r"\b(\d{1,2})[/-](\d{1,2})\b", t): month_day(int(dn), int(mo))
    for dn, mn in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th|e)?\s+([a-z]{3})", t):
        if mn in MONTHS: month_day(int(dn), MONTHS[mn])
    for mn, dn in re.findall(r"\b([a-z]{3})[a-z]*\s+(\d{1,2})\b", t):
        if mn in MONTHS: month_day(int(dn), MONTHS[mn])
    mon = "(?:" + "|".join(MONTHS) + ")"
    t2 = re.sub(r"\b\d{1,2}[/-]\d{1,2}\b|\b\d{1,2}(?:st|nd|rd|th|e)?\s+%s|\b%s[a-z]*\s+\d{1,2}\b" % (mon, mon), "", t)
    for dn in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th|e)?\b", t2):
        dn = int(dn)
        if 1 <= dn <= 31:
            y, m = today.year, today.month
            if dn < today.day: m, y = (1, y + 1) if m == 12 else (m + 1, y)
            try: add(date(y, m, dn))
            except ValueError: pass
    return sorted(found)

SELF_CLAIM = r"\b(i do|i'll do|ill do|i take|i'll take|ill take|i've got|ik doe|ik neem|ik pak)\b"
OTHER_CLAIM = r"\b(takes|does|has|doet|neemt|pakt)\b"

def parse_claim(text, me, other, other_name):
    """Who `text` assigns nights to, or None if it isn't a scheduling message."""
    t = text.lower()
    if re.search(SELF_CLAIM, t): return me
    m = re.search(r"\b([a-z]+)\s+" + OTHER_CLAIM[2:], t)
    if m and other and m.group(1) in (other_name.lower(), "he", "hij"): return other

def tr(lang, key, **kw):
    v = S[key]
    return (v if isinstance(v, str) else v[LANGS.index(lang)]).format(**kw)

def fmt(d, lang="en"): return f"{tr(lang, 'days').split()[d.weekday()]} {d.day}"

def month(d, lang): return tr(lang, "months").split()[d.month - 1]

def fmt_days(days, lang):
    """'Fri 16, Sat 17', or with months when they differ: 'Wed 30 Dec, Fri 1 Jan'."""
    both = len({d.month for d in days}) > 1
    return ", ".join(fmt(d, lang) + (f" {month(d, lang)}" if both else "") for d in days)

def at(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)

def can_pass(day, t, chore="dogs"): return t < at(day, CHORES[chore][1])

def done_open(day, t): return t < at(day + timedelta(days=1), DONE_UNTIL)

def overdue(db, t, chore="dogs"):
    """Tonight's chore if past its cutoff, not done, and parents not yet told."""
    n = not can_pass(t.date(), t, chore) and night(db, t.date(), chore)
    return n if n and n["status"] == "on" and not kv(db, f"late_{chore}_{t.date()}") else None

def owner(db, day, today):
    return dict(week(db, today, n=(day - today).days + 1)).get(day)

def night(db, day, chore="dogs"):
    return db.execute("SELECT * FROM nights WHERE day=? AND chore=?", (day.isoformat(), chore)).fetchone()

# ---------- intent ----------

OFF_WORDS = r"\b(not|can't|cant|cannot|busy|away|off|out|niet|weg|vakantie|druk|bezet)\b"
WALK_WORDS = SELF_CLAIM[:-3] + r"|i can|can do|lopen|walk)\b"
MIXED = r"\b(but|maar|wel)\b"

def intent(text, me, other, other_name):
    """('off'|'walk', walker), or (None, None) when unclear or mixed."""
    t = text.lower()
    off, walk = re.search(OFF_WORDS, t), re.search(WALK_WORDS, t)
    target = parse_claim(text, me, other, other_name)
    if re.search(MIXED, t) or (off and (walk or target)): return None, None
    if target: return "walk", target
    if walk: return "walk", me
    if off: return "off", me
    return None, None

def apply_off(db, uid, days):
    db.executemany("INSERT OR IGNORE INTO off VALUES(?,?)", [(uid, d.isoformat()) for d in days])
    db.executemany("DELETE FROM overrides WHERE day=? AND walker=?", [(d.isoformat(), uid) for d in days])
    db.commit()

def clear_off(db, uid, days):
    db.executemany("DELETE FROM off WHERE id=? AND day=?", [(uid, d.isoformat()) for d in days]); db.commit()

def apply_claim(db, target, days, chore="dogs"):
    """Pin `chore` to `target`. Pinning dogs drops any dishes pin so dishes follow the other walker again."""
    if chore == "dogs":
        db.executemany("DELETE FROM overrides WHERE day=? AND chore='dishes'", [(d.isoformat(),) for d in days])
    db.executemany("REPLACE INTO overrides(day, chore, walker) VALUES(?,?,?)",
                   [(d.isoformat(), chore, target) for d in days]); db.commit()

# ---------- telegram ----------

TOKEN = os.environ.get("DOGS_TELEGRAM_BOT_TOKEN", "")
def env_ids(var): return [int(x) for x in os.environ.get(var, "").split(",") if x.strip()]
WALKER_IDS = env_ids("WALKER_IDS")  # Telegram user ids of the two walkers, Michael first
PARENT_IDS = env_ids("PARENT_IDS")  # Telegram user ids of the parents
RETRY = (0, 1, 3, 9)  # seconds between send attempts
MAX_PAGE = 1          # /week pages: this week and next
AHEAD = 14            # planning horizon in days

def log(*a): print(datetime.now(TZ).strftime("%F %T"), *a, file=sys.stderr, flush=True)

def api(method, **params):
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}",
                                 data=json.dumps(params).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)["result"]

def send(chat, text, markup=None, html=False):
    """Message id; False if the user blocked or never started the bot (403); None on other failures."""
    p = {"chat_id": chat, "text": text, **({"reply_markup": markup} if markup else {}), **({"parse_mode": "HTML"} if html else {})}
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

def edit(chat, msg, text, markup=None, html=False):
    """True if shown; False if the message is gone; None on other failures."""
    try:
        api("editMessageText", chat_id=chat, message_id=msg, text=text,
            **({"reply_markup": markup} if markup else {}), **({"parse_mode": "HTML"} if html else {}))
        return True
    except urllib.error.HTTPError as e:
        body = e.read()
        if b"not modified" in body: return True
        log("edit", chat, e.code)
        return False if b"not found" in body else None
    except Exception as e:
        log("edit", chat, e)

def now(): return datetime.now(TZ)

def lang_of(db, uid):
    lang = col(db, uid, "lang")
    return lang if lang in LANGS else "en"

def say(db, uid, key, markup=None, **kw):
    return send(uid, tr(lang_of(db, uid), key, **kw), markup)

def tell(db, chat, msg, key, markup=None, **kw):
    edit(chat, msg, tr(lang_of(db, chat), key, **kw), markup)

def tell_parents(db, key, markup=None, **kw):
    for p in members(db, "parent"):
        r = say(db, p["id"], key, markup, **kw)
        log("parent", p["id"], key, {False: "BLOCKED", None: "FAILED"}.get(r, "sent"))

STYLE = {  # Telegram button colours: success = go, danger = stop, primary = pick/navigate
    "done": "success", "cant": "danger", "confirm": "success", "off": "danger", "walk": "primary",
    "accept": "success", "no": "danger", "pcover": "success", "plan": "primary",
    "noff": "danger", "nin": "success", "ntake": "success", "nswap": "primary",
}

def btn(lang, key, data):
    """One inline button: label from S, colour from STYLE (none for neutral keys like nah / back)."""
    b = {"text": tr(lang, "b_" + key), "callback_data": data}
    return {**b, "style": STYLE[key]} if key in STYLE else b

def buttons(db, uid, *keys):
    lang = lang_of(db, uid)
    return {"inline_keyboard": [[btn(lang, k, k) for k in keys]]}

def other_walker(db, uid):
    return next((m["id"] for m in members(db, "walker") if m["id"] != uid), None)

def role_of(db, uid): return col(db, uid, "role")

def pending(db, uid, msg, value=None):
    """Data behind a message's buttons. Read once: reading deletes it."""
    k = f"p_{uid}_{msg}"
    if value is not None: return kv(db, k, json.dumps(value))
    v = kv(db, k)
    db.execute("DELETE FROM kv WHERE k=?", (k,)); db.commit()
    return v and json.loads(v)

def all_pending(db):
    return [(k, json.loads(v)) for k, v in db.execute("SELECT k, v FROM kv WHERE k LIKE 'p\\_%' ESCAPE '\\'")]

def swap_valid(db, p, t):
    """A swap request dies at 23:00 on its first night, or once any night changed hands."""
    days = [date.fromisoformat(d) for d in p["owners"]]
    return can_pass(min(days), t) and all(owner(db, d, t.date()) == p["owners"][d.isoformat()] for d in days)

def prune(db, t):
    db.execute("DELETE FROM kv WHERE k LIKE 'late\\_%' ESCAPE '\\' AND substr(k, -10) < ?",
               ((t.date() - timedelta(days=1)).isoformat(),))
    for k, p in all_pending(db):
        stale = not swap_valid(db, p, t) if p["type"] == "swap" else max(p["days"]) < t.date().isoformat()
        if stale: db.execute("DELETE FROM kv WHERE k=?", (k,))
    db.commit()

def lang_view(lang):
    return tr(lang, "lang"), {"inline_keyboard": [[
        {"text": ("✓ " if l == lang else "") + label, "callback_data": "lang:" + l}
        for l, label in zip(LANGS, ("English", "Nederlands"))]]}

def day_style(db, uid, d, w):
    """Week-view day colour for a walker: red = you're off that day, green = your night, neutral otherwise."""
    if is_off(db, uid, d): return "danger"
    return "success" if w == uid else None

def week_view(db, today, lang="en", page=0, uid=None):
    """Overview as text (one line per night, today bold), days as compact buttons, 4 per row."""
    rows = week(db, today, skip=7 * page)
    swaps = {d for _, p in all_pending(db) if p["type"] == "swap" for d in p["owners"]}
    a, b = rows[0][0], rows[-1][0]
    m = lambda d: month(d, lang).lower()
    span = f"{a.day}–{b.day} {m(b)}" if a.month == b.month else f"{a.day} {m(a)}–{b.day} {m(b)}"
    lines = [f"<b>{tr(lang, 'week', span=span)}</b>"]
    if len(members(db, "walker")) < 2: lines.append(f"<i>{tr(lang, 'solo')}</i>")
    lines.append("")
    for d, w in rows:
        who = tr(lang, "you") if w == uid else html.escape(name(db, w)) if w else "—"
        off = " 🚫" if any(is_off(db, x["id"], d) for x in members(db, "walker")) else ""
        line = f"{fmt(d, lang).lower()}  {'⇄ ' if d.isoformat() in swaps else ''}{who}{off}"
        lines.append(f"<b>{line}</b>" if d == today else line)
    def day_btn(d, w):
        b = {"text": fmt(d, lang).lower(), "callback_data": f"wk:{d}:{page}"}
        s = day_style(db, uid, d, w) if uid else None
        return {**b, "style": s} if s else b
    days = [day_btn(d, w) for d, w in rows]
    nav = {"text": tr(lang, "b_next"), "callback_data": "wp:1"} if page == 0 else {"text": tr(lang, "b_prev"), "callback_data": "wp:0"}
    return "\n".join(lines), {"inline_keyboard": [days[:4], days[4:], [nav]]}

def night_view(db, uid, day, page):
    """One night: who's on what, and only the buttons that apply."""
    t, lang = now(), lang_of(db, uid)
    cb = lambda k, style: {"text": tr(lang, "b_" + k), "callback_data": f"{k}:{day}:{page}", "style": style}
    cur, other = owner(db, day, t.date()), other_walker(db, uid)
    who = lambda w: tr(lang, "you") if w == uid else html.escape(name(db, w)) if w else "—"
    dish = dishes(db, day, cur) if cur else None
    text = f"<b>{fmt(day, lang).lower()}</b>\n🐕 {who(cur)}\n🍽 {who(dish if other else None)}"
    if is_off(db, uid, day): text += f"\n🚫 {tr(lang, 'you')}"
    acts = [cb("nin", "success")] if is_off(db, uid, day) else [cb("noff", "danger")]
    if not cur: acts.append(cb("ntake", "success"))
    elif cur != uid or not is_off(db, other, day): acts.append(cb("nswap", "primary"))
    # One action per row: big full-width targets on iPhone and Mac, back last.
    return text, {"inline_keyboard": [[a] for a in acts] + [[{"text": tr(lang, "b_back"), "callback_data": f"wp:{page}"}]]}

def view(db, uid, page, day=None):
    t = now()
    if day and (day < t.date() or not can_pass(day, t)): day = None
    return night_view(db, uid, day, page) if day else week_view(db, t.date(), lang_of(db, uid), page, uid)

def show(db, uid, msg, page, day=None):
    """Edit a week message in place; the latest one per member is tracked for live updates."""
    text, kb = view(db, uid, page, day)
    r = edit(uid, msg, text, kb, html=True)
    db.execute("UPDATE weekmsg SET page=?, day=?, sig=? WHERE id=? AND msg=?",
               (page, day and day.isoformat(), text + json.dumps(kb), uid, msg)); db.commit()
    return r

def open_week(db, uid):
    """/week: a fresh message at the bottom; the old one is deleted."""
    old = db.execute("SELECT msg FROM weekmsg WHERE id=?", (uid,)).fetchone()
    if old:
        try: api("deleteMessage", chat_id=uid, message_id=old["msg"])
        except Exception as e: log("delete", uid, e)
    text, kb = view(db, uid, 0)
    m = send(uid, text, kb, html=True)
    if m: db.execute("REPLACE INTO weekmsg(id, msg, page, day, sig) VALUES(?,?,0,NULL,?)", (uid, m, text + json.dumps(kb))); db.commit()

def refresh_weeks(db):
    """Re-render every tracked week message; edit only the ones that changed."""
    for r in db.execute("SELECT * FROM weekmsg").fetchall():
        day = r["day"] and date.fromisoformat(r["day"])
        text, kb = view(db, r["id"], r["page"], day)
        if text + json.dumps(kb) == r["sig"]: continue
        if show(db, r["id"], r["msg"], r["page"], day) is False:
            db.execute("DELETE FROM weekmsg WHERE id=?", (r["id"],)); db.commit()

def set_night(db, day, chore, **cols):
    db.execute(f"UPDATE nights SET {', '.join(c + '=?' for c in cols)} WHERE day=? AND chore=?",
               (*cols.values(), day, chore)); db.commit()

def K(key, chore):
    """String key for a chore: the '_dishes' variant when one exists."""
    return key + "_dishes" if chore == "dishes" and key + "_dishes" in S else key

def chore_buttons(db, uid, chore):
    """Done and Can't stacked full width: the two things a walker taps each night, each a big target."""
    lang = lang_of(db, uid)
    return {"inline_keyboard": [[btn(lang, k, f"{k}:{chore}")] for k in ("done", "cant")]}

def plan_button(lang):
    return btn(lang, "plan", "plan")

def say_on(db, uid, day, chore, key="on", **kw):
    """Tonight's chore message; the first one notes when both walkers are marked off."""
    lang, d = lang_of(db, uid), date.fromisoformat(day)
    walkers = members(db, "walker")
    both = key == "on" and len(walkers) == 2 and all(is_off(db, m["id"], d) for m in walkers)
    return send(uid, tr(lang, K(key, chore), **kw) + (tr(lang, K("both_off", chore)) if both else ""), chore_buttons(db, uid, chore))

def deliver(db, day, chore, uid, key="on", **kw):
    """Send tonight's message. Network trouble: leave msg empty so the next tick retries.
    Blocked (403): tell parents and hand the chore to the other walker."""
    msg = say_on(db, uid, day, chore, key, **kw)
    if msg is not False: return set_night(db, day, chore, walker=uid, msg=msg)
    tell_parents(db, "unreachable", name=name(db, uid))
    o = other_walker(db, uid)
    if o and key == "on": return deliver(db, day, chore, o, "on_unreachable", name=name(db, uid))
    set_night(db, day, chore, status="nobody", walker=None)
    tell_parents(db, K("nobody_parents", chore))

def nightly(db, t, chore):
    """Tonight's message from its send time until the cutoff. The stored msg id is the sent flag.
    If the bot was down all evening, a row is still made at the cutoff so parents get the late alert."""
    if (t.hour, t.minute) < CHORES[chore][0]: return
    day = t.date().isoformat()
    n = night(db, t.date(), chore)
    if not n:
        dog = dict(week(db, t.date(), n=1)).get(t.date())
        uid = dog if chore == "dogs" else dog and dishes(db, t.date(), dog)
        if uid is None: return
        db.execute("INSERT INTO nights(day, chore, walker, status) VALUES(?,?,?,'on')", (day, chore, uid)); db.commit()
        n = night(db, t.date(), chore)
    if not n["msg"] and n["status"] == "on" and can_pass(t.date(), t, chore): deliver(db, day, chore, n["walker"])

def missed_yesterday(db, t):
    """Bot was down through all of last night: tell parents once."""
    y = t.date() - timedelta(days=1)
    first = db.execute("SELECT MIN(joined) FROM members WHERE role='walker'").fetchone()[0]
    if night(db, y) or not first or first > at(y, CHORES["dogs"][1]).timestamp(): return
    db.execute("INSERT INTO nights(day, chore, status) VALUES(?, 'dogs', 'missed')", (y.isoformat(),)); db.commit()
    tell_parents(db, "missed")

def tick(db, t):
    missed_yesterday(db, t)
    for chore in CHORES:
        nightly(db, t, chore)
        if overdue(db, t, chore):
            kv(db, f"late_{chore}_{t.date()}", "1")
            for p in members(db, "parent"):
                say(db, p["id"], K("late", chore), {"inline_keyboard": [[
                    btn(lang_of(db, p["id"]), "pcover", f"pcover:{chore}:{t.date()}")]]})
    prune(db, t)

def pass_night(db, n, uid, chat=None, msg=None, answer=None):
    """uid can't do tonight's chore: hand it to the other walker, or tell everyone nobody's free.
    Network trouble reaching the other walker changes nothing; uid is asked to try again."""
    chore, cant = n["chore"], set(filter(None, n["cant"].split(","))) | {str(uid)}
    chat, msg = chat or uid, msg or n["msg"]
    o = other_walker(db, uid)
    new = say_on(db, o, n["day"], chore, "on_passed", name=name(db, uid)) if o and str(o) not in cant else 0
    if new is None or new is False:
        if new is False: tell_parents(db, "unreachable", name=name(db, o))
        key = "retry" if new is None else "cant_reach"
        return answer(key, name=name(db, o)) if answer else say(db, uid, key, name=name(db, o))
    if new:
        set_night(db, n["day"], chore, walker=o, msg=new, cant=",".join(cant))
        return tell(db, chat, msg, "passed", name=name(db, o))
    set_night(db, n["day"], chore, status="nobody", walker=None, cant=",".join(cant))
    tell(db, chat, msg, "nobody")
    if o: say(db, o, K("nobody_either", chore), name=name(db, uid))
    tell_parents(db, K("nobody_parents", chore))

def move_tonight(db, n, new):
    """Tonight's message already went out: pass it to `new`."""
    if n["walker"] == new: return
    if n["walker"] and n["msg"]: tell(db, n["walker"], n["msg"], "passed", name=name(db, new))
    set_night(db, n["day"], n["chore"], walker=new, status="on", msg=say_on(db, new, n["day"], n["chore"]) or None)

def on_button(db, q):
    """Handle the tap first, answer Telegram last: a failed answer (e.g. query too old) never loses the tap."""
    lang, reply = lang_of(db, q["from"]["id"]), {}
    def answer(key=None, **kw):
        if key: reply["text"] = tr(lang, key, **kw)
    try:
        handle_button(db, q, answer)
    except (ValueError, KeyError, IndexError) as e:  # malformed or outdated callback_data
        reply["text"] = tr(lang, "old")
        log("callback", q.get("data"), repr(e))
    except Exception:
        reply["text"] = tr(lang, "error")
        raise
    finally:
        try: api("answerCallbackQuery", callback_query_id=q["id"], **reply)
        except Exception as e: log("answer", e)

def handle_button(db, q, answer):
    uid, data = q["from"]["id"], q["data"]
    chat, msg = q["message"]["chat"]["id"], q["message"]["message_id"]
    lang, today = lang_of(db, uid), now().date()
    kind, _, arg = data.partition(":")
    if kind == "lang":
        arg = arg if arg in LANGS else "en"
        db.execute("UPDATE members SET lang=? WHERE id=?", (arg, uid)); db.commit()
        answer()
        return edit(chat, msg, *lang_view(arg))
    if kind == "wk":
        day, page = arg.split(":")
        return on_week_tap(db, uid, date.fromisoformat(day), chat, msg, answer, int(page))
    if kind == "plan":
        answer()
        return open_week(db, uid)
    if kind in ("noff", "ntake", "nswap", "nin"):
        day, page = arg.split(":")
        return on_night_action(db, uid, kind, date.fromisoformat(day), chat, msg, answer, int(page))
    if kind == "wp":
        answer()
        return show(db, uid, msg, min(max(int(arg), 0), MAX_PAGE))
    if kind in ("accept", "no"):
        return on_swap_reply(db, uid, kind == "accept", chat, msg, answer)
    if kind in ("confirm", "cancel", "off", "walk"):
        return on_preview(db, uid, kind, today, chat, msg, answer)
    if kind == "pcover":
        return on_parent_cover(db, uid, arg, chat, msg, answer)
    chore = arg or "dogs"
    n = db.execute("SELECT * FROM nights WHERE msg=? AND walker=? AND chore=?", (msg, uid, chore)).fetchone()
    if not n or n["status"] != "on": return answer()
    day, t = date.fromisoformat(n["day"]), now()
    if not done_open(day, t): return answer("old")
    if kind == "cant":
        return pass_night(db, n, uid, chat, msg, answer) if can_pass(day, t, chore) else answer("too_late")
    hm = t.strftime("%H:%M")
    set_night(db, n["day"], chore, status="done", done_at=hm)
    tell(db, chat, msg, K("walked", chore), hm=hm)
    if chore == "dogs": tell_parents(db, "parent_done", name=name(db, uid), hm=hm)

def ask(db, frm, to, days, back=None):
    """Ask the walker who isn't `frm` to agree that `to` walks `days`. Returns say()'s result."""
    rcpt, t = other_walker(db, frm), now()
    m = say(db, rcpt, "ask_take" if to == rcpt else "ask_give", buttons(db, rcpt, "accept", "no"),
            name=name(db, frm), day=fmt_days(days, lang_of(db, rcpt)))
    if not m: return m
    pending(db, rcpt, m, {"type": "swap", "from": frm, "to": to, "back": back,
                          "owners": {d.isoformat(): owner(db, d, t.date()) for d in days}})
    return m

def night_open(db, uid, day, answer):
    """Can uid still change this night? Answers the tap when not."""
    t = now()
    if day < t.date() or day >= t.date() + timedelta(days=AHEAD): return answer("old")
    if role_of(db, uid) != "walker": return answer()
    if not can_pass(day, t): return answer("too_late")
    n = night(db, day)
    if n and n["status"] not in ("on", "nobody"): return answer("settled")
    return True

def on_week_tap(db, uid, day, chat, msg, answer, page):
    if not night_open(db, uid, day, answer): return
    answer()
    show(db, uid, msg, page, day)

def on_night_action(db, uid, kind, day, chat, msg, answer, page):
    if not night_open(db, uid, day, answer): return
    t, lang = now(), lang_of(db, uid)
    if kind == "nswap": return ask_swap(db, uid, day, chat, msg, answer, page)
    if kind == "noff": confirm_off(db, uid, [day])
    elif kind == "nin": undo_off(db, uid, day)
    else: take_empty(db, uid, day)
    answer("taken", day=fmt(day, lang)) if kind == "ntake" else answer("saved")
    show(db, uid, msg, page)

def undo_off(db, uid, day):
    """Back in: tonight's live dishes return to whoever the rota now picks."""
    clear_off(db, uid, [day])
    dog, dish = night(db, day), night(db, day, "dishes")
    if dish and dish["msg"] and dish["status"] == "on" and can_pass(day, now(), "dishes"):
        move_tonight(db, dish, dishes(db, day, dog["walker"] if dog else owner(db, day, now().date()), sent=False))

def take_empty(db, uid, day):
    n = night(db, day)
    if owner(db, day, now().date()): return
    apply_claim(db, uid, [day])
    if n: set_night(db, n["day"], "dogs", walker=uid, status="on", msg=None, cant="")

def ask_swap(db, uid, day, chat, msg, answer, page):
    t, cur, other = now(), owner(db, day, now().date()), other_walker(db, uid)
    if not other: return answer()
    m = ask(db, uid, other_walker(db, cur), [day], [chat, msg, page])
    if not m: return answer("retry" if m is None else "cant_reach", name=name(db, other))
    answer("asked", name=name(db, other))
    show(db, uid, msg, page)

def on_swap_reply(db, uid, ok, chat, msg, answer):
    p, t = pending(db, uid, msg), now()
    if not p or not swap_valid(db, p, t):
        answer("old")
        return tell(db, chat, msg, "old")
    answer()
    days, req = [date.fromisoformat(d) for d in p["owners"]], p["from"]
    lang = lang_of(db, req)
    if not ok:
        tell(db, chat, msg, "declined")
        return say(db, req, "req_no", name=name(db, uid), day=fmt_days(days, lang))
    clear_off(db, p["to"], days)
    apply_claim(db, p["to"], days)  # dishes follow: they go to whoever isn't on dogs
    for chore in CHORES:
        n = night(db, t.date(), chore)
        who = p["to"] if chore == "dogs" else dishes(db, t.date(), p["to"], sent=False)
        if n and t.date() in days and n["msg"] and n["status"] == "on" and can_pass(t.date(), t, chore):
            move_tonight(db, n, who)
    dogs_only = t.date() in days and not can_pass(t.date(), t, "dishes")  # tonight's dishes are already history
    tell(db, chat, msg, "swapped_dogs" if dogs_only else "swapped", day=fmt_days(days, lang_of(db, uid)), walker=name(db, p["to"]))
    say(db, req, "req_yes", name=name(db, uid), day=fmt_days(days, lang), walker=name(db, p["to"]))
    if p["back"]: show(db, req, p["back"][1], p["back"][2])

def preview(db, uid, off, walk, target, msg=None):
    lang = lang_of(db, uid)
    lines = ([tr(lang, "preview_off", days=fmt_days(off, lang))] if off else []) + \
            ([tr(lang, "preview_claim", name=name(db, target), days=fmt_days(walk, lang))] if walk else [])
    kb = buttons(db, uid, "confirm", "cancel")
    if msg: edit(uid, msg, "\n".join(lines), kb)
    else: msg = send(uid, "\n".join(lines), kb)
    pending(db, uid, msg, {"type": "preview", "target": target,
                           "off": [d.isoformat() for d in off], "walk": [d.isoformat() for d in walk],
                           "days": [d.isoformat() for d in off + walk]})

def ask_day(db, uid, p, msg=None):
    """Unclear message: ask Off or Walk for each day in turn."""
    day = date.fromisoformat(p["days"][len(p["off"]) + len(p["walk"])])
    text, kb = tr(lang_of(db, uid), "which", day=fmt(day, lang_of(db, uid))), buttons(db, uid, "off", "walk")
    if msg: edit(uid, msg, text, kb)
    else: msg = send(uid, text, kb)
    pending(db, uid, msg, p)

def on_preview(db, uid, choice, today, chat, msg, answer):
    p = pending(db, uid, msg)
    if not p: return answer("old")
    answer()
    if choice == "cancel": return tell(db, chat, msg, "cancelled")
    if choice in ("off", "walk"):
        p[choice].append(p["days"][len(p["off"]) + len(p["walk"])])
        if len(p["off"]) + len(p["walk"]) < len(p["days"]): return ask_day(db, uid, p, msg)
    future = lambda key: [d for d in map(date.fromisoformat, p[key]) if d >= today]
    off, walk = future("off"), future("walk")
    if choice != "confirm": return preview(db, uid, off, walk, p.get("target", uid), msg)
    if off: confirm_off(db, uid, off)
    if walk and p["target"] == uid: confirm_walk(db, uid, walk)
    elif walk:
        free = [d for d in walk if not is_off(db, p["target"], d)]
        if not free: return tell(db, chat, msg, "target_off", name=name(db, p["target"]))
        m = ask(db, uid, p["target"], free)
        if not m:
            pending(db, uid, msg, p)  # keep the preview so Confirm can be tapped again
            return tell(db, chat, msg, "retry" if m is None else "cant_reach", buttons(db, uid, "confirm", "cancel"),
                        name=name(db, p["target"]))
        return tell(db, chat, msg, "asked", name=name(db, p["target"]))
    tell(db, chat, msg, "saved")

def confirm_off(db, uid, days):
    apply_off(db, uid, days)
    t = now()
    for chore in CHORES:
        n = night(db, t.date(), chore)
        if not (n and t.date() in days and n["walker"] == uid and n["status"] == "on" and can_pass(t.date(), t, chore)):
            continue
        if n["msg"]: pass_night(db, n, uid)
        else: set_night(db, n["day"], chore, walker=other_walker(db, uid) or uid)

def confirm_walk(db, uid, days):
    t = now()
    clear_off(db, uid, days)
    apply_claim(db, uid, [d for d in days if not night(db, d) or d == t.date()])
    n, dish = night(db, t.date()), night(db, t.date(), "dishes")
    if n and t.date() in days and n["walker"] != uid and n["status"] in ("on", "nobody") and can_pass(t.date(), t):
        move_tonight(db, n, uid)
    if dish and t.date() in days and dish["status"] == "on" and can_pass(t.date(), t, "dishes"):
        move_tonight(db, dish, dishes(db, t.date(), uid, sent=False))

def on_parent_cover(db, uid, arg, chat, msg, answer):
    chore, _, day = arg.rpartition(":")
    chore = chore if chore in CHORES else "dogs"
    n = night(db, date.fromisoformat(day), chore)
    if not n or n["status"] != "on" or not done_open(date.fromisoformat(day), now()):
        answer("sorted")
        return tell(db, chat, msg, "sorted")
    answer()
    who = name(db, uid)
    set_night(db, day, chore, status="parent", walker=None, done_at=now().strftime("%H:%M"))
    tell(db, chat, msg, "pcover_me")
    if n["walker"] and n["msg"]: tell(db, n["walker"], n["msg"], "pcover_live", name=who)
    for m in members(db, "walker") + members(db, "parent"):
        if m["id"] not in (n["walker"], uid): say(db, m["id"], K("pcover_all", chore), name=who)

def on_start(db, u, arg):
    """Start joins people on WALKER_IDS / PARENT_IDS. Anyone else gets the private note."""
    uid, first = u["id"], u.get("first_name") or "?"
    lang = "nl" if (u.get("language_code") or "").startswith("nl") else "en"
    if role_of(db, uid): return say(db, uid, "already_in")
    role = "walker" if uid in WALKER_IDS else "parent" if uid in PARENT_IDS else None
    if not role: return send(uid, tr(lang, "private"))
    db.execute("INSERT INTO members(id, name, role, joined, lang) VALUES(?,?,?,?,?)",
               (uid, first, role, int(time.time()), lang)); db.commit()
    if role == "parent":
        say(db, uid, "hi_parent")
    else:
        send(uid, tr(lang, "hi_walker", name=first), {"inline_keyboard": [[plan_button(lang)]]})
    for m in members(db, "walker") + (members(db, "parent") if role == "walker" else []):
        if m["id"] != uid: say(db, m["id"], "joined", name=first)

def on_text(db, msg):
    if "text" not in msg or "forward_origin" in msg or "forward_date" in msg: return  # stickers, photos, forwards
    u, text = msg["from"], msg["text"].strip()
    uid = u["id"]
    if msg["chat"]["type"] != "private": return
    if text.startswith("/start"): return on_start(db, u, text[6:].strip())
    role = role_of(db, uid)
    if not role: return send(uid, tr("en", "private"))
    lang, today = lang_of(db, uid), now().date()
    if text == "/lang": return send(uid, *lang_view(lang))
    if text == "/week": return open_week(db, uid)
    if text.startswith("/"): return say(db, uid, "commands")
    if role != "walker": return say(db, uid, "hi_parent")
    days = parse_days(text, today)
    if not days: return say(db, uid, "huh")
    days = [d for d in days if d < today + timedelta(days=AHEAD)]
    if not days: return say(db, uid, "too_far")
    o = other_walker(db, uid)
    kind, target = intent(text, uid, o, name(db, o) if o else "")
    if kind == "off": return preview(db, uid, days, [], uid)
    if kind == "walk": return preview(db, uid, [], days, target)
    if len(days) > 7: return say(db, uid, "huh")
    ask_day(db, uid, {"type": "ask", "target": uid, "off": [], "walk": [], "days": [d.isoformat() for d in days]})

def setup():
    """One-off bot profile: name and commands (en + nl)."""
    log("bot", api("getMe")["username"])
    api("setMyName", name="Honduitlaten")
    for lang, cmds in [(None, ("plan", "language")), ("nl", ("planning", "taal"))]:
        extra = {"language_code": lang} if lang else {}
        cmd = [{"command": c, "description": d} for c, d in zip(("week", "lang"), cmds)]
        api("setMyCommands", commands=cmd, **extra)

LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dogbot.lock")

def run():
    if not TOKEN: sys.exit("DOGS_TELEGRAM_BOT_TOKEN not set")
    lock = open(LOCK, "a+")
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: sys.exit(3)  # another instance is running; run.sh stops on 3
    lock.truncate(0); lock.write(str(os.getpid())); lock.flush()
    db = connect()
    log("polling")
    poll(db, 0)  # handle taps queued while down (e.g. Done) before tick() can send late alerts
    while True:
        try: tick(db, now()); refresh_weeks(db)
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
        try: refresh_weeks(db)
        except Exception as e: log("refresh", repr(e))

if __name__ == "__main__":
    setup() if sys.argv[1:] == ["setup"] else run()
