# -*- coding: utf-8 -*-
"""
ربات کاملاً خودکار:
- خواندن کانال‌های عمومی تلگرام از طریق Web (بدون بات تلگرام)
- ارسال فقط پیام متنی یا عکس‌دار (بدون ویدیو و فایل)
- پیدا کردن خودکار GUID کانال و گروه روبیکا
"""

import time, json, os, re, requests
from bs4 import BeautifulSoup

# ================= تنظیمات =================
SOURCES = [
    "https://t.me/s/iranfnews",
    "https://t.me/s/khabarfuri",
]

RUBIKA_BOT_TOKEN = os.getenv("RUBIKA_BOT_TOKEN")
TARGET_USERNAME = "shortnews_ir"   # بدون @

STATE_FILE = "state.json"
CHECK_INTERVAL = 180
# ==========================================


def get_guids():
    """پیدا کردن خودکار GUID کانال و گروه"""
    url = f"https://botapi.rubika.ir/v3/{RUBIKA_BOT_TOKEN}/getUpdates"
    res = requests.post(url, json={"limit": 20}).json()

    channel_guid = None
    group_guid = None

    for u in res.get("updates", []):
        chat_id = u.get("chat_id") or u.get("update", {}).get("chat_id")
        if not chat_id:
            continue
        if chat_id.startswith("c") and not channel_guid:
            channel_guid = chat_id
        elif chat_id.startswith("g") and not group_guid:
            group_guid = chat_id

    return channel_guid, group_guid


def clean_text(text):
    if not text:
        return ""
    text = re.sub(r"https?://t\.me/\S+", f"@{TARGET_USERNAME}", text)
    text = re.sub(r"@\w+", f"@{TARGET_USERNAME}", text)
    return text.strip()


def fetch_posts(url):
    r = requests.get(url, timeout=20)
    soup = BeautifulSoup(r.text, "html.parser")
    posts = []

    for msg in soup.select("div.tgme_widget_message"):
        pid = msg.get("data-post")
        if not pid:
            continue

        text_el = msg.select_one("div.tgme_widget_message_text")
        text = text_el.get_text("\n", strip=True) if text_el else ""

        photo = None
        img = msg.select_one("a.tgme_widget_message_photo_wrap")
        if img and img.get("style") and "url('" in img.get("style"):
            photo = img.get("style").split("url('")[1].split("')")[0]

        # رد کردن ویدیو و فایل
        if msg.select_one("video") or msg.select_one("a.tgme_widget_message_document"):
            continue

        posts.append({"id": pid, "text": text, "photo": photo})

    return posts


def send_message(guid, text):
    requests.post(
        f"https://botapi.rubika.ir/v3/{RUBIKA_BOT_TOKEN}/sendMessage",
        json={"chat_id": guid, "text": text}
    )


def send_photo(guid, photo, caption=""):
    requests.post(
        f"https://botapi.rubika.ir/v3/{RUBIKA_BOT_TOKEN}/sendPhoto",
        json={"chat_id": guid, "photo_url": photo, "caption": caption}
    )


def main():
    print("🔍 در حال پیدا کردن GUID کانال و گروه...")
    channel_guid, group_guid = get_guids()

    if not channel_guid or not group_guid:
        print("❌ GUID پیدا نشد | یک پیام در کانال و گروه بفرست")
        return

    print("✅ GUIDها پیدا شدند")

    state = {}
    if os.path.exists(STATE_FILE):
        state = json.load(open(STATE_FILE, "r", encoding="utf-8"))

    while True:
        for src in SOURCES:
            last_id = state.get(src)
            posts = fetch_posts(src)
            posts.reverse()

            for p in posts:
                if last_id and p["id"] == last_id:
                    continue

                text = clean_text(p["text"])

                if p["photo"]:
                    send_photo(channel_guid, p["photo"], text)
                    send_photo(group_guid, p["photo"], text)
                else:
                    send_message(channel_guid, text)
                    send_message(group_guid, text)

                state[src] = p["id"]
                json.dump(state, open(STATE_FILE, "w", encoding="utf-8"))
                time.sleep(1)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
