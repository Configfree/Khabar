-- coding: utf-8 --

""" نسخه نهایی فقط مخصوص کانال روبیکا (بدون گروه)

✔️ بدون نیاز به ادمین گروه ✔️ GUID کانال فقط یک‌بار گرفته و ذخیره می‌شود ✔️ مناسب GitHub Actions ✔️ دریافت محتوا از کانال‌های عمومی تلگرام (Web) ✔️ ارسال فقط پیام متنی یا دارای عکس (بدون ویدیو و فایل) """

import time, json, os, re, requests from bs4 import BeautifulSoup

================= تنظیمات =================

SOURCES = [ "https://t.me/s/iranfnews", "https://t.me/s/khabarfuri", ]

RUBIKA_BOT_TOKEN = os.getenv("RUBIKA_BOT_TOKEN") TARGET_USERNAME = "shortnews_ir"   # بدون @

STATE_FILE = "state.json" GUID_FILE = "channel_guid.json" CHECK_INTERVAL = 180

==========================================

def load_channel_guid(): if os.path.exists(GUID_FILE): return json.load(open(GUID_FILE, "r", encoding="utf-8")).get("channel") return None

def save_channel_guid(guid): json.dump({"channel": guid}, open(GUID_FILE, "w", encoding="utf-8"))

def find_channel_guid(): """GUID کانال را از getUpdates فقط یک‌بار می‌گیرد""" url = f"https://botapi.rubika.ir/v3/{RUBIKA_BOT_TOKEN}/getUpdates" res = requests.post(url, json={"limit": 50}).json()

for u in res.get("updates", []):
    chat_id = u.get("chat_id") or u.get("update", {}).get("chat_id")
    if chat_id and chat_id.startswith("c"):
        save_channel_guid(chat_id)
        return chat_id
return None

def clean_text(text): if not text: return "" text = re.sub(r"https?://t.me/\S+", f"@{TARGET_USERNAME}", text) text = re.sub(r"@\w+", f"@{TARGET_USERNAME}", text) return text.strip()

def fetch_posts(url): r = requests.get(url, timeout=20) soup = BeautifulSoup(r.text, "html.parser") posts = []

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

def send_message(channel_guid, text): requests.post( f"https://botapi.rubika.ir/v3/{RUBIKA_BOT_TOKEN}/sendMessage", json={"chat_id": channel_guid, "text": text} )

def send_photo(channel_guid, photo, caption=""): requests.post( f"https://botapi.rubika.ir/v3/{RUBIKA_BOT_TOKEN}/sendPhoto", json={"chat_id": channel_guid, "photo_url": photo, "caption": caption} )

def main(): channel_guid = load_channel_guid()

if not channel_guid:
    print("🔍 GUID کانال ذخیره نشده، در حال جستجو...")
    channel_guid = find_channel_guid()
    if not channel_guid:
        print("❌ GUID کانال پیدا نشد | بات باید ادمین کانال باشد و یک پیام تست بفرستی")
        return
    print("✅ GUID کانال ذخیره شد")

state = {}
if os.path.exists(STATE_FILE):
    state = json.load(open(STATE_FILE, "r", encoding="utf-8"))

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
        else:
            send_message(channel_guid, text)

        state[src] = p["id"]
        json.dump(state, open(STATE_FILE, "w", encoding="utf-8"))
        time.sleep(1)

if name == "main": main()
