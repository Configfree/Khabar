# -*- coding: utf-8 -*-

"""
Rubika Channel Forwarder (Telegram Web Scraper)
Only Channel | No Group | Stable Version
"""

import os
import time
import json
import re
import requests
from bs4 import BeautifulSoup

# ================== CONFIG ==================
SOURCES = [
    "https://t.me/s/iranfnews",
    "https://t.me/s/khabarfuri",
]

RUBIKA_TOKEN = os.getenv("RUBIKA_BOT_TOKEN")
TARGET_USERNAME = "shortnews_ir"  # بدون @

STATE_FILE = "state.json"
GUID_FILE = "channel_guid.json"
# ============================================


# ---------- Utils ----------
def log(msg):
    print(msg, flush=True)


def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------- Rubika ----------
def get_channel_guid():
    if os.path.exists(GUID_FILE):
        return load_json(GUID_FILE).get("channel")

    url = f"https://botapi.rubika.ir/v3/{RUBIKA_TOKEN}/getUpdates"
    try:
        res = requests.post(url, json={"limit": 50}, timeout=20).json()
    except Exception:
        return None

    for upd in res.get("updates", []):
        chat_id = upd.get("chat_id") or upd.get("update", {}).get("chat_id")
        if isinstance(chat_id, str) and chat_id.startswith("c"):
            save_json(GUID_FILE, {"channel": chat_id})
            return chat_id

    return None


def send_message(chat_id, text):
    if not text:
        return
    requests.post(
        f"https://botapi.rubika.ir/v3/{RUBIKA_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=20,
    )


def send_photo(chat_id, photo_url, caption=""):
    requests.post(
        f"https://botapi.rubika.ir/v3/{RUBIKA_TOKEN}/sendPhoto",
        json={
            "chat_id": chat_id,
            "photo_url": photo_url,
            "caption": caption,
        },
        timeout=20,
    )


# ---------- Telegram Web ----------
def clean_text(text):
    if not text:
        return ""

    text = re.sub(r"https?://t\.me/\S+", f"@{TARGET_USERNAME}", text)
    text = re.sub(r"@\w+", f"@{TARGET_USERNAME}", text)

    return text.strip()


def fetch_posts(source_url):
    posts = []

    try:
        r = requests.get(source_url, timeout=30)
    except Exception:
        return posts

    soup = BeautifulSoup(r.text, "html.parser")

    for msg in soup.select("div.tgme_widget_message"):
        post_id = msg.get("data-post")
        if not post_id:
            continue

        # skip video & files
        if msg.select_one("video") or msg.select_one(".tgme_widget_message_document"):
            continue

        text_el = msg.select_one(".tgme_widget_message_text")
        text = text_el.get_text("\n", strip=True) if text_el else ""

        photo = None
        photo_el = msg.select_one(".tgme_widget_message_photo_wrap")
        if photo_el and "url('" in photo_el.get("style", ""):
            photo = photo_el["style"].split("url('")[1].split("')")[0]

        posts.append({
            "id": post_id,
            "text": text,
            "photo": photo
        })

    return posts


# ---------- Main ----------
def main():
    if not RUBIKA_TOKEN:
        log("❌ RUBIKA_BOT_TOKEN تنظیم نشده")
        return

    channel_guid = get_channel_guid()
    if not channel_guid:
        log("❌ GUID کانال پیدا نشد | بات باید ادمین کانال باشد و یک پیام تست ارسال شود")
        return

    log("✅ بات فعال شد")

    state = load_json(STATE_FILE)

    for src in SOURCES:
        last_id = state.get(src)
        posts = fetch_posts(src)
        posts.reverse()

        for p in posts:
            if last_id == p["id"]:
                continue

            text = clean_text(p["text"])

            if p["photo"]:
                send_photo(channel_guid, p["photo"], text)
            else:
                send_message(channel_guid, text)

            state[src] = p["id"]
            save_json(STATE_FILE, state)
            time.sleep(1)


if __name__ == "__main__":
    main()
