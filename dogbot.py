"""Dog-walk rotation bot. Telegram DMs, long polling, SQLite."""
import fcntl, html, json, os, re, secrets, signal, sqlite3, sys, time, urllib.error, urllib.request
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
    "b_confirm": ("Save changes", "Wijzigingen opslaan"),
    "b_cancel": ("Cancel", "Annuleren"),
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
    "late_dishes": ("dishes not confirmed yet", "afwas nog niet bevestigd"),
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
    "late": ("dog walk not confirmed yet", "honden uitlaten nog niet bevestigd"),
    "pcover_me": ("🙋 you're on it, thanks!", "🙋 jij doet 't, top!"),
    "pcover_all": ("{name}'s got the dogs tonight", "{name} doet de honden vanavond"),
    "pcover_live": ("{name}'s got it", "{name} doet 't"),
    "sorted": ("already sorted", "al geregeld"),
    "months": ("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec", "jan feb mrt apr mei jun jul aug sep okt nov dec"),
    "week": ("Planning · {span}", "Planning · {span}"),
    "you": ("you", "jij"),
    "solo": ("other walker's not in yet, you've got both", "andere loper zit er nog niet in, jij doet alles"),
    "too_far": ("Plan up to 30 days ahead. Choose dates within that month.", "Plan tot 30 dagen vooruit. Kies datums binnen die maand."),
    "b_next": ("next week ▶", "volgende week ▶"),
    "b_prev": ("◀ Previous week", "◀ Vorige week"),
    "full_parents": ("already 2 parents", "al 2 ouders"),
    "commands": ("/week · /lang", "/week · /lang"),
    "taken": ("{day}'s yours", "{day} is van jou"),
    "target_off": ("{name} can't then", "{name} kan dan niet"),
    "asked": ("asked {name}", "{name} gevraagd"),
    "ask_take": ("{name} asks: can you take the dogs on {day}? Dishes move to the other walker unless already done or past 21:00.", "{name} vraagt: kan jij de honden op {day} doen? De afwas gaat naar de ander, behalve als die al klaar is of na 21:00."),
    "ask_give": ("{name} wants to take the dogs on {day}. Dishes move to you unless already done or past 21:00. Agree?", "{name} wil de honden op {day} overnemen. De afwas gaat naar jou, behalve als die al klaar is of na 21:00. Akkoord?"),
    "declined": ("no swap", "niet geruild"),
    "req_yes": ("👍 {name} said yes, {day} goes to {walker}", "👍 {name} zei ja, {day} is voor {walker}"),
    "req_no": ("{name} said no to {day}", "{name} zei nee op {day}"),
    "preview_off": ("off: {days}", "kan niet: {days}"),
    "preview_claim": ("{name} walks: {days}", "{name} loopt: {days}"),
    "which": ("{day}: off or walking?", "{day}: kan je niet of loop je?"),
    "saved": ("👍 saved", "👍 opgeslagen"),
    "huh": ("didn't get that, try \"not fri\"", "snap 'm niet, probeer \"kan niet vr\""),
    "retry": ("couldn't reach {name}, try again", "{name} niet bereikt, nog een keer?"),
    "request_updated": ("The plan changed. Review the updated tasks, then accept.", "De planning veranderde. Bekijk de nieuwe taken en ga daarna akkoord."),
    "missed": ("last night's chores were not confirmed; check with each other", "de taken van gisteravond zijn niet bevestigd; stem dit even af"),
    "cant_reach": ("can't reach {name}", "{name} is onbereikbaar"),
    "error": ("oops, try again", "oeps, probeer nog eens"),
    "swapped": ("👍 {day} goes to {walker}", "👍 {day} is voor {walker}"),
    "swapped_dogs": ("🐕 {day} goes to {walker}", "🐕 {day} is voor {walker}"),
    "cancelled": ("cancelled", "geannuleerd"),
    "private": ("this bot's private", "deze bot is privé"),
    "already_in": ("you're already in, /week shows the plan", "je zit er al in, /week voor de planning"),
    "full": ("both spots are taken", "beide plekken zijn bezet"),
    "hi_walker": "Heyyy! dog and dish bot here 🐕 dishes 18:30, dogs 21:45, hit done when u did it, "
                 "can't just passes that one job on aha, other one taps start first 🙏",
    "hi_invite": ("\n/invite gets links for the others", "\n/invite geeft links voor de rest"),
    "hi_parent": "Heyyy! dog and dish bot here 🐕 you'll hear when the dogs are out, or if something's left",
    "joined": ("{name} joined", "{name} doet mee"),
    "invite": ("other walker:\n{w}\n\nparents:\n{p}\n\nThese links stay valid until you replace them in Family", "andere loper:\n{w}\n\nouders:\n{p}\n\nDeze links blijven geldig tot je ze in Gezin vervangt"),
    "lang": ("Language", "Taal"),
    "b_plan": ("📅 plan", "📅 planning"),
    "b_noff": ("i'm off", "ik kan niet"),
    "b_ntake": ("i'll take it", "ik doe 'm"),
    "b_nswap": ("swap", "ruilen"),
    "b_nin": ("🚫 i'm in", "🚫 ik kan toch"),
    "b_back": ("← back", "← terug"),
}
S.update({
    "b_home": ("🏠 Today", "🏠 Vandaag"),
    "b_help": ("How it works", "Hoe werkt het?"),
    "b_language": ("Language", "Taal"),
    "b_points": ("Points", "Punten"),
    "points_title": ("Points · {month} {year}", "Punten · {month} {year}"),
    "points_rule": ("1 point for each completed chore. Taking over counts once you tap Done.", "1 punt per afgeronde taak. Overnemen telt zodra je op Klaar tikt."),
    "points_own": ("Your points this month: {points}", "Jouw punten deze maand: {points}"),
    "points_total": ("{name}: {points}", "{name}: {points}"),
    "b_invite": ("Invite family", "Gezin uitnodigen"),
    "b_plan": ("📅 Planning", "📅 Planning"),
    "b_nin": ("I'm available again", "Ik kan weer"),
    "b_nswap": ("Request swap", "Ruil aanvragen"),
    "today": ("Today · {day}", "Vandaag · {day}"),
    "dogs_label": ("🐕 Dogs", "🐕 Honden"),
    "dishes_label": ("🍽 Dishes", "🍽 Afwas"),
    "planned": ("planned", "gepland"),
    "waiting": ("still to do", "nog te doen"),
    "done_status": ("done {time}", "klaar {time}"),
    "parent_status": ("parent taking over, still to do", "ouder neemt over, nog te doen"),
    "unassigned": ("nobody assigned", "niemand ingedeeld"),
    "missed_status": ("completion not confirmed", "niet als klaar bevestigd"),
    "off_status": ("Unavailable: {names}", "Kan niet: {names}"),
    "pending_status": ("⇄ Swap awaiting a reply", "⇄ Ruil wacht op antwoord"),
    "swap_scope": ("A planning swap changes dogs and dishes. Dishes already finished or past 21:00 stay as they are. Dogs can change until 23:00.", "Een ruil in de planning verandert honden en afwas. Afwas die klaar is of na 21:00 blijft staan. Honden kunnen tot 23:00 wisselen."),
    "week_hint": ("Tap a day for details and availability.", "Tik op een dag voor details en beschikbaarheid."),
    "solo": ("Waiting for the second walker. Until then, the only walker has both chores.", "Wachten op de tweede loper. Tot die tijd doet de enige loper beide taken."),
    "hi_walker": ("Welcome, {name}! You and the other walker share dogs and dishes.\nReminders: dishes at 18:30, dogs at 21:45. Tap Done after finishing. Can't passes only that chore on.\nUse Today or the planning below. Typed changes show a preview before you confirm.", "Welkom, {name}! Jullie verdelen samen de honden en de afwas.\nHerinneringen: afwas om 18:30, honden om 21:45. Tik op Klaar zodra het gedaan is. Kan niet geeft alleen die taak door.\nGebruik Vandaag of de planning hieronder. Getypte wijzigingen krijg je eerst ter bevestiging te zien."),
    "hi_parent": ("Welcome! You can see both chores and the planning here. You'll hear when the dogs are out, or when help is needed. You can take over an unfinished chore below.", "Welkom! Hier zie je beide taken en de planning. Je hoort het als de honden uit zijn of als er hulp nodig is. Een openstaande taak kun je hieronder overnemen."),
    "help_walker": ("Dishes reminder: 18:30. Dogs reminder: 21:45.\nDone records that chore as finished. Can't passes only that chore to the other walker, until 21:00 for dishes or 23:00 for dogs.\nPlanning: choose a day to mark yourself unavailable or request a swap. The other walker must accept a swap. Unavailability applies to both chores.\nYou can also type \"not Friday\". Check the preview before saving.", "Afwasherinnering: 18:30. Hondenherinnering: 21:45.\nKlaar registreert die taak als gedaan. Kan niet geeft alleen die taak aan de andere loper, tot 21:00 voor afwas en 23:00 voor honden.\nPlanning: kies een dag om aan te geven dat je niet kan of om een ruil aan te vragen. De andere loper moet een ruil accepteren. Niet beschikbaar geldt voor beide taken.\nJe kunt ook \"kan niet vrijdag\" typen. Controleer het overzicht voordat je opslaat."),
    "help_parent": ("Today shows who is doing each chore and whether it is finished. Planning goes up to 30 days ahead.\nIf a chore is still unfinished at 21:00 for dishes or 23:00 for dogs, you'll get an alert. Tap I'll take it to cover it. Then tap Done once you have finished.", "Vandaag toont wie welke taak doet en of die klaar is. Je kunt tot 30 dagen vooruit plannen.\nAls afwas om 21:00 of honden om 23:00 nog niet klaar is, krijg je een melding. Tik op Ik doe 't om over te nemen. Tik daarna op Klaar zodra je het gedaan hebt."),
    "huh": ("I couldn't read that. Choose a day in Planning, or type \"not Friday\".", "Dat begreep ik niet. Kies een dag in de planning, of typ \"kan niet vrijdag\"."),
    "commands": ("Use the buttons below to see today, plan ahead or get help.", "Gebruik de knoppen hieronder voor vandaag, de planning of uitleg."),
})

S.update({
    "b_more": ("More", "Meer"),
    "b_family": ("Family", "Gezin"),
    "b_history": ("My recent chores", "Mijn recente taken"),
    "b_last_month": ("◀ Previous month", "◀ Vorige maand"),
    "b_this_month": ("This month ▶", "Deze maand ▶"),
    "b_availability": ("Availability", "Beschikbaarheid"),
    "b_requests": ("Swap requests", "Ruilverzoeken"),
    "b_rotate_links": ("Replace invite links", "Uitnodigingslinks vervangen"),
    "b_rotate_confirm": ("Replace links", "Links vervangen"),
    "b_rotate_cancel": ("Keep current links", "Huidige links houden"),
    "b_undo_done": ("Undo Done", "Klaar terugdraaien"),
    "b_fix_done": ("I did this", "Heb ik gedaan"),
    "more_title": ("More", "Meer"),
    "family_title": ("Family", "Gezin"),
    "family_walkers": ("Walkers: {names}", "Lopers: {names}"),
    "family_parents": ("Parents: {names}", "Ouders: {names}"),
    "family_empty": ("nobody yet", "nog niemand"),
    "family_waiting": ("Open places · walkers: {walkers} · parents: {parents}", "Open plekken · lopers: {walkers} · ouders: {parents}"),
    "family_ready": ("Everyone has joined.", "Iedereen doet mee."),
    "family_links": ("Share each link with the right family member. These links stay valid until you replace them.", "Deel elke link met het juiste gezinslid. Deze links blijven geldig tot je ze vervangt."),
    "family_walker_link": ("Walker invite", "Loper uitnodigen"),
    "family_parent_link": ("Parent invite", "Ouder uitnodigen"),
    "family_owner": ("The bot owner can share invite links.", "De eigenaar kan uitnodigingslinks delen."),
    "rotate_preview": ("Replace the invite links?\nThe old links will stop working. Family members who already joined stay connected.", "Uitnodigingslinks vervangen?\nDe oude links werken daarna niet meer. Gezinsleden die al meedoen blijven verbonden."),
    "rotate_changed": ("The links changed meanwhile. Open Family to see the current links.", "De links zijn intussen gewijzigd. Open Gezin voor de huidige links."),
    "rotate_kept": ("Current invite links kept.", "Huidige uitnodigingslinks behouden."),
    "requests_waiting": ("Swap requests awaiting your reply: {count}", "Ruilverzoeken om te beantwoorden: {count}"),
    "history_title": ("My chores · last 7 days", "Mijn taken · afgelopen 7 dagen"),
    "history_empty": ("No chores recorded for you in these 7 days.", "Voor jou zijn in deze 7 dagen nog geen taken geregistreerd."),
    "history_open": ("not confirmed", "niet bevestigd"),
    "history_hint": ("Need to correct a task? You will review the change before confirming.", "Taak corrigeren? Je controleert de wijziging voordat je bevestigt."),
})

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
    db.execute("PRAGMA busy_timeout=5000")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY, name TEXT, role TEXT, joined INTEGER, lang TEXT DEFAULT 'en');
    CREATE TABLE IF NOT EXISTS off(id INTEGER, day TEXT, PRIMARY KEY(id, day));
    CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS corrections(
        id INTEGER PRIMARY KEY, day TEXT NOT NULL, chore TEXT NOT NULL,
        actor INTEGER NOT NULL, before_status TEXT NOT NULL, after_status TEXT NOT NULL,
        created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS outbox(
        id INTEGER PRIMARY KEY, event TEXT UNIQUE, recipient INTEGER NOT NULL,
        payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        next_try REAL NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'pending',
        created REAL NOT NULL, expires REAL NOT NULL);
    """)
    migrate(db)
    for table, cols in TABLES.items(): db.execute(f"CREATE TABLE IF NOT EXISTS {table}({cols})")
    have = {c[1] for c in db.execute("PRAGMA table_info(nights)")}
    for column in ("cover_id", "cover_msg"):
        if column not in have: db.execute(f"ALTER TABLE nights ADD COLUMN {column} INTEGER")
    if "rotation_walker" not in have:
        db.execute("ALTER TABLE nights ADD COLUMN rotation_walker INTEGER")
        db.execute("UPDATE nights SET rotation_walker=walker")
    if "done_ts" not in have:
        db.execute("ALTER TABLE nights ADD COLUMN done_ts REAL")
    db.commit()
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

def monthly_points(db, today):
    """One point per completed chore, credited to its actual person and scheduled month.

    Scores are derived from the unique day/chore records, never incremented by taps.
    This also carries existing history into the points view without a data migration.
    """
    result = []
    for member in db.execute("SELECT * FROM members ORDER BY joined, id").fetchall():
        points = db.execute(
            "SELECT COUNT(*) FROM nights WHERE status='done' AND COALESCE(walker,cover_id)=? AND substr(day,1,7)=?",
            (member["id"], today.isoformat()[:7])).fetchone()[0]
        if member["role"] == "walker" or points:
            result.append({"id": member["id"], "name": member["name"], "role": member["role"], "points": points})
    return result

def is_off(db, uid, day):
    return db.execute("SELECT 1 FROM off WHERE id=? AND day=?", (uid, day.isoformat())).fetchone() is not None

def _rotation_before(db, day, walkers):
    """Recover the preceding turn without writing a plan or iterating empty years."""
    a, b = walkers[:2]
    previous = db.execute(
        "SELECT day, COALESCE(walker,rotation_walker) AS anchor FROM nights "
        "WHERE chore='dogs' AND day<? AND COALESCE(walker,rotation_walker) IS NOT NULL "
        "ORDER BY day DESC LIMIT 1", (day.isoformat(),)).fetchone()
    if previous:
        cursor, last = date.fromisoformat(previous["day"]) + timedelta(days=1), previous["anchor"]
    else:
        joined = db.execute("SELECT MIN(joined) FROM members WHERE role='walker'").fetchone()[0]
        cursor = min(day, datetime.fromtimestamp(joined, TZ).date()) if joined is not None else day
        last = b
    events = db.execute(
        "SELECT day FROM off WHERE day>=? AND day<? UNION "
        "SELECT day FROM overrides WHERE chore='dogs' AND day>=? AND day<? UNION "
        "SELECT day FROM nights WHERE chore='dogs' AND day>=? AND day<? ORDER BY day",
        (str(cursor), str(day)) * 3).fetchall()
    for event in events:
        event_day = date.fromisoformat(event[0])
        if (event_day - cursor).days % 2: last = a if last == b else b
        row = night(db, event_day)
        if row and row["status"] == "nobody":
            turn = row["rotation_walker"]
        else:
            turn = (row["walker"] or row["rotation_walker"]) if row else None
            if turn is None: turn = pick(db, event_day, last)
        last = turn or last
        cursor = event_day + timedelta(days=1)
    if (day - cursor).days % 2: last = a if last == b else b
    return last

def pick(db, day, last=None, extra_counts=None):
    """Walker for `day`. `last` = who walked the previous night (defaults to history)."""
    o = db.execute("SELECT walker FROM overrides WHERE day=? AND chore='dogs'", (day.isoformat(),)).fetchone()
    if o: return o[0]
    w = [m["id"] for m in members(db, "walker")]
    if not w: return None
    if len(w) == 1: return None if is_off(db, w[0], day) else w[0]
    a, b = w[:2]
    if last is None:
        last = _rotation_before(db, day, w)
    base = a if last == b else b
    other = a if base == b else b
    off_base, off_other = is_off(db, base, day), is_off(db, other, day)
    if off_base and not off_other: return other
    if off_base and off_other: return None
    return base

def week(db, today, n=7, skip=0):
    """Planned walker per night for `n` nights starting `skip` days after today."""
    out, last, counts = [], None, {}
    for i in range(skip + n):
        d = today + timedelta(days=i)
        row = db.execute("SELECT walker,rotation_walker,status FROM nights WHERE day=? AND chore='dogs'", (d.isoformat(),)).fetchone()
        uid = row[0] if row else pick(db, d, last, counts)
        counts[uid] = counts.get(uid, 0) + 1
        out.append((d, uid))
        last = (uid or row["rotation_walker"] or last) if row else uid or last
    return out[skip:]

def dishes(db, day, dog, sent=True):
    """Dishes go to whoever isn't on dogs, unless they're off and the dog walker isn't.
    sent=False ignores a dishes message already out, to see who should have it now."""
    for table in ("nights", "overrides")[0 if sent else 1:]:
        r = db.execute(f"SELECT walker FROM {table} WHERE day=? AND chore='dishes'", (day.isoformat(),)).fetchone()
        if r: return r[0]
    if dog is None: return None
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
        if a not in WD or b not in WD: return m.group(0)
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
    if re.search(r"\b(day after tomorrow|overmorgen)\b", t):
        found.discard(today + timedelta(days=1))
        add(today + timedelta(days=2))
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
        for year in range(today.year, today.year + 5):
            try: d = date(year, mo, dn)
            except ValueError: continue
            if d >= today:
                add(d)
                return
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
    if re.search(r"\b(available again|back in|kan weer|weer beschikbaar)\b", t): return "in", me
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
OWNER_ID = int(os.environ.get("OWNER_ID") or 0)  # Michael: the only one who can start the bot and invite
RETRY = (0, 1)         # short retries; persisted notifications retry on later ticks
AHEAD = 31            # today plus the next 30 days
MAX_PAGE = (AHEAD - 1) // 7

def log(*a):
    text = " ".join(map(str, a))
    if TOKEN: text = text.replace(TOKEN, "[redacted]")
    text = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot[redacted]", text)
    print(datetime.now(TZ).strftime("%F %T"), text, file=sys.stderr, flush=True)

def api(method, **params):
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}",
                                 data=json.dumps(params).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40 if method == "getUpdates" else 10) as r:
        data = json.load(r)
    if not data.get("ok", True):
        raise RuntimeError(f"Telegram rejected {method} ({data.get('error_code', 'unknown')})")
    return data["result"]

def send(chat, text, markup=None, html=False):
    """Message id; False if the user blocked or never started the bot (403); None on other failures."""
    p = {"chat_id": chat, "text": text, **({"reply_markup": markup} if markup else {}), **({"parse_mode": "HTML"} if html else {})}
    for wait in RETRY:
        time.sleep(wait)
        try:
            return api("sendMessage", **p)["message_id"]
        except urllib.error.HTTPError as e:
            try:
                log("send", chat, e.code)
                if e.code == 403: return False
                if e.code == 429:
                    try: delay = float(json.loads(e.read() or b"{}").get("parameters", {}).get("retry_after", 1))
                    except (ValueError, TypeError, AttributeError): delay = 1
                    time.sleep(max(0, min(delay, 10)))
                    return None
                if e.code == 400: return None
            finally:
                if e.fp is not None: e.close()
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
        try:
            body = e.read()
            if b"not modified" in body: return True
            log("edit", chat, e.code)
            return False if b"not found" in body else None
        finally:
            if e.fp is not None: e.close()
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

def tell_parents(db, key, markup=None, valid=None, event=None, **kw):
    for p in members(db, "parent"):
        notice = f"{event}:{p['id']}" if event else f"notice:{now().date()}:{key}:{p['id']}:{json.dumps(kw, sort_keys=True)}"
        queue_notice(db, p["id"], tr(lang_of(db, p["id"]), key, **kw), markup, notice, valid)

def completion_notice(db, day, chore, uid, hm):
    current = night(db, day, chore)
    valid = {"day": str(day), "chore": chore, "statuses": ["done"], "actor": uid,
             "done_ts": current["done_ts"], "window": False}
    tell_parents(db, "parent_done", valid=valid, event=f"completed:{day}:{chore}:{current['done_ts']}", name=name(db, uid), hm=hm)

def save_notice(db, uid, text, markup=None, event=None, valid=None):
    """Add an outgoing notice inside the caller's transaction, without sending."""
    payload = json.dumps({"text": text, "markup": markup, "valid": valid})
    stamp = time.time()
    db.execute("INSERT OR IGNORE INTO outbox(event,recipient,payload,created,expires) VALUES(?,?,?,?,?)",
               (event or secrets.token_hex(12), uid, payload, stamp, stamp + 86400))

def queue_notice(db, uid, text, markup=None, event=None, valid=None):
    """Persist before sending. Failed notifications survive a process restart."""
    save_notice(db, uid, text, markup, event, valid)
    db.commit()
    drain_outbox(db, event)

def drain_outbox(db, event=None):
    stamp = time.time()
    sql = "SELECT * FROM outbox WHERE state='pending' AND next_try<=?"
    args = [stamp]
    if event: sql += " AND event=?"; args.append(event)
    for row in db.execute(sql + " ORDER BY id LIMIT 4", args).fetchall():
        p = json.loads(row["payload"])
        valid = p.get("valid")
        current = night(db, date.fromisoformat(valid["day"]), valid["chore"]) if valid else None
        expired = stamp >= row["expires"] or (valid and (not current or current["status"] not in valid["statuses"]
                  or (valid.get("window", True) and not done_open(date.fromisoformat(valid["day"]), now()))
                  or ("actor" in valid and (current["walker"] or current["cover_id"]) != valid["actor"])
                  or ("done_ts" in valid and current["done_ts"] != valid["done_ts"])))
        if expired:
            db.execute("UPDATE outbox SET state='expired' WHERE id=?", (row["id"],)); db.commit(); continue
        result = send(row["recipient"], p["text"], p["markup"])
        state = "blocked" if result is False else "sent" if result else "pending"
        wait = min(300, 15 * 2 ** min(row["attempts"], 5))
        db.execute("UPDATE outbox SET state=?, attempts=attempts+1, next_try=? WHERE id=?",
                   (state, stamp + wait, row["id"]))
        db.commit()

def parent_help(db, day, chore, key):
    recipients = members(db, "parent") or members(db, "walker")[:1]
    for p in recipients:
        uid, lang = p["id"], lang_of(db, p["id"])
        markup = {"inline_keyboard": [[{"text": tr(lang, "b_pcover"), "callback_data": f"pcover:{chore}:{day}"}]]} if p["role"] == "parent" else menu_markup(db, uid)
        queue_notice(db, uid, tr(lang, K(key, chore)), markup, f"alert:{day}:{chore}:{key}:{uid}",
                     {"day": str(day), "chore": chore, "statuses": ["nobody"] if key == "nobody_parents" else ["on"]})

def buttons(db, uid, *keys):
    lang = lang_of(db, uid)
    return {"inline_keyboard": [[{"text": tr(lang, "b_" + k), "callback_data": k} for k in keys]]}

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

def peek_pending(db, uid, msg):
    value = kv(db, f"p_{uid}_{msg}")
    return json.loads(value) if value else None

def all_pending(db):
    return [(k, json.loads(v)) for k, v in db.execute("SELECT k, v FROM kv WHERE k LIKE 'p\\_%' ESCAPE '\\'")]

def swap_valid(db, p, t):
    """A swap request dies at 23:00 on its first night, or once any night changed hands."""
    days = [date.fromisoformat(d) for d in p["owners"]]
    return bool(days) and can_pass(min(days), t) and all(
        (not night(db, d) or night(db, d)["status"] in ("on", "nobody"))
        and owner(db, d, t.date()) == p["owners"][d.isoformat()] for d in days)

def prune(db, t):
    db.execute("DELETE FROM kv WHERE k LIKE 'late\\_%' ESCAPE '\\' AND substr(k, -10) < ?",
               ((t.date() - timedelta(days=1)).isoformat(),))
    for k, p in all_pending(db):
        if "expires" in p: stale = t.timestamp() >= p["expires"]
        elif p["type"] == "swap": stale = not swap_valid(db, p, t)
        else: stale = bool(p.get("days")) and max(p["days"]) < t.date().isoformat()
        if stale: db.execute("DELETE FROM kv WHERE k=?", (k,))
    cutoff = (t.date() - timedelta(days=30)).isoformat()
    db.execute("DELETE FROM off WHERE day<?", (cutoff,))
    db.execute("DELETE FROM overrides WHERE day<?", (cutoff,))
    db.execute("DELETE FROM outbox WHERE expires<?", (time.time() - 7 * 86400,))
    db.commit()

def lang_view(lang):
    return tr(lang, "lang"), {"inline_keyboard": [[
        {"text": ("✓ " if l == lang else "") + label, "callback_data": "lang:" + l}
        for l, label in zip(LANGS, ("English", "Nederlands"))]]}

def menu_markup(db, uid):
    lang = lang_of(db, uid)
    return {"inline_keyboard": [[{"text": tr(lang, "b_" + key), "callback_data": callback}
                                 for key, callback in (("home", "home"), ("plan", "plan"))],
                                [{"text": tr(lang, "b_" + key), "callback_data": callback}
                                 for key, callback in (("points", "points"), ("more", "more"))]]}

def chore_status(db, uid, day, chore, assigned, lang):
    n = night(db, day, chore)
    if not n and day < now().date(): return tr(lang, "past_unrecorded")
    who_id = (n["walker"] or n["cover_id"]) if n else assigned
    who = tr(lang, "you") if who_id == uid else html.escape(name(db, who_id)) if who_id else tr(lang, "unassigned")
    status = n["status"] if n else "planned"
    if status == "done": state = "✅ " + tr(lang, "done_status", time=n["done_at"] or "").strip()
    elif status == "parent":
        cover = n["cover_id"] if "cover_id" in n.keys() else None
        person = html.escape(name(db, cover)) if cover else ""
        return (person + " · " if person else "") + tr(lang, "parent_status")
    elif status == "missed": return tr(lang, "missed_status")
    elif status == "nobody": return "⚠️ " + tr(lang, "unassigned")
    else: state = tr(lang, "waiting" if n else "planned")
    return f"{who} · {state}"


def day_details(db, uid, day, dog, lang):
    dish = dishes(db, day, dog)
    lines = [f"{tr(lang, 'dishes_label')} 18:30 · {chore_status(db, uid, day, 'dishes', dish, lang)}",
             f"{tr(lang, 'dogs_label')} 21:45 · {chore_status(db, uid, day, 'dogs', dog, lang)}"]
    off = [html.escape(m["name"]) for m in members(db, "walker") if is_off(db, m["id"], day)]
    if off: lines.append(tr(lang, "off_status", names=", ".join(off)))
    if any(p.get("type") == "swap" and day.isoformat() in p.get("owners", {}) for _, p in all_pending(db)):
        lines.append(tr(lang, "pending_status"))
    return lines


def week_view(db, today, lang="en", page=0, uid=None):
    last_page = (AHEAD - 1) // 7
    page = max(0, min(last_page, page))
    rows = week(db, today, n=min(7, AHEAD - 7 * page), skip=7 * page)
    a, b = rows[0][0], rows[-1][0]
    span = f"{fmt(a, lang)} {month(a, lang)} – {fmt(b, lang)} {month(b, lang)}"
    lines = [f"<b>{tr(lang, 'week', span=span)}</b>",
             f"{tr(lang, 'dogs_label')} 21:45 · {tr(lang, 'dishes_label')} 18:30", ""]
    walkers = members(db, "walker")
    if len(walkers) == 1: lines.append(tr(lang, "solo"))
    pending_days = {d for _, p in all_pending(db) if p.get("type") == "swap" for d in p.get("owners", {})}
    def compact(day, chore, assigned):
        n = night(db, day, chore)
        actual = (n["walker"] or n["cover_id"]) if n else assigned
        if n and n["status"] == "parent":
            actual = n["cover_id"] if "cover_id" in n.keys() else None
        who = tr(lang, "you") if actual == uid else html.escape(name(db, actual)) if actual else tr(lang, "unassigned")
        if n and n["status"] == "done": return who + " ✓" + (" " + n["done_at"] if n["done_at"] else "")
        if n and n["status"] == "parent": return who + " 🙋"
        if n and n["status"] == "missed": return tr(lang, "missed_status")
        return who if actual else "⚠️ " + who
    for day, dog in rows:
        lines.append(f"<b>{fmt(day, lang)}</b>  🐕 {compact(day, 'dogs', dog)} · 🍽 {compact(day, 'dishes', dishes(db, day, dog))}")
        off = [html.escape(m["name"]) for m in walkers if is_off(db, m["id"], day)]
        if off: lines.append("  " + tr(lang, "off_status", names=", ".join(off)))
        if day.isoformat() in pending_days: lines.append("  " + tr(lang, "pending_status"))
    lines.extend(["", tr(lang, "week_hint")])
    days = [{"text": fmt(d, lang), "callback_data": f"wk:{d}:{page}"} for d, _ in rows]
    nav = []
    if page > 0: nav.append({"text": tr(lang, "b_prev"), "callback_data": f"wp:{page - 1}"})
    if page < last_page: nav.append({"text": tr(lang, "b_next"), "callback_data": f"wp:{page + 1}"})
    keyboard = [days[i:i + 4] for i in range(0, len(days), 4)]
    if nav: keyboard.append(nav)
    if role_of(db, uid) == "walker":
        keyboard.append([{"text": tr(lang, "b_availability"), "callback_data": "availability"},
                         {"text": tr(lang, "b_requests"), "callback_data": "requests"}])
    return "\n".join(lines), {"inline_keyboard": keyboard + menu_markup(db, uid)["inline_keyboard"]}



def night_view(db, uid, day, page):
    t, lang = now(), lang_of(db, uid)
    cur, other = owner(db, day, t.date()), other_walker(db, uid)
    lines = [f"<b>{fmt(day, lang)} {month(day, lang)}</b>"] + day_details(db, uid, day, cur, lang)
    rows = []
    dog_row = night(db, day)
    editable = not dog_row or dog_row["status"] in ("on", "nobody")
    if role_of(db, uid) == "walker" and editable and day >= t.date() and can_pass(day, t):
        cb = lambda k: {"text": tr(lang, "b_" + k), "callback_data": f"{k}:{day}:{page}"}
        row = [cb("nin" if is_off(db, uid, day) else "noff")]
        if not cur: row.append(cb("ntake"))
        elif other and (cur != uid or not is_off(db, other, day)): row.append(cb("nswap"))
        rows.append(row)
    if day == t.date(): rows.extend(today_actions(db, uid, day, t))
    if any(p.get("type") == "swap" and str(day) in p.get("owners", {})
           and (p.get("from") == uid or key.startswith(f"p_{uid}_"))
           for key, p in all_pending(db)):
        rows.append([{"text": tr(lang, "b_requests"), "callback_data": "requests"}])
    rows.append([{"text": tr(lang, "b_back"), "callback_data": f"wp:{page}"}])
    return "\n".join(lines), {"inline_keyboard": rows + menu_markup(db, uid)["inline_keyboard"]}


def today_actions(db, uid, day, t):
    rows, lang = [], lang_of(db, uid)
    for chore in ("dishes", "dogs"):
        n = night(db, day, chore)
        if not done_open(day, t): continue
        label = tr(lang, chore + "_label")
        if not n:
            dog = owner(db, day, day)
            assigned = dog if chore == "dogs" else dishes(db, day, dog)
            if day == t.date() and role_of(db, uid) == "walker" and assigned == uid:
                rows.append([{"text": label + " · " + tr(lang, "b_done"), "callback_data": f"done:{chore}:{day}"}])
            continue
        if day != t.date(): label = fmt(day, lang) + " · " + label
        if n["status"] == "done" and (n["walker"] or n["cover_id"]) == uid:
            rows.append([{"text": label + " · " + tr(lang, "b_undo_done"),
                          "callback_data": f"correction:{day}:{chore}:undo"}])
        elif role_of(db, uid) == "walker" and n["walker"] == uid and n["status"] == "on":
            row = [{"text": label + " · " + tr(lang, "b_done"), "callback_data": f"done:{chore}:{day}"}]
            if can_pass(day, t, chore): row.append({"text": tr(lang, "b_cant"), "callback_data": f"cant:{chore}:{day}"})
            rows.append(row)
        elif role_of(db, uid) == "parent" and n["status"] == "parent" and "cover_id" in n.keys() and n["cover_id"] == uid:
            rows.append([{"text": label + " · " + tr(lang, "b_done"), "callback_data": f"pdone:{chore}:{day}"}])
        elif role_of(db, uid) == "parent" and n["status"] in ("on", "nobody"):
            rows.append([{"text": label + " · " + tr(lang, "b_pcover"), "callback_data": f"pcover:{chore}:{day}"}])
    return rows


S.update({
    "past_unrecorded": ("No confirmation recorded", "Geen bevestiging geregistreerd"),
    "focus_next": ("Next for you: {chore} at {time}.", "Straks voor jou: {chore} om {time}."),
    "focus_open": ("Yours to confirm: {chore}.", "Nog door jou te bevestigen: {chore}."),
    "focus_yesterday": ("Still yours from {day}: {chore}.", "Nog voor jou van {day}: {chore}."),
    "focus_done": ("Your chores are confirmed done.", "Jouw taken zijn bevestigd klaar."),
    "focus_off": ("You're marked unavailable today.", "Je staat vandaag als niet beschikbaar."),
    "focus_none": ("Nothing assigned to you today.", "Vandaag staat er niets voor jou gepland."),
    "focus_help": ("Help needed: {chore}.", "Hulp nodig: {chore}."),
    "focus_help_yesterday": ("Help still needed for {day}: {chore}.", "Nog hulp nodig voor {day}: {chore}."),
    "focus_parent_own": ("Your takeover still needs confirmation: {chore}.", "Jouw overname wacht op bevestiging: {chore}."),
    "focus_family_done": ("Both chores are confirmed done.", "Beide taken zijn bevestigd klaar."),
    "focus_assigned": ("Both chores are assigned. See their confirmations below.", "Beide taken zijn verdeeld. Hieronder zie je wat bevestigd is."),
    "focus_wait_family": ("Waiting for the walkers to join.", "Wachten tot de lopers meedoen."),
    "focus_setup": ("Invite the second walker through Family. Until then, you have both chores.", "Nodig de tweede loper uit via Gezin. Tot die tijd heb jij beide taken."),
    "first_home_walker": ("This bot shares dogs and dishes. Tap Done after finishing; use Planning for days you can't.", "Deze bot verdeelt honden en afwas. Tik op Klaar na afloop; geef via Planning aan wanneer je niet kan."),
    "first_home_parent": ("Follow the chores here. If you take one over, tap Done after finishing.", "Volg hier de taken. Neem je iets over, tik dan na afloop op Klaar."),
})


def home_tasks(db, day, today):
    """Read actual assignments first, without manufacturing reminder rows."""
    dog_row = night(db, day)
    dog = dog_row["walker"] if dog_row else owner(db, day, today) if day >= today else None
    result = []
    for chore in ("dishes", "dogs"):
        row = night(db, day, chore)
        person = (row["walker"] or row["cover_id"]) if row else dog if chore == "dogs" else dishes(db, day, dog)
        result.append((chore, person, row["status"] if row else "planned"))
    return result


def home_focus(db, uid, t, waiting=0):
    """One immediate next step. Yesterday's unfinished work outranks today's plan."""
    lang, parent = lang_of(db, uid), role_of(db, uid) == "parent"
    today = t.date()
    label = lambda chores: ", ".join(tr(lang, chore + "_label") for chore in chores)
    if t.hour < DONE_UNTIL:
        yesterday = today - timedelta(days=1)
        old_tasks = home_tasks(db, yesterday, today)
        own = [chore for chore, person, status in old_tasks if person == uid and status in ("on", "parent")]
        if own: return tr(lang, "focus_yesterday", day=fmt(yesterday, lang), chore=label(own)), yesterday
        help_needed = [chore for chore, person, status in old_tasks if status == "nobody" or status == "on"]
        if parent and help_needed:
            return tr(lang, "focus_help_yesterday", day=fmt(yesterday, lang), chore=label(help_needed)), yesterday
    if waiting: return tr(lang, "requests_waiting", count=waiting), None
    tasks = home_tasks(db, today, today)
    if parent:
        own = [chore for chore, person, status in tasks if person == uid and status == "parent"]
        if own: return tr(lang, "focus_parent_own", chore=label(own)), None
        help_needed = [chore for chore, person, status in tasks
                       if status == "nobody" or (person is None and members(db, "walker"))
                       or (status == "on" and not can_pass(today, t, chore))]
        if help_needed: return tr(lang, "focus_help", chore=label(help_needed)), None
        if all(status == "done" for _, _, status in tasks): return tr(lang, "focus_family_done"), None
        if not members(db, "walker"): return tr(lang, "focus_wait_family"), None
        return tr(lang, "focus_assigned"), None
    own = [(chore, status) for chore, person, status in tasks if person == uid]
    for chore, status in own:
        if status not in ("planned", "on"): continue
        hour, minute = CHORES[chore][0]
        if status == "planned" and t < at(today, hour, minute):
            return tr(lang, "focus_next", chore=label([chore]), time=f"{hour:02d}:{minute:02d}"), None
        return tr(lang, "focus_open", chore=label([chore])), None
    if own and all(status == "done" for _, status in own): return tr(lang, "focus_done"), None
    return tr(lang, "focus_off" if is_off(db, uid, today) else "focus_none"), None


def home_view(db, uid):
    t, lang = now(), lang_of(db, uid)
    day = t.date()
    dog = owner(db, day, day)
    waiting = sum(1 for key, request in all_pending(db)
                  if key.startswith(f"p_{uid}_") and request.get("type") == "swap" and swap_valid(db, request, t))
    focus, previous = home_focus(db, uid, t, waiting)
    lines = [f"<b>{tr(lang, 'today', day=fmt(day, lang))}</b>", focus, ""]
    rows = []
    if previous:
        lines.extend([f"<b>{fmt(previous, lang)} {month(previous, lang)}</b>"] + day_details(db, uid, previous, None, lang) + [""])
        rows.extend(today_actions(db, uid, previous, t))
    lines.extend(day_details(db, uid, day, dog, lang))
    rows.extend(today_actions(db, uid, day, t))
    if waiting:
        if previous: lines.extend(["", tr(lang, "requests_waiting", count=waiting)])
        rows.append([{"text": tr(lang, "b_requests"), "callback_data": "requests"}])
    if len(members(db, "walker")) == 1:
        lines.extend(["", tr(lang, "focus_setup" if uid == OWNER_ID else "solo")])
        if uid == OWNER_ID: rows.append([{"text": tr(lang, "b_invite"), "callback_data": "family"}])
    joined = col(db, uid, "joined")
    if joined is not None and 0 <= t.timestamp() - joined < 86400:
        lines.extend(["", tr(lang, "first_home_parent" if role_of(db, uid) == "parent" else "first_home_walker")])
    score = next((r["points"] for r in monthly_points(db, day) if r["id"] == uid), 0)
    lines.extend(["", tr(lang, "points_own", points=score)])
    return "\n".join(lines), {"inline_keyboard": rows + menu_markup(db, uid)["inline_keyboard"]}


def help_view(db, uid):
    lang = lang_of(db, uid)
    text = tr(lang, "help_parent" if role_of(db, uid) == "parent" else "help_walker")
    if role_of(db, uid) == "walker": text += "\n\n" + tr(lang, "swap_scope")
    text += "\n\n" + tr(lang, "points_rule")
    return text, menu_markup(db, uid)


def points_view(db, uid, previous=False):
    day, lang = now().date(), lang_of(db, uid)
    if previous: day = day.replace(day=1) - timedelta(days=1)
    lines = [tr(lang, "points_title", month=month(day, lang), year=day.year), ""]
    for member in monthly_points(db, day):
        label = tr(lang, "you") if member["id"] == uid else member["name"]
        lines.append(tr(lang, "points_total", name=label, points=member["points"]))
    lines.extend(["", tr(lang, "points_rule")])
    rows = [[{"text": tr(lang, "b_this_month" if previous else "b_last_month"),
              "callback_data": "points_month:current" if previous else "points_month:previous"}],
            [{"text": tr(lang, "b_history"), "callback_data": "history"}]]
    return "\n".join(lines), {"inline_keyboard": rows + menu_markup(db, uid)["inline_keyboard"]}


def more_view(db, uid):
    lang = lang_of(db, uid)
    rows = [[{"text": tr(lang, "b_help"), "callback_data": "help"},
             {"text": tr(lang, "b_language"), "callback_data": "language"}],
            [{"text": tr(lang, "b_family"), "callback_data": "family"}]]
    return tr(lang, "more_title"), {"inline_keyboard": rows + menu_markup(db, uid)["inline_keyboard"]}


def family_view(db, uid):
    lang = lang_of(db, uid)
    walkers, parents = members(db, "walker"), members(db, "parent")
    names = lambda group: ", ".join(member["name"] for member in group) or tr(lang, "family_empty")
    lines = [tr(lang, "family_title"), "", tr(lang, "family_walkers", names=names(walkers)),
             tr(lang, "family_parents", names=names(parents))]
    remaining = (max(0, 2 - len(walkers)), max(0, 2 - len(parents)))
    lines.extend(["", tr(lang, "family_waiting", walkers=remaining[0], parents=remaining[1])
                  if any(remaining) else tr(lang, "family_ready")])
    rows = []
    if uid == OWNER_ID:
        code = kv(db, "code") or kv(db, "code", secrets.token_hex(8))
        username = kv(db, "bot")
        if username:
            lines.extend(["", tr(lang, "family_links")])
            for role in ("walker", "parent"):
                lines.extend(["", tr(lang, "family_" + role + "_link"), f"https://t.me/{username}?start={role}_{code}"])
            rows.append([{"text": tr(lang, "b_rotate_links"), "callback_data": "rotate_links"}])
    elif any(remaining): lines.extend(["", tr(lang, "family_owner")])
    return "\n".join(lines), {"inline_keyboard": rows + menu_markup(db, uid)["inline_keyboard"]}


def history_view(db, uid):
    today, lang = now().date(), lang_of(db, uid)
    records = db.execute("SELECT * FROM nights WHERE day>=? AND day<=? AND COALESCE(walker,cover_id)=? ORDER BY day DESC, chore",
                         ((today - timedelta(days=6)).isoformat(), today.isoformat(), uid)).fetchall()
    lines, rows = [tr(lang, "history_title"), ""], []
    for record in records:
        day, chore = date.fromisoformat(record["day"]), record["chore"]
        label = f"{fmt(day, lang)} {month(day, lang)} · {tr(lang, chore + '_label')}"
        done = record["status"] == "done"
        status = tr(lang, "done_status", time=record["done_at"] or "").strip() + " · +1" if done else tr(lang, "history_open")
        lines.append(label + " · " + status)
        correction = "undo" if done else "done"
        rows.append([{"text": label + " · " + tr(lang, "b_undo_done" if done else "b_fix_done"),
                      "callback_data": f"correction:{day}:{chore}:{correction}"}])
    if not records: lines.append(tr(lang, "history_empty"))
    else: lines.extend(["", tr(lang, "history_hint")])
    return "\n".join(lines), {"inline_keyboard": rows + menu_markup(db, uid)["inline_keyboard"]}


def handle_ui_button(db, uid, kind, arg, chat, msg, answer):
    """Navigation and owner-only invite rotation. Preview never changes live links."""
    pages = {"more": -5, "family": -6, "invite": -6, "history": -7}
    if kind in pages:
        if kind == "invite" and uid != OWNER_ID: return answer("private")
        return show(db, uid, msg, pages[kind])
    if kind == "points_month":
        if arg not in ("current", "previous"): return answer("old")
        return show(db, uid, msg, -8 if arg == "previous" else -3)
    if kind not in ("rotate_links", "rotate_confirm", "rotate_cancel"): return answer("old")
    if uid != OWNER_ID or chat != uid: return answer("private")
    lang = lang_of(db, uid)
    if kind == "rotate_links":
        keyboard = {"inline_keyboard": [[{"text": tr(lang, "b_rotate_confirm"), "callback_data": "rotate_confirm"}],
                                        [{"text": tr(lang, "b_rotate_cancel"), "callback_data": "rotate_cancel"}]]}
        message = send(uid, tr(lang, "rotate_preview"), keyboard)
        if message:
            pending(db, uid, message, {"type": "rotate_links", "code": kv(db, "code"),
                                      "expires": now().timestamp() + 3600, "days": [now().date().isoformat()]})
        return
    proposal = peek_pending(db, uid, msg)
    if not proposal or proposal.get("type") != "rotate_links" or proposal.get("expires", 0) <= now().timestamp():
        return answer("old")
    pending(db, uid, msg)
    if kind == "rotate_cancel": return tell(db, chat, msg, "rotate_kept", menu_markup(db, uid))
    if proposal.get("code") != kv(db, "code"):
        return tell(db, chat, msg, "rotate_changed", menu_markup(db, uid))
    kv(db, "code", secrets.token_hex(8))
    return show(db, uid, msg, -6)

def view(db, uid, page, day=None):
    if page == -1: return home_view(db, uid)
    if page == -9:
        text, kb = requests_view(db, uid)
        return html.escape(text), kb
    if page == -10:
        text, kb = request_detail_view(db, uid)
        return html.escape(text), kb
    if page in (-2, -3, -4, -5, -6, -7, -8):
        if page == -2: text, kb = help_view(db, uid)
        elif page in (-3, -8): text, kb = points_view(db, uid, previous=page == -8)
        elif page == -5: text, kb = more_view(db, uid)
        elif page == -6: text, kb = family_view(db, uid)
        elif page == -7: text, kb = history_view(db, uid)
        else:
            text, kb = lang_view(lang_of(db, uid))
            kb["inline_keyboard"] += menu_markup(db, uid)["inline_keyboard"]
        return html.escape(text), kb
    t = now()
    if day and not (t.date() <= day < t.date() + timedelta(days=AHEAD)): day = None
    return night_view(db, uid, day, page) if day else week_view(db, t.date(), lang_of(db, uid), page, uid)

def show(db, uid, msg, page, day=None):
    text, kb = view(db, uid, page, day)
    r = edit(uid, msg, text, kb, html=True)
    if r:
        track_view(db, uid, msg, page, day, text, kb)
    return r

def track_view(db, uid, msg, page, day, text, kb):
    old = db.execute("SELECT msg FROM weekmsg WHERE id=?", (uid,)).fetchone()
    db.execute("REPLACE INTO weekmsg(id,msg,page,day,sig) VALUES(?,?,?,?,?)",
               (uid, msg, page, day and day.isoformat(), text + json.dumps(kb)))
    db.commit()
    if old and old["msg"] != msg:
        try: api("editMessageReplyMarkup", chat_id=uid, message_id=old["msg"], reply_markup={"inline_keyboard": []})
        except Exception as exc: log("retire view", type(exc).__name__)


def open_week(db, uid, page=0):
    """Send a fresh overview; keep the last usable view if delivery fails."""
    text, kb = view(db, uid, page)
    m = send(uid, text, kb, html=True)
    if m:
        track_view(db, uid, m, page, None, text, kb)
    return m


def open_home(db, uid):
    return open_week(db, uid, -1)


def refresh_weeks(db):
    for r in db.execute("SELECT * FROM weekmsg").fetchall():
        day = r["day"] and date.fromisoformat(r["day"])
        text, kb = view(db, r["id"], r["page"], day)
        if text + json.dumps(kb) == r["sig"]: continue
        if show(db, r["id"], r["msg"], r["page"], day) is False:
            db.execute("DELETE FROM weekmsg WHERE id=?", (r["id"],)); db.commit()


def set_night(db, day, chore, **cols):
    if "walker" in cols:
        old = night(db, date.fromisoformat(str(day)), chore)
        cols.setdefault("rotation_walker", cols["walker"] or (old and (old["walker"] or old["rotation_walker"])))
    if cols.get("status") == "done": cols.setdefault("done_ts", now().timestamp())
    db.execute(f"UPDATE nights SET {', '.join(c + '=?' for c in cols)} WHERE day=? AND chore=?",
               (*cols.values(), day, chore)); db.commit()

def K(key, chore):
    """String key for a chore: the '_dishes' variant when one exists."""
    return key + "_dishes" if chore == "dishes" and key + "_dishes" in S else key

def chore_buttons(db, uid, chore):
    lang = lang_of(db, uid)
    return {"inline_keyboard": [[{"text": tr(lang, "b_" + k), "callback_data": f"{k}:{chore}"} for k in ("done", "cant")]]}

def plan_button(lang):
    return {"text": tr(lang, "b_plan"), "callback_data": "plan"}

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
    if o and key == "on" and not is_off(db, o, date.fromisoformat(day)):
        return deliver(db, day, chore, o, "on_unreachable", name=name(db, uid))
    set_night(db, day, chore, status="nobody", walker=None)
    parent_help(db, day, chore, "nobody_parents")

def nightly(db, t, chore):
    """Tonight's message from its send time until the cutoff. The stored msg id is the sent flag.
    If the bot was down all evening, a row is still made at the cutoff so parents get the late alert."""
    if (t.hour, t.minute) < CHORES[chore][0]: return
    day = t.date().isoformat()
    n = night(db, t.date(), chore)
    if not n:
        dog = dict(week(db, t.date(), n=1)).get(t.date())
        uid = dog if chore == "dogs" else dog and dishes(db, t.date(), dog)
        if uid is None:
            if not members(db, "walker"): return
            db.execute("INSERT INTO nights(day,chore,status) VALUES(?,?,'nobody')", (day, chore)); db.commit()
            parent_help(db, day, chore, "nobody_parents")
            return
        db.execute("INSERT INTO nights(day, chore, walker, status) VALUES(?,?,?,'on')", (day, chore, uid)); db.commit()
        n = night(db, t.date(), chore)
    if not n["msg"] and n["status"] == "on" and can_pass(t.date(), t, chore): deliver(db, day, chore, n["walker"])

def missed_yesterday(db, t):
    """Report unconfirmed past work after the Done window, including partial outages."""
    if t.hour < DONE_UNTIL: return
    y = t.date() - timedelta(days=1)
    first = db.execute("SELECT MIN(joined) FROM members WHERE role='walker'").fetchone()[0]
    if not first: return
    planned_dog = pick(db, y)
    for chore in CHORES:
        if not night(db, y, chore) and first <= at(y, CHORES[chore][1]).timestamp():
            expected = planned_dog if chore == "dogs" else dishes(db, y, planned_dog, sent=False)
            db.execute("INSERT INTO nights(day,chore,walker,rotation_walker,status) VALUES(?,?,?,?,'on')",
                       (y.isoformat(), chore, expected, expected))
    unresolved = db.execute("SELECT * FROM nights WHERE day<? AND status IN ('on','parent','nobody') ORDER BY day", (t.date().isoformat(),)).fetchall()
    recipients = members(db, "parent") or members(db, "walker")[:1]
    for n in unresolved:
        for recipient in recipients:
            lang = lang_of(db, recipient["id"])
            label = tr(lang, n["chore"] + "_label")
            text = (f"No completion confirmed: {label}, {n['day']}. Check with each other."
                    if lang == "en" else f"Niet als klaar bevestigd: {label}, {n['day']}. Stem dit even met elkaar af.")
            # Persist the notice before marking the unresolved row as history.
            queue_notice(db, recipient["id"], text, menu_markup(db, recipient["id"]), f"unconfirmed:{n['day']}:{n['chore']}:{recipient['id']}")
        set_night(db, n["day"], n["chore"], status="missed")
    db.commit()

def tick(db, t):
    missed_yesterday(db, t)
    for chore in CHORES:
        nightly(db, t, chore)
        if overdue(db, t, chore):
            parent_help(db, t.date(), chore, "late")
            kv(db, f"late_{chore}_{t.date()}", "1")
    drain_outbox(db)
    prune(db, t)

def pass_night(db, n, uid, chat=None, msg=None, answer=None):
    """uid can't do tonight's chore: hand it to the other walker, or tell everyone nobody's free.
    Network trouble reaching the other walker changes nothing; uid is asked to try again."""
    chore, cant = n["chore"], set(filter(None, n["cant"].split(","))) | {str(uid)}
    chat, msg = chat or uid, msg or n["msg"]
    o = other_walker(db, uid)
    available = o and str(o) not in cant and not is_off(db, o, date.fromisoformat(n["day"]))
    new = say_on(db, o, n["day"], chore, "on_passed", name=name(db, uid)) if available else 0
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
    parent_help(db, n["day"], chore, "nobody_parents")

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
    role = role_of(db, uid)
    if not role or chat != uid or q["message"]["chat"].get("type", "private") != "private":
        return answer("private")
    kind, _, arg = data.partition(":")
    if kind in ("more", "family", "invite", "history", "points_month", "rotate_links", "rotate_confirm", "rotate_cancel"):
        return handle_ui_button(db, uid, kind, arg, chat, msg, answer)
    if kind == "availability": return open_availability(db, uid)
    if kind == "av": return handle_availability_button(db, uid, arg, chat, msg, answer)
    if kind == "requests":
        kv(db, f"requests_page_{uid}", str(max(0, int(arg or 0))))
        return show_requests(db, uid, msg)
    if kind in ("request_open", "request_page", "request_details", "request_preview_details", "request_preview_summary",
                "request_confirm", "request_cancel", "swap_reply", "withdraw", "withdraw_confirm", "withdraw_cancel"):
        return handle_request_button(db, uid, kind, arg, chat, msg, answer)
    if kind in ("correction", "correct_confirm", "correct_cancel"):
        return handle_correction_button(db, uid, kind, arg, chat, msg, answer)
    if kind == "home": return show(db, uid, msg, -1)
    if kind == "help": return show(db, uid, msg, -2)
    if kind == "points": return show(db, uid, msg, -3)
    if kind == "language": return show(db, uid, msg, -4)
    if kind == "invite":
        if uid != OWNER_ID: return answer("private")
        return on_text(db, {"from": q["from"], "chat": {"type": "private"}, "text": "/invite"})
    if kind == "lang":
        arg = arg if arg in LANGS else "en"
        db.execute("UPDATE members SET lang=? WHERE id=?", (arg, uid)); db.commit()
        answer()
        return show(db, uid, msg, -1)
    if kind == "wk":
        day, page = arg.split(":")
        return on_week_tap(db, uid, date.fromisoformat(day), chat, msg, answer, int(page))
    if kind == "plan":
        answer()
        return show(db, uid, msg, 0)
    if kind in ("noff", "ntake", "nswap", "nin"):
        day, page = arg.split(":")
        return on_night_action(db, uid, kind, date.fromisoformat(day), chat, msg, answer, int(page))
    if kind == "wp":
        answer()
        return show(db, uid, msg, min(max(int(arg), 0), MAX_PAGE))
    if kind in ("accept", "no"):
        if role != "walker": return answer("private")
        return on_swap_reply(db, uid, kind == "accept", chat, msg, answer)
    if kind in ("confirm", "cancel", "off", "walk"):
        if role != "walker": return answer("private")
        return on_preview(db, uid, kind, today, chat, msg, answer)
    if kind == "pcover":
        if role != "parent": return answer("private")
        return on_parent_cover(db, uid, arg, chat, msg, answer)
    if kind == "pdone": return on_parent_done(db, uid, arg, chat, msg, answer)
    if kind not in ("done", "cant") or role != "walker": return answer("old")
    chore, _, dated = arg.partition(":")
    chore = chore or "dogs"
    if chore not in CHORES: return answer("old")
    n = night(db, date.fromisoformat(dated), chore) if dated else db.execute(
        "SELECT * FROM nights WHERE msg=? AND walker=? AND chore=?", (msg, uid, chore)).fetchone()
    if not n and dated == today.isoformat() and kind == "done":
        dog = owner(db, today, today)
        assigned = dog if chore == "dogs" else dishes(db, today, dog)
        if assigned != uid: return answer("old")
        db.execute("INSERT INTO nights(day,chore,walker,status) VALUES(?,?,?,'on')", (dated, chore, uid)); db.commit()
        n = night(db, today, chore)
    if not n or n["walker"] != uid or n["status"] != "on": return answer("settled")
    day, t = date.fromisoformat(n["day"]), now()
    if not done_open(day, t): return answer("old")
    if kind == "cant":
        if not can_pass(day, t, chore): return answer("too_late")
        pass_night(db, n, uid, uid, n["msg"], answer)
        if dated: show(db, uid, msg, -1)
        return
    hm = t.strftime("%H:%M")
    set_night(db, n["day"], chore, status="done", done_at=hm)
    if n["msg"]: tell(db, uid, n["msg"], K("walked", chore), correction_button(db, uid, day, chore), hm=hm)
    if dated: show(db, uid, msg, -1)
    if chore == "dogs": completion_notice(db, day, chore, uid, hm)

def ask(db, frm, to, days, back=None):
    """Ask the walker who isn't `frm` to agree that `to` walks `days`. Returns say()'s result."""
    rcpt, t = other_walker(db, frm), now()
    if rcpt is None: return False
    owners = {d.isoformat(): owner(db, d, t.date()) for d in days}
    for key, existing in all_pending(db):
        if (existing.get("type") == "swap" and existing.get("from") == frm and existing.get("to") == to
                and existing.get("owners") == owners and swap_valid(db, existing, t)):
            return int(key.rsplit("_", 1)[1])
    impact = swap_impact(db, to, days, t)
    m = send(rcpt, swap_request_text(db, rcpt, frm, impact), swap_response_buttons(db, rcpt))
    if not m: return m
    pending(db, rcpt, m, {"type": "swap", "from": frm, "to": to, "back": back,
                          "owners": owners, "impact": impact})
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
    if not now().date() <= day < now().date() + timedelta(days=AHEAD): return answer("old")
    answer()
    show(db, uid, msg, min(max(page, 0), MAX_PAGE), day)

def on_night_action(db, uid, kind, day, chat, msg, answer, page):
    if not night_open(db, uid, day, answer): return
    t, lang = now(), lang_of(db, uid)
    if kind == "nswap": return preview_swap(db, uid, day, msg, page, answer)
    if kind == "noff": return open_availability(db, uid, days=[day], mode="off", review=True)
    elif kind == "nin": return open_availability(db, uid, days=[day], mode="on", review=True)
    else: take_empty(db, uid, day)
    answer("taken", day=fmt(day, lang)) if kind == "ntake" else answer("saved")
    show(db, uid, msg, page)

def undo_off(db, uid, day):
    """Back in: tonight's live dishes return to whoever the rota now picks."""
    clear_off(db, uid, [day])
    reconcile_open_day(db, day)
    dog, dish = night(db, day), night(db, day, "dishes")
    if dish and dish["msg"] and dish["status"] == "on" and can_pass(day, now(), "dishes"):
        move_tonight(db, dish, dishes(db, day, dog["walker"] if dog else owner(db, day, now().date()), sent=False))

def take_empty(db, uid, day):
    n = night(db, day)
    if owner(db, day, now().date()): return
    clear_off(db, uid, [day])
    apply_claim(db, uid, [day])
    if n: set_night(db, n["day"], "dogs", walker=uid, status="on", msg=None, cant="")
    reconcile_open_day(db, day)

def reconcile_open_day(db, day):
    """Re-plan unassigned or unsent work when availability changes; completed work is history."""
    t = now()
    dog_row = night(db, day)
    dog = dog_row["walker"] if dog_row and dog_row["status"] not in ("nobody", "missed") else pick(db, day)
    for chore in CHORES:
        n = night(db, day, chore)
        if not n or not can_pass(day, t, chore): continue
        if n["status"] != "nobody" and not (n["status"] == "on" and not n["msg"]): continue
        who = dog if chore == "dogs" else dishes(db, day, dog, sent=False)
        set_night(db, day.isoformat(), chore, walker=who, status="on" if who else "nobody", msg=None)

def ask_swap(db, uid, day, chat, msg, answer, page):
    t, cur, other = now(), owner(db, day, now().date()), other_walker(db, uid)
    if not other: return answer()
    m = ask(db, uid, other_walker(db, cur), [day], [chat, msg, page])
    if not m: return answer("retry" if m is None else "cant_reach", name=name(db, other))
    answer("asked", name=name(db, other))
    show(db, uid, msg, page)

def on_swap_reply(db, uid, ok, chat, msg, answer):
    p, t = peek_pending(db, uid, msg), now()
    if not p or p.get("type") != "swap": return answer("old")
    if not swap_valid(db, p, t):
        pending(db, uid, msg)
        answer("old")
        return tell(db, chat, msg, "old")
    answer()
    days, req = [date.fromisoformat(d) for d in p["owners"]], p["from"]
    lang = lang_of(db, req)
    if not ok:
        pending(db, uid, msg)
        tell(db, chat, msg, "declined")
        return say(db, req, "req_no", name=name(db, uid), day=fmt_days(days, lang))
    impact = swap_impact(db, p["to"], days, t)
    if impact != p.get("impact"):
        text = local_text(db, uid, "The plan changed. Check the updated tasks before accepting.\n\n",
                          "De planning is veranderd. Bekijk de bijgewerkte taken voordat je akkoord gaat.\n\n")
        if edit(uid, msg, text + swap_request_text(db, uid, req, impact), swap_response_buttons(db, uid)):
            p["impact"] = impact
            pending(db, uid, msg, p)
            answer("request_updated")
        else: answer("error")
        return "review"
    clear_off(db, p["to"], days)
    apply_claim(db, p["to"], days)  # dishes follow: they go to whoever isn't on dogs
    for chore in CHORES:
        n = night(db, t.date(), chore)
        who = p["to"] if chore == "dogs" else dishes(db, t.date(), p["to"], sent=False)
        if n and t.date() in days and n["status"] in ("on", "nobody") and can_pass(t.date(), t, chore):
            move_tonight(db, n, who)
    pending(db, uid, msg)
    dogs_only = t.date() in days and not can_pass(t.date(), t, "dishes")  # tonight's dishes are already history
    tell(db, chat, msg, "swapped_dogs" if dogs_only else "swapped", day=fmt_days(days, lang_of(db, uid)), walker=name(db, p["to"]))
    say(db, req, "req_yes", name=name(db, uid), day=fmt_days(days, lang), walker=name(db, p["to"]))
    if p["back"]: show(db, req, p["back"][1], p["back"][2])
    answer("swapped", day=fmt_days(days, lang_of(db, uid)), walker=name(db, p["to"]))

def av_text(lang, key, **values):
    """Private availability-copy kept beside its isolated flow."""
    copy = {
        "title": ("Availability · choose dates", "Beschikbaarheid · kies dagen"),
        "off": ("I can't", "Ik kan niet"),
        "on": ("I'm available again", "Ik kan weer"),
        "legend": ("✓ selected · 🚫 currently unavailable\nNothing changes until you review and confirm.",
                   "✓ gekozen · 🚫 nu niet beschikbaar\nEr verandert niets tot je het bekijkt en bevestigt."),
        "review": ("Review {count} dates", "Bekijk {count} dagen"),
        "empty": ("Choose at least one date first.", "Kies eerst minstens één dag."),
        "confirm": ("Confirm availability", "Beschikbaarheid bevestigen"),
        "back": ("← Change dates", "← Dagen aanpassen"),
        "cancel": ("Cancel", "Annuleren"),
        "scope": ("This updates your availability for dogs and dishes. The rota may change; it does not reserve either chore for you. Being available again keeps work already assigned in a reminder with that person. Completed chores and parent coverage stay unchanged.",
                  "Dit past je beschikbaarheid voor honden en afwas aan. De planning kan veranderen; je neemt hiermee geen taak over. Als je weer kunt, blijft werk uit een verstuurde herinnering bij die persoon. Afgeronde taken en hulp van ouders blijven staan."),
        "scope_off": ("For dogs and dishes. The plan adjusts for these dates. Completed tasks and parent coverage stay unchanged.",
                      "Voor honden en afwas. De planning past zich aan op deze dagen. Afgeronde taken en hulp van ouders blijven staan."),
        "scope_on": ("Marks you available again for dogs and dishes. Tasks already sent to someone else stay with that person.",
                     "Je kunt weer voor honden en afwas. Taken die al naar iemand anders zijn gestuurd, blijven bij die persoon."),
        "today": ("Today: dishes can move before 21:00, dogs before 23:00. Past those cutoffs, that chore stays as it is.",
                  "Vandaag: afwas kan vóór 21:00 wijzigen, honden vóór 23:00. Daarna blijft die taak zoals hij is."),
        "stale": ("The plan changed. Review these dates again before confirming.",
                  "De planning is veranderd. Bekijk deze dagen opnieuw voordat je bevestigt."),
        "saved": ("Saved: {mode}\n{days}", "Opgeslagen: {mode}\n{days}"),
    }
    return copy[key][0 if lang == "en" else 1].format(**values)


def av_snapshot(db, selected, t):
    """Bound review to the real rota, membership and each chore's current cutoff."""
    import hashlib
    state = {}
    # Names and language affect presentation, not approval of a scheduling change.
    for table, columns, order in (
            ("members", "id,role,joined", "id"), ("off", "id,day", "id,day"),
            ("overrides", "day,chore,walker", "day,chore"),
            ("nights", "day,chore,walker,status,cant,rotation_walker,cover_id,CASE WHEN msg IS NULL THEN 0 ELSE 1 END AS delivered", "day,chore")):
        state[table] = [dict(row) for row in db.execute(f"SELECT {columns} FROM {table} ORDER BY {order}")]
    state["cutoffs"] = [[d, chore, can_pass(date.fromisoformat(d), t, chore)]
                        for d in selected for chore in CHORES]
    state["today"] = t.date().isoformat()
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def av_valid_dates(selected, t):
    try:
        days = sorted({date.fromisoformat(d) for d in selected})
    except (ValueError, TypeError):
        return None
    if not days or len(days) != len(selected): return None
    if any(not t.date() <= d < t.date() + timedelta(days=AHEAD) or not can_pass(d, t) for d in days):
        return None
    return days


def av_clone(db):
    """Copy just scheduling tables without backup() waiting on a source write transaction."""
    copy = sqlite3.connect(":memory:")
    copy.row_factory = sqlite3.Row
    try:
        for table in ("members", "off", "overrides", "nights"):
            schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
            copy.execute(schema)
            rows = db.execute(f"SELECT * FROM {table}").fetchall()
            if rows:
                copy.executemany(f"INSERT INTO {table} VALUES({','.join('?' for _ in rows[0])})", [tuple(row) for row in rows])
        copy.commit()
        return copy
    except Exception:
        copy.close()
        raise


def av_apply_state(db, uid, days, mode, t):
    """The one availability policy used by simulation and atomic save. No commit or I/O."""
    effects = []
    if mode == "off":
        db.executemany("INSERT OR IGNORE INTO off VALUES(?,?)", [(uid, str(d)) for d in days])
        db.executemany("DELETE FROM overrides WHERE day=? AND walker=?", [(str(d), uid) for d in days])
    elif mode == "on":
        db.executemany("DELETE FROM off WHERE id=? AND day=?", [(uid, str(d)) for d in days])
    else: raise ValueError("Unknown availability mode")
    for day in days:
        for chore in CHORES:
            n = night(db, day, chore)
            if not n or not can_pass(day, t, chore): continue
            cant = set(filter(None, (n["cant"] or "").split(",")))
            if mode == "off":
                if day != t.date() or n["status"] != "on" or n["walker"] != uid: continue
                cant.add(str(uid))
                other = other_walker(db, uid)
                who = other if other and not is_off(db, other, day) and str(other) not in cant else None
            else:
                if n["status"] != "nobody" and not (n["status"] == "on" and not n["msg"]): continue
                cant.discard(str(uid))
                dog = night(db, day)
                dog_walker = dog["walker"] if dog and dog["status"] not in ("nobody", "missed") else pick(db, day)
                who = pick(db, day) if chore == "dogs" else dishes(db, day, dog_walker, sent=False)
                if who and (is_off(db, who, day) or str(who) in cant): who = None
            db.execute("UPDATE nights SET walker=?,status=?,msg=NULL,cant=?,rotation_walker=COALESCE(rotation_walker,walker,?) WHERE day=? AND chore=?",
                       (who, "on" if who else "nobody", ",".join(sorted(cant)), who, str(day), chore))
            effects.append((dict(n), who))
    return effects


def av_plan(db, t):
    """Structured, display-independent schedule for the full visible horizon."""
    result = {}
    for day, dog in week(db, t.date(), n=AHEAD):
        result[str(day)] = {}
        for chore in CHORES:
            n = night(db, day, chore)
            person = (n["walker"] or n["cover_id"]) if n else dog if chore == "dogs" else dishes(db, day, dog)
            state = n["status"] if n else "planned"
            if n and state == "parent": person = n["cover_id"]
            if n and state == "nobody": person = None
            result[str(day)][chore] = {"person": person, "status": state,
                                      "delivered": bool(n and n["msg"]), "closed": not can_pass(day, t, chore)}
    return result


def av_impact(db, uid, proposal, t):
    """Preview the exact save policy, including changes beyond selected dates, privately."""
    copy = av_clone(db)
    try:
        before = av_plan(copy, t)
        av_apply_state(copy, uid, [date.fromisoformat(d) for d in proposal["selected"]], proposal["mode"], t)
        after = av_plan(copy, t)
        return [{"day": day, "selected": day in proposal["selected"], "before": before[day], "after": after[day]}
                for day in before if day in proposal["selected"] or before[day] != after[day]]
    finally:
        copy.close()


def av_impact_text(db, uid, proposal, impact, t):
    """A short decision summary, with optional seven-row pages of the saved impact."""
    lang = lang_of(db, uid)
    nl = lang == "nl"
    selected = [item for item in impact if item["selected"]]
    later = [item for item in impact if not item["selected"]]
    page = proposal.get("impact_page")
    detailed = page is not None
    pages = max(1, (len(impact) + 6) // 7)
    if detailed:
        page = min(max(int(page), 0), pages - 1)
        visible = impact[page * 7:page * 7 + 7]
    else:
        visible = selected[:5]
    def span(items):
        first, last = [date.fromisoformat(items[i]["day"]) for i in (0, -1)]
        left = f"{first.day}/{first.month}"
        return left if first == last else left + f"–{last.day}/{last.month}"
    def label(person):
        if person is None: return "niemand" if nl else "no one"
        if person == uid: return "jij" if nl else "you"
        text = " ".join(name(db, person).split())
        if len(text.encode("utf-16-le")) // 2 > 20:
            text = text.encode("utf-16-le")[:38].decode("utf-16-le", errors="ignore") + "…"
        return text
    lines = [av_text(lang, proposal["mode"]),
             "Voor honden en afwas · nu → na opslaan" if nl else "Dogs and dishes · now → after saving"]
    lines.append((f"{len(selected)} gekozen dagen · {len(later)} andere dagen wijzigen" if nl else
                  f"{len(selected)} selected dates · {len(later)} other dates change"))
    if detailed:
        lines.extend(["", f"Alle dagen · {page + 1}/{pages}" if nl else f"All dates · {page + 1}/{pages}"])
    else:
        lines.extend(["", "Gekozen dagen" if nl else "Selected dates"])
    markers = set()
    for item in visible:
        parts = []
        for chore, icon in (("dogs", "🐕"), ("dishes", "🍽")):
            before, after = item["before"][chore], item["after"][chore]
            if before["person"] == after["person"]:
                text = "=" + label(after["person"]); markers.add("=")
            else:
                text = label(before["person"]) + "→" + label(after["person"])
            mark = "✓" if after["status"] == "done" else "🙋" if after["status"] == "parent" else "⌛" if after["closed"] else "📩" if after["delivered"] else None
            if mark:
                text += " " + mark; markers.add(mark)
            parts.append(icon + " " + text)
        d = date.fromisoformat(item["day"])
        qualifier = (" [gekozen]" if nl else " [selected]") if detailed and item["selected"] else ""
        lines.append(f"{d.day}/{d.month}{qualifier} " + " · ".join(parts))
    if not detailed and len(selected) > 5:
        remaining = selected[5:]
        lines.append(f"+ {len(remaining)} gekozen dagen ({span(remaining)})" if nl else
                     f"+ {len(remaining)} more selected dates ({span(remaining)})")
    if not detailed and later:
        lines.extend(["", (f"Ook gewijzigd in de planning: {len(later)} dagen ({span(later)})." if nl else
                            f"Also changes in the rota: {len(later)} dates ({span(later)}).")])
    if later:
        lines.append("Overnemen telt als een beurt; daardoor schuift de latere planning mee." if nl else
                     "Covering a walk counts as a turn, so later dates shift too.")
    legend = {"=": "ongewijzigd" if nl else "unchanged", "📩": "verstuurd" if nl else "sent",
              "✓": "klaar" if nl else "done", "🙋": "ouder" if nl else "parent", "⌛": "te laat" if nl else "past cutoff"}
    if markers:
        lines.extend(["", " · ".join(mark + " " + legend[mark] for mark in legend if mark in markers)])
    if t.date().isoformat() in proposal["selected"]: lines.append(av_text(lang, "today"))
    lines.append("Nog niet opgeslagen." if nl else "Not saved yet.")
    return "\n".join(lines)


def av_view(db, uid, proposal):
    lang, today = lang_of(db, uid), now().date()
    selected, mode = proposal["selected"], proposal["mode"]
    if proposal["stage"] == "review":
        t = now()
        impact = proposal.get("impact")
        if impact is None: impact = av_impact(db, uid, proposal, t)
        lines = [av_impact_text(db, uid, proposal, impact, t)]
        count = len(selected)
        save = f"{count} {'dag' if count == 1 else 'dagen'} opslaan" if lang == "nl" else f"Save {count} {'day' if count == 1 else 'days'}"
        rows = []
        if proposal.get("impact_page") is not None:
            pages = max(1, (len(impact) + 6) // 7)
            page = min(max(int(proposal["impact_page"]), 0), pages - 1)
            nav = []
            if page: nav.append({"text": "←", "callback_data": f"av:details:{page - 1}"})
            if page + 1 < pages: nav.append({"text": "→", "callback_data": f"av:details:{page + 1}"})
            if nav: rows.append(nav)
            rows.append([{"text": "← Naar overzicht" if lang == "nl" else "← Back to summary", "callback_data": "av:summary"}])
        elif len(impact) > 5 or any(not item["selected"] for item in impact):
            rows.append([{"text": f"Bekijk alle {len(impact)} dagen" if lang == "nl" else f"View all {len(impact)} dates", "callback_data": "av:details:0"}])
        rows.extend([[{"text": save, "callback_data": "av:confirm"}],
                [{"text": av_text(lang, "back"), "callback_data": "av:back"},
                 {"text": av_text(lang, "cancel"), "callback_data": "av:cancel"}]])
    else:
        lines = [av_text(lang, "title"), av_text(lang, mode), "", av_text(lang, "legend")]
        rows = [[{"text": ("✓ " if mode == value else "") + av_text(lang, value),
                  "callback_data": "av:mode:" + value} for value in ("off", "on")]]
        row = []
        for offset in range(AHEAD):
            day = today + timedelta(days=offset)
            label = ("✓ " if str(day) in selected else "") + ("🚫" if is_off(db, uid, day) else "")
            label += f"{day.day}/{day.month}"
            row.append({"text": label, "callback_data": "av:toggle:" + str(day)})
            if len(row) == 7:
                rows.append(row); row = []
        if row: rows.append(row)
        rows.append([{"text": av_text(lang, "review", count=len(selected)), "callback_data": "av:review"},
                     {"text": av_text(lang, "cancel"), "callback_data": "av:cancel"}])
    return "\n".join(lines), {"inline_keyboard": rows}


def open_availability(db, uid, days=None, mode="off", review=False):
    if role_of(db, uid) != "walker": return say(db, uid, "private")
    if mode not in ("off", "on"): return None
    t = now()
    selected = sorted({str(d) for d in (days or [])})
    if selected and not av_valid_dates(selected, t): return say(db, uid, "old")
    if review and not selected: return None
    proposal = {"type": "availability", "selected": selected, "mode": mode,
                "days": [str(t.date())], "expires": t.timestamp() + 3600,
                "stage": "review" if review else "select"}
    if review:
        proposal["snapshot"] = av_snapshot(db, selected, t)
        proposal["impact"] = av_impact(db, uid, proposal, t)
    message = send(uid, *av_view(db, uid, proposal))
    if message: pending(db, uid, message, proposal)
    return message


def commit_availability(db, uid, msg, proposal, t):
    """Commit the whole batch before any Telegram operation; unsent rows remain retryable."""
    effects = []
    with db:
        if not db.in_transaction: db.execute("BEGIN IMMEDIATE")
        days = av_valid_dates(proposal["selected"], t)
        if (not days or role_of(db, uid) != "walker" or proposal.get("stage") != "review"
                or proposal.get("expires", 0) <= t.timestamp()
                or proposal.get("snapshot") != av_snapshot(db, proposal["selected"], t)):
            raise ValueError("Availability review changed")
        effects = av_apply_state(db, uid, days, proposal["mode"], t)
        for old, who in effects:
            if who is not None: continue
            day, chore = old["day"], old["chore"]
            recipients = members(db, "parent") or members(db, "walker")[:1]
            for recipient in recipients:
                rid, lang = recipient["id"], lang_of(db, recipient["id"])
                markup = {"inline_keyboard": [[{"text": tr(lang, "b_pcover"), "callback_data": f"pcover:{chore}:{day}"}]]} if recipient["role"] == "parent" else None
                payload = json.dumps({"text": tr(lang, K("nobody_parents", chore)), "markup": markup,
                                      "valid": {"day": str(day), "chore": chore, "statuses": ["nobody"]}})
                stamp = time.time()
                db.execute("INSERT OR IGNORE INTO outbox(event,recipient,payload,created,expires) VALUES(?,?,?,?,?)",
                           (f"availability-help:{uid}:{msg}:{day}:{chore}:{rid}", rid, payload, stamp, stamp + 86400))
        db.execute("DELETE FROM kv WHERE k=?", (f"p_{uid}_{msg}",))
    # State is committed, even if a reminder cannot be edited or delivered now.
    for old, who in effects:
        try:
            if old["msg"] and old["walker"]:
                text = tr(lang_of(db, old["walker"]), "passed", name=name(db, who)) if who else tr(lang_of(db, old["walker"]), "nobody")
                edit(old["walker"], old["msg"], text)
            if who and date.fromisoformat(old["day"]) == t.date() and (t.hour, t.minute) >= CHORES[old["chore"]][0]:
                deliver(db, old["day"], old["chore"], who)
        except Exception as exc:
            log("availability notification", type(exc).__name__)
    try: drain_outbox(db)
    except Exception as exc: log("availability notification", type(exc).__name__)


def handle_availability_button(db, uid, arg, chat, msg, answer):
    if chat != uid or role_of(db, uid) != "walker": return answer("private")
    proposal, t = peek_pending(db, uid, msg), now()
    if not proposal or proposal.get("type") != "availability" or proposal.get("expires", 0) <= t.timestamp():
        return answer("old")
    lang = lang_of(db, uid)
    if arg == "cancel":
        if edit(chat, msg, tr(lang, "cancelled")):
            pending(db, uid, msg)
            return answer()
        return answer("error")
    updated = dict(proposal)
    if arg == "confirm":
        days = av_valid_dates(proposal["selected"], t)
        if proposal.get("stage") != "review" or not days: return answer("old")
        if proposal.get("snapshot") != av_snapshot(db, proposal["selected"], t):
            return answer("av_stale")
        try: commit_availability(db, uid, msg, proposal, t)
        except ValueError: return answer("av_stale")
        except sqlite3.Error: return answer("error")
        acknowledgment = av_text(lang, "saved", mode=av_text(lang, proposal["mode"]), days=fmt_days(days, lang))
        if not edit(chat, msg, acknowledgment):
            queue_notice(db, uid, acknowledgment, event=f"availability:{uid}:{msg}:{proposal['expires']}")
        return answer("saved")
    if arg == "back":
        updated["stage"] = "select"
        updated.pop("snapshot", None)
        updated.pop("impact", None)
        updated.pop("impact_page", None)
    elif (arg == "summary" or arg.startswith("details:")) and proposal.get("stage") == "review":
        if not proposal.get("impact"): return answer("old")
        if arg == "summary": updated.pop("impact_page", None)
        else:
            try: page = int(arg.split(":", 1)[1])
            except ValueError: return answer("old")
            updated["impact_page"] = min(max(page, 0), (len(proposal["impact"]) - 1) // 7)
    elif arg == "review":
        if not proposal["selected"]: return answer("av_empty")
        if not av_valid_dates(proposal["selected"], t): return answer("old")
        updated["stage"] = "review"
        updated["snapshot"] = av_snapshot(db, proposal["selected"], t)
        updated["impact"] = av_impact(db, uid, updated, t)
        updated.pop("impact_page", None)
    elif arg.startswith("mode:") and proposal.get("stage") == "select":
        mode = arg.split(":", 1)[1]
        if mode not in ("off", "on"): return answer("old")
        updated["mode"] = mode
    elif arg.startswith("toggle:") and proposal.get("stage") == "select":
        day = arg.split(":", 1)[1]
        if not av_valid_dates([day], t): return answer("old")
        selected = set(proposal["selected"])
        if day in selected: selected.remove(day)
        else: selected.add(day)
        updated["selected"] = sorted(selected)
    else: return answer("old")
    if not edit(chat, msg, *av_view(db, uid, updated)): return answer("error")
    pending(db, uid, msg, updated)
    return answer()


S.update({
    "av_stale": ("The plan changed. Go back and review your dates again.",
                 "De planning is veranderd. Ga terug en bekijk je dagen opnieuw."),
    "av_empty": ("Choose at least one date first.", "Kies eerst minstens één dag."),
})


def preview(db, uid, off, walk, target, msg=None):
    lang = lang_of(db, uid)
    lines = ([tr(lang, "preview_off", days=fmt_days(off, lang))] if off else []) + \
            ([tr(lang, "preview_claim", name=name(db, target), days=fmt_days(walk, lang))] if walk else [])
    kb = buttons(db, uid, "confirm", "cancel")
    if walk:
        asks_other = target != uid or any(owner(db, d, now().date()) not in (None, uid) for d in walk)
        if asks_other:
            kb["inline_keyboard"][0][0]["text"] = local_text(db, uid, "Save dates and send request" if off else "Send request",
                                                             "Dagen opslaan en verzoek versturen" if off else "Verzoek versturen")
        else:
            kb["inline_keyboard"][0][0]["text"] = local_text(db, uid, "Save assignment", "Taak opslaan")
    if msg:
        if not edit(uid, msg, "\n".join(lines), kb): return
    else: msg = send(uid, "\n".join(lines), kb)
    if not msg: return
    pending(db, uid, msg, {"type": "preview", "target": target,
                           "off": [d.isoformat() for d in off], "walk": [d.isoformat() for d in walk],
                           "days": [d.isoformat() for d in off + walk]})

def ask_day(db, uid, p, msg=None):
    """Unclear message: ask Off or Walk for each day in turn."""
    day = date.fromisoformat(p["days"][len(p["off"]) + len(p["walk"])])
    text, kb = tr(lang_of(db, uid), "which", day=fmt(day, lang_of(db, uid))), buttons(db, uid, "off", "walk")
    if msg:
        if not edit(uid, msg, text, kb): return
    else: msg = send(uid, text, kb)
    if not msg: return
    pending(db, uid, msg, p)

def on_preview(db, uid, choice, today, chat, msg, answer):
    p = peek_pending(db, uid, msg)
    if not p or p.get("type") not in ("ask", "preview"): return answer("old")
    answer()
    if choice == "cancel":
        pending(db, uid, msg)
        return tell(db, chat, msg, "cancelled", menu_markup(db, uid))
    if choice in ("off", "walk"):
        if p["type"] != "ask": return answer("old")
        p[choice].append(p["days"][len(p["off"]) + len(p["walk"])])
        if len(p["off"]) + len(p["walk"]) < len(p["days"]): return ask_day(db, uid, p, msg)
    future = lambda key: [d for d in map(date.fromisoformat, p[key]) if today <= d < today + timedelta(days=AHEAD)]
    off, walk = future("off"), future("walk")
    if choice != "confirm": return preview(db, uid, off, walk, p.get("target", uid), msg)
    if p["type"] != "preview": return answer("old")
    if not off and not walk:
        pending(db, uid, msg)
        return tell(db, chat, msg, "old", menu_markup(db, uid))
    if any(not can_pass(d, now()) for d in off + walk): return answer("too_late")
    needs_consent = walk and (p["target"] != uid or any(owner(db, d, today) not in (None, uid) for d in walk))
    if needs_consent:
        free = [d for d in walk if p["target"] == uid or not is_off(db, p["target"], d)]
        if not free: return tell(db, chat, msg, "target_off", name=name(db, p["target"]))
        m = ask(db, uid, p["target"], free)
        if not m:
            pending(db, uid, msg, p)  # keep the preview so Confirm can be tapped again
            return tell(db, chat, msg, "retry" if m is None else "cant_reach", buttons(db, uid, "confirm", "cancel"),
                        name=name(db, p["target"]))
        if off: confirm_off(db, uid, off)
        pending(db, uid, msg)
        return tell(db, chat, msg, "asked", menu_markup(db, uid), name=name(db, other_walker(db, uid)))
    if off: confirm_off(db, uid, off)
    if walk: confirm_walk(db, uid, walk)
    pending(db, uid, msg)
    tell(db, chat, msg, "saved", menu_markup(db, uid))

def confirm_off(db, uid, days):
    apply_off(db, uid, days)
    t = now()
    for chore in CHORES:
        n = night(db, t.date(), chore)
        if not (n and t.date() in days and n["walker"] == uid and n["status"] == "on" and can_pass(t.date(), t, chore)):
            continue
        if n["msg"]: pass_night(db, n, uid)
        else:
            other = other_walker(db, uid)
            who = other if other and not is_off(db, other, t.date()) else None
            set_night(db, n["day"], chore, walker=who, status="on" if who else "nobody")
            if who is None: parent_help(db, n["day"], chore, "nobody_parents")

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
    if role_of(db, uid) != "parent": return answer("private")
    chore = chore or "dogs"
    if chore not in CHORES: return answer("old")
    n = night(db, date.fromisoformat(day), chore)
    if not n or n["status"] not in ("on", "nobody") or not done_open(date.fromisoformat(day), now()):
        answer("sorted")
        return tell(db, chat, msg, "sorted")
    answer()
    who = name(db, uid)
    set_night(db, day, chore, status="parent", walker=None, done_at=None, cover_id=uid, cover_msg=msg)
    markup = {"inline_keyboard": [[{"text": tr(lang_of(db, uid), "b_done"), "callback_data": f"pdone:{chore}:{day}"}],
                                   [{"text": tr(lang_of(db, uid), "b_home"), "callback_data": "home"}]]}
    tell(db, chat, msg, "pcover_me", markup)
    if n["walker"] and n["msg"]: tell(db, n["walker"], n["msg"], "pcover_live", name=who)
    for m in members(db, "walker") + members(db, "parent"):
        if m["id"] not in (n["walker"], uid): say(db, m["id"], K("pcover_all", chore), name=who)

def on_parent_done(db, uid, arg, chat, msg, answer):
    if role_of(db, uid) != "parent": return answer("private")
    chore, day = arg.split(":", 1)
    if chore not in CHORES: return answer("old")
    d = date.fromisoformat(day)
    n = night(db, d, chore)
    if not n or n["status"] != "parent" or n["cover_id"] != uid: return answer("settled")
    if not done_open(d, now()): return answer("old")
    hm = now().strftime("%H:%M")
    set_night(db, day, chore, status="done", done_at=hm)
    if n["cover_msg"]: tell(db, uid, n["cover_msg"], K("walked", chore), correction_button(db, uid, d, chore), hm=hm)
    if msg != n["cover_msg"]: show(db, uid, msg, -1)
    if chore == "dogs": completion_notice(db, d, chore, uid, hm)
    answer("saved")

def local_text(db, uid, english, dutch):
    return dutch if lang_of(db, uid) == "nl" else english

def correction_button(db, uid, day, chore):
    return {"inline_keyboard": [[{"text": tr(lang_of(db, uid), "b_undo_done"),
                                   "callback_data": f"correction:{day}:{chore}:undo"}]]}

def private_review(db, uid, text, data, confirm, cancel):
    for key, existing in all_pending(db):
        if (key.startswith(f"p_{uid}_") and existing.get("expires", 0) > now().timestamp()
                and all(existing.get(field) == value for field, value in data.items())):
            return int(key.rsplit("_", 1)[1])
    labels = {"request_preview": ("Send request", "Verzoek versturen", "Keep plan", "Planning behouden"),
              "withdraw": ("Withdraw request", "Verzoek intrekken", "Keep request", "Verzoek behouden"),
              "correction": ("Undo Done", "Klaar terugdraaien", "Keep as is", "Zo laten") if data.get("action") == "undo"
                  else ("Mark completed", "Als klaar opslaan", "Keep as is", "Zo laten")}
    yes_en, yes_nl, no_en, no_nl = labels.get(data.get("type"), ("Save", "Opslaan", "Cancel", "Annuleren"))
    keyboard = {"inline_keyboard": [[{"text": local_text(db, uid, yes_en, yes_nl), "callback_data": confirm},
                                      {"text": local_text(db, uid, no_en, no_nl), "callback_data": cancel}]]}
    if data.get("type") == "request_preview" and impact_needs_details(data.get("impact", [])):
        keyboard["inline_keyboard"].insert(0, [{"text": local_text(db, uid, "View all changes", "Alle wijzigingen bekijken"),
                                               "callback_data": "request_preview_details:0"}])
    msg = send(uid, text, keyboard)
    if msg:
        data["expires"] = now().timestamp() + 3600
        data.setdefault("days", [now().date().isoformat()])
        pending(db, uid, msg, data)
    return msg

def swap_impact(db, target, days, t):
    """Project the actual accepted-swap rules in an isolated copy, without sending."""
    copy = av_clone(db)
    try:
        before = av_plan(copy, t)
        clear_off(copy, target, days)
        apply_claim(copy, target, days)
        if t.date() in days:
            for chore in CHORES:
                n = night(copy, t.date(), chore)
                who = target if chore == "dogs" else dishes(copy, t.date(), target, sent=False)
                if n and n["status"] in ("on", "nobody") and can_pass(t.date(), t, chore) and n["walker"] != who:
                    set_night(copy, str(t.date()), chore, walker=who, status="on", msg=None)
        after = av_plan(copy, t)
        chosen = {str(day) for day in days}
        # Ignore delivery bookkeeping; the review concerns who does what and settled work.
        relevant = lambda plan: {chore: {key: value for key, value in row.items() if key != "delivered"}
                                 for chore, row in plan.items()}
        return [{"day": day, "selected": day in chosen, "before": relevant(before[day]), "after": relevant(after[day])}
                for day in before if day in chosen or relevant(before[day]) != relevant(after[day])]
    finally:
        copy.close()

def impact_needs_details(impact):
    return len(impact) > 5 or any(not item["selected"] for item in impact)

def swap_impact_text(db, uid, impact, page=None):
    nl = lang_of(db, uid) == "nl"
    def render(limit):
        def label(person):
            if person is None: return "niemand" if nl else "no one"
            if person == uid: return "jij" if nl else "you"
            value = " ".join(name(db, person).split())
            encoded = value.encode("utf-16-le")
            return encoded[:2 * (limit - 1)].decode("utf-16-le", errors="ignore") + "…" if len(encoded) > limit * 2 else value
        lines = ["Nu → na akkoord" if nl else "Now → after acceptance"]
        selected = [item for item in impact if item["selected"]]
        later = [item for item in impact if not item["selected"]]
        if page is None:
            entries = selected[:5]
            lines.append(f"{len(selected)} gekozen dag(en)" if nl else f"{len(selected)} selected date(s)")
        else:
            page_number = min(max(0, page), max(0, (len(impact) - 1) // 7))
            entries = impact[page_number * 7:page_number * 7 + 7]
            lines.append(f"{page_number * 7 + 1}–{page_number * 7 + len(entries)} / {len(impact)}")
        for item in entries:
                d = date.fromisoformat(item["day"])
                parts = []
                for chore, icon in (("dogs", "🐕"), ("dishes", "🍽")):
                    old, new = item["before"][chore], item["after"][chore]
                    who = label(new["person"])
                    text = who if old["person"] == new["person"] else label(old["person"]) + " → " + who
                    if new["status"] == "done": text += " ✓"
                    elif new["status"] == "parent": text += " 🙋"
                    parts.append(icon + " " + text)
                lines.append(f"{d.day}/{d.month} · " + " · ".join(parts))
        if page is None:
            if len(selected) > 5:
                lines.append(f"+ {len(selected) - 5} gekozen dagen in de volledige lijst." if nl else f"+ {len(selected) - 5} selected dates in the full list.")
            if later:
                first, last = date.fromisoformat(later[0]["day"]), date.fromisoformat(later[-1]["day"])
                span = f"{first.day}/{first.month}–{last.day}/{last.month}"
                lines.extend(["", f"Ook {len(later)} latere dagen veranderen ({span})." if nl else f"Also changes {len(later)} later dates ({span}).",
                              "Overnemen telt mee als beurt. Bekijk alle wijzigingen voor het volledige overzicht." if nl else "Covering counts as a turn. View all changes for the full plan."])
            else: lines.append("Andere dagen blijven gelijk." if nl else "Other dates stay the same.")
        return "\n".join(lines)
    for limit in (20, 16, 12):
        text = render(limit)
        if len(text.encode("utf-16-le")) // 2 < 3300: return text
    return text

def swap_response_buttons(db, uid):
    return {"inline_keyboard": [[{"text": local_text(db, uid, "View full proposal", "Volledig voorstel bekijken"), "callback_data": "request_details"}],
                                  [{"text": local_text(db, uid, "Accept swap", "Ruil accepteren"), "callback_data": "accept"},
                                   {"text": local_text(db, uid, "Keep current plan", "Planning behouden"), "callback_data": "no"}]]}

def swap_request_text(db, uid, requester, impact, page=None):
    person = " ".join(name(db, requester).split())[:40]
    return local_text(db, uid, f"{person} asks to change the plan.\n\n", f"{person} vraagt om de planning te wijzigen.\n\n") + \
        swap_impact_text(db, uid, impact, page=page) + "\n\n" + local_text(db, uid, "Only changes if you accept.", "Verandert alleen als jij akkoord gaat.")

def request_name(db, uid, limit=32):
    """Keep inbox summaries bounded even with unusually long Telegram names."""
    value = " ".join(name(db, uid).split())
    encoded = value.encode("utf-16-le")
    return encoded[:2 * (limit - 1)].decode("utf-16-le", errors="ignore") + "…" if len(encoded) > 2 * limit else value


def visible_requests(db, uid):
    if role_of(db, uid) != "walker": return []
    entries, t = [], now()
    for key, request in all_pending(db):
        if request.get("type") != "swap": continue
        try:
            _, recipient, message = key.split("_")
            recipient, message = int(recipient), int(message)
            if uid not in (request["from"], recipient) or not swap_valid(db, request, t): continue
            days = sorted(date.fromisoformat(day) for day in request["owners"])
        except (KeyError, ValueError, TypeError): continue
        entries.append((recipient, message, request, days))
    return sorted(entries, key=lambda item: (item[0] != uid, item[3][0], item[1], item[0]))


def request_inbox_page(db, uid, total):
    try: page = int(kv(db, f"requests_page_{uid}") or 0)
    except (ValueError, TypeError): page = 0
    return min(max(page, 0), max(0, (total - 1) // 6))


def request_dates_label(days, lang):
    first, last = days[0], days[-1]
    label = f"{fmt(first, lang)} {month(first, lang)}"
    if len(days) > 1:
        label += f" – {fmt(last, lang)} {month(last, lang)}"
        label += f" · {len(days)} " + ("dagen" if lang == "nl" else "dates")
    return label


def requests_view(db, uid):
    lang = lang_of(db, uid)
    entries = visible_requests(db, uid)
    page = request_inbox_page(db, uid, len(entries))
    pages = max(1, (len(entries) + 5) // 6)
    title = local_text(db, uid, "Swap requests", "Ruilverzoeken")
    lines = [title + (f" · {page + 1}/{pages}" if pages > 1 else ""), ""]
    rows = []
    for index, (recipient, message, request, days) in enumerate(entries[page * 6:page * 6 + 6], page * 6 + 1):
        label = request_dates_label(days, lang)
        person = request_name(db, request["from"] if recipient == uid else recipient)
        status = local_text(db, uid, f"From {person} · your reply needed", f"Van {person} · jouw antwoord nodig") if recipient == uid else \
                 local_text(db, uid, f"Sent to {person} · awaiting their reply", f"Naar {person} · wacht op antwoord")
        lines.extend([f"{index}. {label}", status, ""])
        rows.append([{"text": f"{index} · " + local_text(db, uid, "Review request", "Verzoek bekijken"),
                      "callback_data": f"request_open:{recipient}:{message}"}])
    if not entries: lines.append(local_text(db, uid, "No open requests.", "Geen open verzoeken."))
    nav = []
    if page: nav.append({"text": local_text(db, uid, "◀ Previous", "◀ Vorige"), "callback_data": f"requests:{page - 1}"})
    if page + 1 < pages: nav.append({"text": local_text(db, uid, "Next ▶", "Volgende ▶"), "callback_data": f"requests:{page + 1}"})
    if nav: rows.append(nav)
    return "\n".join(lines).strip(), {"inline_keyboard": rows + menu_markup(db, uid)["inline_keyboard"]}


def request_detail_view(db, uid):
    """Read summary or seven saved impact rows; never project a fresh proposal here."""
    inbox_page = request_inbox_page(db, uid, len(visible_requests(db, uid)))
    back = [{"text": local_text(db, uid, "← Requests", "← Verzoeken"), "callback_data": f"requests:{inbox_page}"}]
    rows = []
    expired = local_text(db, uid, "Request expired or already handled.", "Verzoek verlopen of al afgehandeld.")
    request, recipient, source, impact_page = None, None, None, None
    try:
        selected = json.loads(kv(db, f"request_view_{uid}") or "{}")
        recipient, source = int(selected["recipient"]), int(selected["source"])
        candidate = peek_pending(db, recipient, source)
        if (role_of(db, uid) == "walker" and candidate and candidate.get("type") == "swap"
                and uid in (recipient, candidate["from"]) and swap_valid(db, candidate, now())):
            request = candidate
            if selected.get("page") is not None:
                try: impact_page = max(0, int(selected["page"]))
                except (TypeError, ValueError): impact_page = None
    except (KeyError, ValueError, TypeError): pass
    text = expired
    if request:
        impact = request.get("impact")
        if impact:
            last_page = (len(impact) - 1) // 7
            if impact_page is not None: impact_page = min(impact_page, last_page)
            if recipient == uid:
                text = swap_request_text(db, uid, request["from"], impact, page=impact_page)
            else:
                person = request_name(db, recipient)
                text = local_text(db, uid, f"Your request to {person}", f"Jouw verzoek aan {person}")
                text += "\n\n" + swap_impact_text(db, uid, impact, page=impact_page)
                text += "\n\n" + local_text(db, uid, "Waiting for their reply. The plan has not changed.", "Wacht op antwoord. De planning is nog niet gewijzigd.")
            if impact_page is None:
                if len(impact) > 5 or any(not item["selected"] for item in impact):
                    rows.append([{"text": local_text(db, uid, f"View all {len(impact)} dates", f"Alle {len(impact)} dagen bekijken"),
                                  "callback_data": f"request_page:{recipient}:{source}:0"}])
            else:
                nav = []
                if impact_page > 0:
                    nav.append({"text": local_text(db, uid, "◀ Previous", "◀ Vorige"),
                                "callback_data": f"request_page:{recipient}:{source}:{impact_page - 1}"})
                if impact_page < last_page:
                    nav.append({"text": local_text(db, uid, "Next ▶", "Volgende ▶"),
                                "callback_data": f"request_page:{recipient}:{source}:{impact_page + 1}"})
                if nav: rows.append(nav)
                rows.append([{"text": local_text(db, uid, "← Summary", "← Samenvatting"),
                              "callback_data": f"request_open:{recipient}:{source}"}])
            if recipient == uid:
                rows.append([{"text": local_text(db, uid, "Accept swap", "Ruil accepteren"), "callback_data": f"swap_reply:{source}:accept"},
                             {"text": local_text(db, uid, "Keep current plan", "Planning behouden"), "callback_data": f"swap_reply:{source}:no"}])
        else:
            text = local_text(db, uid, "This older request has no saved review. Ask for a new request before accepting.",
                              "Dit oudere verzoek heeft geen opgeslagen overzicht. Vraag een nieuw verzoek voordat je akkoord gaat.")
        if uid == request["from"] and uid != recipient:
            rows.append([{"text": local_text(db, uid, "Withdraw request", "Verzoek intrekken"), "callback_data": f"withdraw:{recipient}:{source}"}])
    return text, {"inline_keyboard": rows + [back] + menu_markup(db, uid)["inline_keyboard"]}


def on_open_request(db, uid, recipient, source, msg, answer):
    return on_request_page(db, uid, recipient, source, None, msg, answer)


def on_request_page(db, uid, recipient, source, page, msg, answer):
    if role_of(db, uid) != "walker": return answer("private")
    recipient, source = int(recipient), int(source)
    request = peek_pending(db, recipient, source)
    if not request or request.get("type") != "swap": return answer("old")
    if uid not in (request.get("from"), recipient): return answer("private")
    if not swap_valid(db, request, now()): return answer("old")
    if page is not None:
        if not request.get("impact"): return answer("old")
        try: page = min(max(0, int(page)), (len(request["impact"]) - 1) // 7)
        except (TypeError, ValueError): return answer("old")
    kv(db, f"request_view_{uid}", json.dumps({"recipient": recipient, "source": source, "page": page}))
    return show(db, uid, msg, -10)


def show_requests(db, uid, msg):
    return show(db, uid, msg, -9)

def preview_swap(db, uid, day, msg, page, answer):
    other = other_walker(db, uid)
    if not other: return answer("solo")
    current = owner(db, day, now().date())
    target = other_walker(db, current)
    if target is None: return answer("old")
    lang = lang_of(db, uid)
    text = local_text(db, uid, f"Ask {name(db, other)} to swap {fmt(day, lang)}?", f"{name(db, other)} vragen om {fmt(day, lang)} te ruilen?")
    impact = swap_impact(db, target, [day], now())
    text += "\n\n" + swap_impact_text(db, uid, impact)
    text += "\n\n" + local_text(db, uid, "Nothing changes until the other walker accepts.", "Er verandert niets tot de andere loper akkoord gaat.")
    return private_review(db, uid, text, {"type": "request_preview", "day": str(day), "target": target,
                         "owners": {str(day): current}, "impact": impact, "back": [uid, msg, page]}, "request_confirm", "request_cancel")

def handle_request_button(db, uid, kind, arg, chat, msg, answer):
    if role_of(db, uid) != "walker" or chat != uid: return answer("private")
    if kind == "request_open":
        recipient, source = map(int, arg.split(":"))
        return on_open_request(db, uid, recipient, source, msg, answer)
    if kind == "request_page":
        recipient, source, page = map(int, arg.split(":"))
        return on_request_page(db, uid, recipient, source, page, msg, answer)
    if kind == "request_details": return on_request_page(db, uid, uid, msg, 0, msg, answer)
    if kind in ("request_preview_details", "request_preview_summary"):
        p = peek_pending(db, uid, msg)
        if not p or p.get("type") != "request_preview" or p.get("expires", 0) <= now().timestamp(): return answer("old")
        page = None if kind == "request_preview_summary" else min(max(0, int(arg)), max(0, (len(p["impact"]) - 1) // 7))
        text = swap_impact_text(db, uid, p["impact"], page=page)
        rows = []
        if page is None:
            if impact_needs_details(p["impact"]): rows.append([{"text": local_text(db, uid, "View all changes", "Alle wijzigingen bekijken"), "callback_data": "request_preview_details:0"}])
        else:
            nav = []
            if page > 0: nav.append({"text": "←", "callback_data": f"request_preview_details:{page - 1}"})
            if (page + 1) * 7 < len(p["impact"]): nav.append({"text": "→", "callback_data": f"request_preview_details:{page + 1}"})
            if nav: rows.append(nav)
            rows.append([{"text": local_text(db, uid, "Back to summary", "Terug naar overzicht"), "callback_data": "request_preview_summary"}])
        rows.append([{"text": local_text(db, uid, "Send request", "Verzoek versturen"), "callback_data": "request_confirm"},
                     {"text": local_text(db, uid, "Keep plan", "Planning behouden"), "callback_data": "request_cancel"}])
        text += "\n\n" + local_text(db, uid, "Sending asks the other walker. The plan changes only after acceptance.", "Versturen vraagt de andere loper. De planning verandert pas na akkoord.")
        edit(uid, msg, text, {"inline_keyboard": rows})
        return
    if kind == "swap_reply":
        source, action = arg.split(":")
        if action not in ("accept", "no"): return answer("old")
        outcome = on_swap_reply(db, uid, action == "accept", uid, int(source), answer)
        if outcome == "review": return on_open_request(db, uid, uid, int(source), msg, answer)
        return show_requests(db, uid, msg)
    if kind == "withdraw":
        recipient, source = map(int, arg.split(":"))
        request = peek_pending(db, recipient, source)
        if not request or request.get("type") != "swap" or request["from"] != uid: return answer("old")
        text = local_text(db, uid, "Withdraw this request? The current plan will stay as it is.", "Dit verzoek intrekken? De huidige planning blijft staan.")
        return private_review(db, uid, text, {"type": "withdraw", "recipient": recipient, "source": source,
                              "request": request}, "withdraw_confirm", "withdraw_cancel")
    p = peek_pending(db, uid, msg)
    expected = "request_preview" if kind.startswith("request_") else "withdraw"
    if not p or p.get("type") != expected or now().timestamp() >= p["expires"]: return answer("old")
    if kind.endswith("cancel"):
        pending(db, uid, msg)
        return tell(db, uid, msg, "cancelled", menu_markup(db, uid))
    if kind == "request_confirm":
        if not swap_valid(db, p, now()): return answer("old")
        day = date.fromisoformat(p["day"])
        if p.get("impact") is not None and swap_impact(db, p["target"], [day], now()) != p["impact"]:
            pending(db, uid, msg)
            text = local_text(db, uid, "The plan changed. Open the day to review it again.", "De planning is veranderd. Open de dag om opnieuw te kijken.")
            edit(uid, msg, text, menu_markup(db, uid))
            return
        sent = ask(db, uid, p["target"], [day], p["back"])
        if not sent: return answer("retry", name=name(db, other_walker(db, uid)))
        pending(db, uid, msg)
        return tell(db, uid, msg, "asked", menu_markup(db, uid), name=name(db, other_walker(db, uid)))
    recipient, source = p["recipient"], p["source"]
    current = peek_pending(db, recipient, source)
    if current != p["request"] or current.get("from") != uid: return answer("old")
    text = local_text(db, recipient, f"{name(db, uid)} withdrew the swap request. The plan is unchanged.", f"{name(db, uid)} heeft het ruilverzoek ingetrokken. De planning blijft staan.")
    with db:
        db.execute("DELETE FROM kv WHERE k IN (?,?)", (f"p_{recipient}_{source}", f"p_{uid}_{msg}"))
        save_notice(db, recipient, text, menu_markup(db, recipient), f"withdraw:{recipient}:{source}")
    edit(recipient, source, text, {"inline_keyboard": []})
    show_requests(db, uid, msg)
    drain_outbox(db)

def correction_snapshot(row):
    return {key: row[key] for key in ("status", "walker", "cover_id", "done_at", "done_ts")}

def correction_allowed(db, uid, day, chore, action):
    today = now().date()
    if chore not in CHORES or action not in ("done", "undo"): return None
    if not today - timedelta(days=6) <= day <= today: return None
    n = night(db, day, chore)
    if not n or (n["walker"] or n["cover_id"]) != uid: return None
    if action == "undo" and n["status"] != "done": return None
    if action == "done" and n["status"] not in ("on", "parent", "missed"): return None
    return n

def handle_correction_button(db, uid, kind, arg, chat, msg, answer):
    if not role_of(db, uid) or chat != uid: return answer("private")
    if kind == "correction":
        day_text, chore, action = arg.split(":")
        day = date.fromisoformat(day_text)
        row = correction_allowed(db, uid, day, chore, action)
        if not row: return answer("old")
        label = fmt(day, lang_of(db, uid)) + " · " + tr(lang_of(db, uid), chore + "_label")
        text = local_text(db, uid, "Undo this completion?", "Deze bevestiging terugdraaien?") if action == "undo" else local_text(db, uid, "Confirm you completed this task?", "Bevestigen dat jij deze taak hebt gedaan?")
        effect = local_text(db, uid, "Removes one point. The task becomes unconfirmed again.", "Haalt één punt weg. De taak wordt weer onbevestigd.") if action == "undo" else local_text(db, uid, "Adds one point to the month this task belonged to.", "Telt één punt bij de maand waarin deze taak viel.")
        text += "\n\n" + label + "\n" + effect
        if members(db, "parent"): text += "\n" + local_text(db, uid, "Parents will receive the correction.", "Ouders krijgen de correctie te zien.")
        return private_review(db, uid, text, {"type": "correction", "day": day_text, "chore": chore,
                              "action": action, "snapshot": correction_snapshot(row)}, "correct_confirm", "correct_cancel")
    p = peek_pending(db, uid, msg)
    if not p or p.get("type") != "correction" or now().timestamp() >= p["expires"]: return answer("old")
    if kind == "correct_cancel":
        pending(db, uid, msg)
        return tell(db, uid, msg, "cancelled", menu_markup(db, uid))
    day, chore, action = date.fromisoformat(p["day"]), p["chore"], p["action"]
    row = correction_allowed(db, uid, day, chore, action)
    if not row or correction_snapshot(row) != p["snapshot"]: return answer("old")
    t = now()
    status = "done" if action == "done" else ("parent" if row["cover_id"] else "on") if done_open(day, t) else "missed"
    hm, stamp = (t.strftime("%H:%M"), t.timestamp()) if action == "done" else (None, None)
    with db:
        db.execute("UPDATE nights SET status=?,done_at=?,done_ts=? WHERE day=? AND chore=?", (status, hm, stamp, str(day), chore))
        audit = db.execute("INSERT INTO corrections(day,chore,actor,before_status,after_status,created) VALUES(?,?,?,?,?,?)",
                           (str(day), chore, uid, row["status"], status, t.timestamp())).lastrowid
        db.execute("DELETE FROM kv WHERE k=?", (f"p_{uid}_{msg}",))
        for parent in members(db, "parent"):
            recipient = parent["id"]
            label = tr(lang_of(db, recipient), chore + "_label")
            outcome = local_text(db, recipient, "confirmed done", "als klaar bevestigd") if action == "done" else local_text(db, recipient, "completion withdrawn", "klaar-bevestiging ingetrokken")
            text = f"{str(day)} · {label}: {name(db, uid)} · {outcome}"
            save_notice(db, recipient, text, menu_markup(db, recipient), f"correction:{audit}:{recipient}",
                        {"day": str(day), "chore": chore, "statuses": [status], "actor": uid,
                         "done_ts": stamp, "window": False})
    if not edit(uid, msg, *history_view(db, uid)):
        queue_notice(db, uid, local_text(db, uid, "Correction saved. Your points are updated.", "Correctie opgeslagen. Je punten zijn bijgewerkt."), menu_markup(db, uid), f"correction_ack:{audit}")
    drain_outbox(db)
    refresh_weeks(db)
    answer("saved")

def on_start(db, u, arg):
    uid, first = u["id"], u.get("first_name") or "?"
    lang = "nl" if (u.get("language_code") or "").startswith("nl") else "en"
    if role_of(db, uid): return open_home(db, uid)
    if uid == OWNER_ID:
        role = "walker"
        if len(members(db, "walker")) >= 2: return send(uid, tr(lang, "full"))
    else:
        m = re.fullmatch(r"(walker|parent)_(\w+)", arg or "")
        if not m or m.group(2) != kv(db, "code"): return send(uid, tr(lang, "private"))
        role = m.group(1)
        if role == "walker" and len(members(db, "walker")) >= 2: return send(uid, tr(lang, "full"))
        if role == "parent" and len(members(db, "parent")) >= 2: return send(uid, tr(lang, "full_parents"))
    db.execute("INSERT INTO members(id, name, role, joined, lang) VALUES(?,?,?,?,?)",
               (uid, first, role, int(now().timestamp()), lang)); db.commit()
    open_home(db, uid)
    for m in members(db, "walker") + (members(db, "parent") if role == "walker" else []):
        if m["id"] != uid: say(db, m["id"], "joined", name=first)

def on_text(db, msg):
    if "text" not in msg or "forward_origin" in msg or "forward_date" in msg: return  # stickers, photos, forwards
    u, text = msg["from"], msg["text"].strip()
    uid = u["id"]
    if msg["chat"]["type"] != "private": return
    command, _, argument = text.partition(" ")
    command = command.split("@")[0].lower()
    if command == "/start": return on_start(db, u, argument.strip())
    role = role_of(db, uid)
    if not role: return send(uid, tr("en", "private"))
    lang, today = lang_of(db, uid), now().date()
    if command == "/lang": return open_week(db, uid, -4)
    if command in ("/today", "/home", "/menu"): return open_home(db, uid)
    if command == "/help": return open_week(db, uid, -2)
    if command == "/points": return open_week(db, uid, -3)
    if command == "/week": return open_week(db, uid)
    if command in ("/more", "/settings"): return open_week(db, uid, -5)
    if command == "/history": return open_week(db, uid, -7)
    if command == "/availability" and role == "walker": return open_availability(db, uid)
    if command == "/requests": return open_week(db, uid, -9)
    if command == "/family" or (command == "/invite" and uid == OWNER_ID): return open_week(db, uid, -6)
    if text.startswith("/"): return say(db, uid, "commands", menu_markup(db, uid))
    if role != "walker": return send(uid, *help_view(db, uid))
    days = parse_days(text, today)
    if not days: return say(db, uid, "huh", menu_markup(db, uid))
    if any(d >= today + timedelta(days=AHEAD) for d in days):
        return say(db, uid, "too_far", menu_markup(db, uid))
    o = other_walker(db, uid)
    kind, target = intent(text, uid, o, name(db, o) if o else "")
    if kind == "off": return open_availability(db, uid, days=days, mode="off", review=True)
    if kind == "in": return open_availability(db, uid, days=days, mode="on", review=True)
    if kind == "walk": return preview(db, uid, [], days, target)
    if len(days) > 7: return say(db, uid, "huh")
    ask_day(db, uid, {"type": "ask", "target": uid, "off": [], "walk": [], "days": [d.isoformat() for d in days]})

def setup():
    """Telegram's menu remains usable without memorising commands."""
    log("bot", api("getMe")["username"])
    api("setMyName", name="Honduitlaten")
    for lang, descriptions in [(None, ("Today and open chores", "Plan up to 30 days ahead", "Points this month", "How it works", "Language", "Invite family")),
                               ("nl", ("Vandaag en openstaande taken", "Plan tot 30 dagen vooruit", "Punten deze maand", "Hoe werkt het?", "Taal", "Gezin uitnodigen"))]:
        extra = {"language_code": lang} if lang else {}
        commands = [{"command": c, "description": d} for c, d in zip(("today", "week", "points", "help", "lang", "invite"), descriptions)]
        api("setMyCommands", commands=commands[:-1], **extra)
        if OWNER_ID: api("setMyCommands", commands=commands, scope={"type": "chat", "chat_id": OWNER_ID}, **extra)


LOCK = os.environ.get("DOGBOT_LOCK", DB + ".lock")
HEALTH = os.environ.get("DOGBOT_HEALTH", DB + ".health.json")
HEALTH_STATE = {}
STOP = False


def write_health(force=False):
    """One small atomic heartbeat per minute; never include configuration or chat text."""
    stamp = time.time()
    if not force and stamp - HEALTH_STATE.get("written_at", 0) < 60: return
    HEALTH_STATE["written_at"] = stamp
    temporary = HEALTH + ".tmp"
    try:
        with open(temporary, "w") as stream:
            json.dump(HEALTH_STATE, stream)
        os.replace(temporary, HEALTH)
    except OSError as exc:
        log("health", type(exc).__name__)


def request_stop(signum, frame):
    global STOP
    STOP = True


def run():
    global STOP
    if not TOKEN: sys.exit("DOGS_TELEGRAM_BOT_TOKEN not set")
    lock = open(LOCK, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        sys.exit(3)
    if OWNER_ID <= 0:
        lock.close()
        log("OWNER_ID must be a positive Telegram user ID")
        sys.exit(2)
    os.umask(0o077)
    lock.seek(0); lock.truncate(0); lock.write(str(os.getpid())); lock.flush()
    db, previous = None, {}
    STOP = False
    HEALTH_STATE.clear()
    HEALTH_STATE.update(pid=os.getpid(), started_at=time.time(), last_poll=0, last_tick=0,
                        last_error="Starting", stopped=False)
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, request_stop)
        db = connect()
        write_health(True)
        while not STOP:
            try:
                kv(db, "bot", api("getMe")["username"])
                break
            except urllib.error.HTTPError as exc:
                if exc.fp is not None: exc.close()
                if exc.code in (401, 404):
                    log("Telegram rejected the bot token; check .env")
                    sys.exit(2)
                log("startup", exc.code)
                HEALTH_STATE["last_error"] = "Telegram unavailable at startup"
            except Exception as exc:
                log("startup", type(exc).__name__)
                HEALTH_STATE["last_error"] = "Telegram unavailable at startup"
            write_health()
            time.sleep(5)
        if STOP: return
        log("polling")
        # Drain queued taps before creating reminders or overdue alerts.
        ready = False
        while not STOP and not ready:
            result = poll(db, 0)
            ready = result is not None and result < 100
        while not STOP:
            try:
                tick(db, now()); refresh_weeks(db)
                HEALTH_STATE["last_tick"] = time.time()
                HEALTH_STATE["last_error"] = ""
            except Exception as exc:
                log("tick", type(exc).__name__)
                HEALTH_STATE["last_error"] = "Schedule update failed"
            result = poll(db, 25)
            while result == 100 and not STOP: result = poll(db, 0)
            write_health()
    finally:
        HEALTH_STATE["stopped"] = True
        write_health(True)
        if db is not None: db.close()
        lock.close()
        for sig, handler in previous.items(): signal.signal(sig, handler)


def poll(db, timeout):
    offset = int(kv(db, "offset") or 0)
    try:
        updates = api("getUpdates", offset=offset, timeout=timeout, allowed_updates=["message", "callback_query"])
        HEALTH_STATE["last_poll"] = time.time()
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError) and exc.fp is not None: exc.close()
        log("poll", type(exc).__name__)
        HEALTH_STATE["last_error"] = "Telegram connection unavailable"
        write_health()
        time.sleep(5)
        return None
    for update in updates:
        failure_key = f"failed_update_{update['update_id']}"
        try:
            if "callback_query" in update: on_button(db, update["callback_query"])
            elif "message" in update: on_text(db, update["message"])
        except Exception as exc:
            db.rollback()
            attempts = int(kv(db, failure_key) or 0) + 1
            kv(db, failure_key, str(attempts))
            log("handler", update["update_id"], type(exc).__name__)
            HEALTH_STATE["last_error"] = "A user action needs retrying"
            if attempts < 3:
                time.sleep(1)
                return None  # keep offset on the failed update
            source = update.get("callback_query") or update.get("message") or {}
            uid = source.get("from", {}).get("id")
            if uid and role_of(db, uid):
                queue_notice(db, uid, tr(lang_of(db, uid), "error"), event=f"failed:{update['update_id']}")
        # A successful handler is acknowledged only after its state is saved.
        kv(db, "offset", str(update["update_id"] + 1))
        db.execute("DELETE FROM kv WHERE k=?", (failure_key,)); db.commit()
        try: refresh_weeks(db)
        except Exception as exc: log("refresh", type(exc).__name__)
    return len(updates)

if __name__ == "__main__":
    setup() if sys.argv[1:] == ["setup"] else run()
