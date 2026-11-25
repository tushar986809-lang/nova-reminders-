"""Runs in the cloud (GitHub Actions) every ~5 minutes, even when your laptop is off.
Sends due reminders to Telegram (and optionally a real phone call via Twilio)."""
import datetime as dt
import json
import os
from xml.sax.saxutils import escape

import requests

from nova_crypto import decrypt

FILE = "reminders.json"


def telegram(text):
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram not configured")
        return False
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text}, timeout=20)
    print("telegram:", r.status_code)
    return r.ok


def twilio_call(text):
    sid, tok = (os.getenv("TWILIO_SID") or "").strip(), (os.getenv("TWILIO_TOKEN") or "").strip()
    src, dst = (os.getenv("TWILIO_FROM") or "").strip(), (os.getenv("MY_PHONE") or "").strip()
    if not (sid and tok and src and dst):
        return False
    twiml = f"<Response><Say language='en-IN'>Reminder from Nova. {escape(text)}</Say></Response>"
    r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json",
                      auth=(sid, tok), data={"To": dst, "From": src, "Twiml": twiml}, timeout=20)
    print("twilio:", r.status_code)
    if not r.ok:  # asli wajah dikhao (isme koi secret nahi hota)
        try:
            j = r.json()
            print("twilio error:", j.get("code"), j.get("message"))
        except ValueError:
            print("twilio error text:", r.text[:300])
    return r.ok


def main():
    with open(FILE, encoding="utf-8") as f:
        items = json.load(f)
    now = dt.datetime.now(dt.timezone.utc)
    changed = False
    for it in items:
        if it.get("sent"):
            continue
        due = dt.datetime.fromisoformat(it["due_utc"])
        if due > now:
            continue
        try:
            text = decrypt(it["text"])
        except Exception as e:
            print("decrypt failed:", type(e).__name__)
            text = "Reminder (text padh nahi paya)"
        ok_tg = telegram(f"⏰ Reminder: {text}")
        ok_call = twilio_call(text)
        if ok_tg or ok_call:  # koi bhi tareeka chala to dobara nahi bhejna
            it["sent"] = True
            changed = True
    # drop reminders that were sent more than 2 days ago
    cutoff = now - dt.timedelta(days=2)
    items = [i for i in items if not (i.get("sent") and dt.datetime.fromisoformat(i["due_utc"]) < cutoff)]
    if changed:
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=1)


if __name__ == "__main__":
    main()
