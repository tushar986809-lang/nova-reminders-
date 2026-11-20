"""Reminders: understands Hindi/English like
   "nova remind me kal 7 baje dawai lena" / "10 minute baad chai yaad dilana" / "reminders dikhao".
Saves them to your GitHub repo; the cloud script sends them to Telegram even if the laptop is off."""
import base64
import datetime as dt
import json
import os
import re
import urllib.parse
import uuid
import webbrowser

import requests

from nova_crypto import encrypt

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TRIGGERS = ("remind", "reminder", "yaad dila", "yaad kara", "yaad rakh")
LIST_WORDS = ("dikhao", "list", "show", "kaun se", "kitne")
STOP = {"nova", "remind", "reminder", "reminders", "me", "mujhe", "set", "laga", "do", "dena", "lagao",
        "yaad", "dilana", "dilao", "dila", "karana", "karao", "kara", "ka", "ki", "ko", "to", "for", "at",
        "please", "kal", "aaj", "parso", "tomorrow", "today", "subah", "shaam", "raat", "dopahar",
        "morning", "evening", "night", "afternoon", "baje", "bje", "baad", "mein", "later", "after", "in"}


def parse_when(text, now=None):
    """Returns (due_datetime_IST, message) or None."""
    now = now or dt.datetime.now(IST)
    t = text.lower()

    m = re.search(r"(\d+)\s*(seconds?|secs?|second|minutes?|mins?|ghante|ghanta|hours?|hrs?|din|days?)", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("sec"):
            delta = dt.timedelta(seconds=n)
        elif unit.startswith(("min",)):
            delta = dt.timedelta(minutes=n)
        elif unit.startswith(("gh", "h")):
            delta = dt.timedelta(hours=n)
        else:
            delta = dt.timedelta(days=n)
        due = now + delta
        rest = t[:m.start()] + " " + t[m.end():]
        return due, _clean(rest)

    m = None
    for cand in re.finditer(r"(\d{1,2})(?::(\d{2}))?\s*(baje|bje|am|pm)?", t):
        if cand.group(2) or cand.group(3):  # a bare number is not a time
            m = cand
            break
    if not m:
        return None
    h, mi, mark = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if h > 23 or mi > 59:
        return None
    day = 1 if ("kal" in t or "tomorrow" in t) else 2 if "parso" in t else 0
    pm = mark == "pm" or any(w in t for w in ("shaam", "evening", "raat", "night", "dopahar", "afternoon"))
    am = mark == "am" or any(w in t for w in ("subah", "morning"))
    base = (now + dt.timedelta(days=day)).replace(second=0, microsecond=0)
    if pm and h < 12:
        h += 12
    if am and h == 12:
        h = 0
    cands = [base.replace(hour=h, minute=mi)]
    if not (pm or am) and h < 12:
        cands.append(base.replace(hour=h + 12, minute=mi))
    cands = sorted(c for c in cands if c > now)
    due = cands[0] if cands else base.replace(hour=h, minute=mi) + dt.timedelta(days=1)
    rest = t[:m.start()] + " " + t[m.end():]
    return due, _clean(rest)


def _clean(s):
    words = [w for w in re.split(r"\s+", s) if w and w not in STOP]
    return " ".join(words) or "Reminder"


# ---------- storage (GitHub repo) ----------
def _gh():
    token, repo = os.getenv("GITHUB_TOKEN", "").strip(), os.getenv("GITHUB_REPO", "").strip()
    if not token or not repo or "paste" in token or "tumhara" in repo:  # .env.example ke nakli value ignore
        return None
    return {"url": f"https://api.github.com/repos/{repo}/contents/reminders.json",
            "headers": {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}}


def _load(gh):
    r = requests.get(gh["url"], headers=gh["headers"], timeout=20)
    if r.status_code == 404:
        return [], None
    r.raise_for_status()
    j = r.json()
    return json.loads(base64.b64decode(j["content"]).decode() or "[]"), j["sha"]


def _save(gh, items, sha, msg):
    body = {"message": msg, "content": base64.b64encode(json.dumps(items, indent=1).encode()).decode()}
    if sha:
        body["sha"] = sha
    r = requests.put(gh["url"], headers=gh["headers"], json=body, timeout=20)
    r.raise_for_status()


LOCAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminders_local.json")


def _local_load():
    try:
        with open(LOCAL_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


import threading
import time

_llock = threading.Lock()


def _local_save(items):
    with open(LOCAL_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)


def _local_add(due, message):
    """NOVA khud bolkar yaad dilayega (jab NOVA chal raha ho)."""
    with _llock:
        items = [i for i in _local_load() if not i.get("done")]
        items.append({"due_utc": due.astimezone(dt.timezone.utc).isoformat(), "text": message, "done": False})
        _local_save(items)


def start_scheduler(announce):
    """Background mein samay dekhta hai; waqt aate hi announce(text) bulata hai.
    NOVA band tha aur reminder nikal gaya (12 ghante tak) to shuru hote hi bata dega."""
    def loop():
        first = True
        while True:
            try:
                now = dt.datetime.now(dt.timezone.utc)
                with _llock:
                    items = _local_load()
                    fire = []
                    for i in items:
                        if i.get("done"):
                            continue
                        late = (now - dt.datetime.fromisoformat(i["due_utc"])).total_seconds()
                        if late >= 0:
                            i["done"] = True
                            if late < 12 * 3600:
                                fire.append((i["text"], late))
                    if fire:
                        _local_save(items)
                for text, late in fire:
                    pre = "Reminder miss ho gaya tha: " if late > 120 else "Tushar, yaad dila raha hoon: "
                    announce(pre + text)
            except Exception as e:
                if first:
                    print("[reminder] scheduler error:", str(e)[:100])
            first = False
            time.sleep(2)
    threading.Thread(target=loop, daemon=True).start()


def _ntfy_add(due, message):
    """ntfy.sh ke server ko 'is time par bhejna' bol do. Laptop band ho tab bhi phone par aayega.
    (ntfy 3 din tak aage ke reminders rakh sakta hai)"""
    topic = os.getenv("NTFY_TOPIC", "").strip()
    now = dt.datetime.now(IST)
    if (due - now).total_seconds() > 3 * 24 * 3600 - 120:
        raise RuntimeError("ntfy mein 3 din se zyada door ka reminder nahi lag sakta")
    due = max(due, now + dt.timedelta(seconds=15))  # ntfy ka minimum 10 second hai
    headers = {"X-Delay": due.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "X-Title": "NOVA Reminder", "X-Priority": "5", "X-Tags": "alarm_clock"}
    r = requests.post(f"https://ntfy.sh/{topic}", data=message.encode("utf-8"), headers=headers, timeout=15)
    r.raise_for_status()
    items = [i for i in _local_load() if i["due_utc"] > now.astimezone(dt.timezone.utc).isoformat()]
    items.append({"due_utc": due.astimezone(dt.timezone.utc).isoformat(), "text": message})
    with open(LOCAL_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)


def _calendar_open(due, message):
    """Koi setup nahi: Google Calendar mein bhara hua event khulta hai, bas Save dabao.
    Phone ka Calendar (jo pehle se hota hai) us time par alarm bajata hai, laptop band ho tab bhi."""
    fmt = "%Y%m%dT%H%M%S"
    start = due.astimezone(IST)
    params = {"action": "TEMPLATE", "text": "⏰ " + message, "ctz": "Asia/Kolkata",
              "dates": f"{start.strftime(fmt)}/{(start + dt.timedelta(minutes=10)).strftime(fmt)}",
              "details": "NOVA reminder"}
    webbrowser.open("https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params))


def add_reminder(due, message, phone=False):
    """Returns 'ntfy' / 'github' / 'local' / 'both' (kis tareeke se laga).
    phone=True: NOVA ke saath-saath Google Calendar bhi khule (laptop band hone par phone yaad dilaye)."""
    if os.getenv("NTFY_TOPIC", "").strip():
        _ntfy_add(due, message)
        return "ntfy"
    if not _gh():
        _local_add(due, message)
        if phone:
            _calendar_open(due, message)
            return "both"
        return "local"
    item = {"id": uuid.uuid4().hex[:8], "due_utc": due.astimezone(dt.timezone.utc).isoformat(),
            "text": encrypt(message), "sent": False}
    gh = _gh()
    for _ in range(3):  # retry if the cloud bot committed at the same moment
        try:
            items, sha = _load(gh)
            items.append(item)
            _save(gh, items, sha, "add reminder")
            _local_add(due, message)  # laptop on ho to NOVA khud bhi bole
            return "github"
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code not in (409, 422):
                raise
    raise RuntimeError("GitHub save nahi ho paya, dobara try karo")


def pending_count():
    if os.getenv("NTFY_TOPIC", "").strip():
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        return sorted(i["due_utc"] for i in _local_load() if i["due_utc"] > now)
    gh = _gh()
    if not gh:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        return sorted(i["due_utc"] for i in _local_load() if not i.get("done") and i["due_utc"] > now)
    items, _ = _load(gh)
    return sorted(i["due_utc"] for i in items if not i.get("sent"))


def skill_reminder(text):
    if any(w in text for w in LIST_WORDS) and "remind" in text:
        try:
            due = pending_count()
        except Exception as e:
            return f"Reminders nahi dekh paaya: {e}"
        if not due:
            return "Koi pending reminder nahi hai."
        nxt = dt.datetime.fromisoformat(due[0]).astimezone(IST).strftime("%d %b, %I:%M %p")
        return f"{len(due)} reminder pending hain. Sabse pehla {nxt} par hai."

    if not any(w in text for w in TRIGGERS):
        return None
    parsed = parse_when(text)
    if not parsed:
        return "Time samajh nahi aaya. Aise bolo: kal 7 baje dawai ka reminder, ya 10 minute baad chai."
    due, message = parsed
    try:
        phone = any(w in text for w in ("phone", "calendar", "mobile"))
        mode = add_reminder(due, message, phone)
    except Exception as e:
        return f"Reminder save nahi ho paya: {e}"
    when = due.strftime("%d %b, %I:%M %p")
    if mode == "local":
        return f"Theek hai, {when} par main khud yaad dilaunga: {message}."
    if mode == "both":
        return (f"Theek hai, {when} par main yaad dilaunga. Phone ke liye Calendar bhi khul gaya hai, "
                "Save dabao to laptop band hone par bhi phone bata dega.")
    return f"Theek hai, {when} par yaad dilaunga: {message}. Laptop band hoga tab bhi phone par call aayegi."
