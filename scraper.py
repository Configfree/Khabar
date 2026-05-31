import requests
import re
import os
import time
import json
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ========== تنظیمات روبیکا ==========
RUBIKA_TOKEN = os.environ.get('RUBIKA_TOKEN')
RUBIKA_CHANNEL = "@NewsLine360"
RUBIKA_HEADERS = {"Content-Type": "application/json"}

# ========== تنظیمات تلگرام ==========
SOURCE_CHANNEL = "KhabarFuri"
LAST_ID_FILE = "last_message_id.txt"

# ========== سشن‌های سراسری ==========
# NOTE: برای ۴ worker همزمان، این سشن‌ها thread-safe هستند
TG_SESSION = requests.Session()
TG_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Connection": "keep-alive"
})

RUBIKA_SESSION = requests.Session()
RUBIKA_SESSION.headers.update(RUBIKA_HEADERS)

# ========== فوتر خطی ساده ==========
FOOTER = """
────────────────────
@NewsLine360
────────────────────
"""

# ========== کامپایل Regexها ==========
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F1E0-\U0001F1FF"
    "]+",
    flags=re.UNICODE
)

SOURCE_LINK_PATTERN = re.compile(r'@KhabarFuri\b')
SOURCE_URL_PATTERN = re.compile(r'https?://t\.me/(?:s/)?KhabarFuri[^\s]*')
MULTI_SPACE_PATTERN = re.compile(r'[ ]{2,}')
MULTI_NEWLINE_PATTERN = re.compile(r'\n{3,}')
KHABARFURI_PATTERN = re.compile(r'@KhabarFuri\s*')
PHOTO_URL_PATTERN = re.compile(r"url\('([^']+)'\)")
PHOTO_SIZE_PATTERN = re.compile(r'_[sb]\d+\.jpg')

def remove_all_emojis(text):
    """حذف همه ایموجی‌ها - پرچم‌ها و صورتک‌ها"""
    if not text:
        return ""
    
    text = EMOJI_PATTERN.sub('', text)
    text = MULTI_SPACE_PATTERN.sub(' ', text)
    text = MULTI_NEWLINE_PATTERN.sub('\n\n', text)
    
    return text.strip()

def replace_source_links(text):
    """جایگزینی لینک‌های کانال مبدأ با کانال خودمون"""
    if not text:
        return ""
    
    text = SOURCE_LINK_PATTERN.sub(RUBIKA_CHANNEL, text)
    text = SOURCE_URL_PATTERN.sub('https://t.me/NewsLine360', text)
    
    return text

def add_footer(text):
    """اضافه کردن فوتر خطی"""
    if not text or not text.strip():
        return FOOTER.strip()
    
    return f"{text.strip()}\n\n{FOOTER.strip()}"

def clean_and_format(text):
    """تمیزکاری کامل متن قبل از ارسال"""
    if not text:
        return FOOTER.strip()
    
    text = KHABARFURI_PATTERN.sub('', text)
    text = remove_all_emojis(text)
    text = replace_source_links(text)
    text = add_footer(text)
    
    return text

def send_to_rubika(content_type, file_path=None, caption=""):
    """ارسال به روبیکا با متن تمیز شده"""
    if not RUBIKA_TOKEN:
        print("❌ RUBIKA_TOKEN تنظیم نشده است")
        return None
    
    rubika_url = f"https://botapi.rubika.ir/v3/{RUBIKA_TOKEN}/"
    cleaned_caption = clean_and_format(caption)
    
    # فقط متن
    if content_type == "text":
        payload = {"chat_id": RUBIKA_CHANNEL, "text": cleaned_caption}
        response = RUBIKA_SESSION.post(
            rubika_url + "sendMessage",
            data=json.dumps(payload),
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "OK":
                print(f"   ✓ متن ارسال شد")
            else:
                print(f"   ✗ خطا: {result}")
        return response
    
    # عکس یا ویدیو
    elif content_type in ["photo", "video"]:
        file_type = "Image" if content_type == "photo" else "Video"
        
        # مرحله 1: دریافت آدرس آپلود
        resp_upload = RUBIKA_SESSION.post(
            rubika_url + "requestSendFile",
            data=json.dumps({"type": file_type}),
            timeout=10
        )
        
        if resp_upload.status_code != 200:
            print(f"   ✗ خطا در دریافت آدرس آپلود")
            return None
            
        upload_data = resp_upload.json()
        if upload_data.get("status") != "OK":
            print(f"   ✗ خطا: {upload_data}")
            return None
            
        upload_url = upload_data["data"]["upload_url"]
        
        # مرحله 2: آپلود فایل
        with open(file_path, 'rb') as f:
            resp_file = RUBIKA_SESSION.post(upload_url, files={"file": f}, timeout=30)
            
        file_data = resp_file.json()
        if file_data.get("status") != "OK":
            print(f"   ✗ خطا در آپلود فایل")
            return None
            
        file_id = file_data["data"]["file_id"]
        
        # مرحله 3: ارسال به کانال
        payload = {
            "chat_id": RUBIKA_CHANNEL,
            "file_id": file_id,
            "text": cleaned_caption
        }
        response = RUBIKA_SESSION.post(
            rubika_url + "sendFile",
            data=json.dumps(payload),
            timeout=15
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "OK":
                print(f"   ✓ {content_type} ارسال شد")
            else:
                print(f"   ✗ خطا: {result}")
        return response

def download_file(url, file_path):
    """دانلود فایل از لینک با streaming بهینه"""
    try:
        response = TG_SESSION.get(url, stream=True, timeout=30)
        if response.status_code == 200:
            with open(file_path, 'wb') as f:
                # chunk size 256KB برای دانلود سریعتر
                for chunk in response.iter_content(chunk_size=262144):
                    f.write(chunk)
            return True
    except Exception:
        pass
    return False

def safe_remove_file(file_path):
    """حذف امن فایل بدون ایجاد خطا"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass  # خطای حذف فایل نادیده گرفته میشه

def extract_media_urls(message):
    """استخراج لینک عکس و ویدیو از پیام"""
    # عکس
    photo = message.find('a', class_='tgme_widget_message_photo_wrap')
    if photo:
        style = photo.get('style', '')
        match = PHOTO_URL_PATTERN.search(style)
        if match:
            url = match.group(1)
            url = PHOTO_SIZE_PATTERN.sub('.jpg', url)
            return url, 'photo'
    
    # ویدیو
    video = message.find('video')
    if video and video.get('src'):
        return video['src'], 'video'
    
    source = message.find('source')
    if source and source.get('src'):
        return source['src'], 'video'
    
    return None, None

def get_last_processed_id():
    """خواندن آخرین ID پردازش شده"""
    if os.path.exists(LAST_ID_FILE):
        with open(LAST_ID_FILE, 'r') as f:
            try:
                return int(f.read().strip())
            except Exception:
                return 0
    return 0

def save_last_processed_id(msg_id):
    """ذخیره آخرین ID پردازش شده"""
    try:
        with open(LAST_ID_FILE, 'w') as f:
            f.write(str(msg_id))
    except Exception:
        pass  # خطای ذخیره نادیده گرفته میشه

def process_single_message(msg_id, msg):
    """پردازش یک پیام - قابل استفاده در threading"""
    print(f"\n📥 پردازش پیام {msg_id}")
    
    # استخراج متن با find سریعتر
    text_elem = msg.find(class_='tgme_widget_message_text')
    text = text_elem.get_text() if text_elem else ""
    
    # فقط پیام‌هایی که تگ دارند
    if '@KhabarFuri' not in text:
        print("   ⏩ رد شد (تگ @KhabarFuri ندارد)")
        return False
    
    print(f"   📝 متن: {text[:80]}..." if len(text) > 80 else f"   📝 متن: {text}")
    
    # استخراج لینک رسانه
    media_url, media_type = extract_media_urls(msg)
    
    try:
        if media_url and media_type == 'photo':
            print(f"   📸 در حال دانلود عکس...")
            file_path = f"downloads/{msg_id}.jpg"
            if download_file(media_url, file_path):
                send_to_rubika("photo", file_path, text)
                safe_remove_file(file_path)
            else:
                print(f"   ✗ خطا در دانلود عکس")
        
        elif media_url and media_type == 'video':
            print(f"   🎥 در حال دانلود ویدیو...")
            file_path = f"downloads/{msg_id}.mp4"
            if download_file(media_url, file_path):
                send_to_rubika("video", file_path, text)
                safe_remove_file(file_path)
            else:
                print(f"   ✗ خطا در دانلود ویدیو")
        
        else:
            print(f"   📝 ارسال متن...")
            send_to_rubika("text", caption=text)
        
        return True
        
    except Exception as e:
        print(f"   ✗ خطا: {e}")
        return False

def scrape():
    """تابع اصلی اسکرپ کانال"""
    print("=" * 55)
    print("       اسکرپ کانال خبری - NewsLine360")
    print("=" * 55)
    
    if not RUBIKA_TOKEN:
        print("❌ خطا: RUBIKA_TOKEN در محیط تعریف نشده است")
        return
    
    # ساخت پوشه موقت
    os.makedirs("downloads", exist_ok=True)
    
    # دریافت صفحه کانال
    url = f"https://t.me/s/{SOURCE_CHANNEL}"
    print(f"\n🔍 در حال بررسی کانال: t.me/{SOURCE_CHANNEL}")
    
    try:
        response = TG_SESSION.get(url, timeout=15)
    except Exception as e:
        print(f"❌ خطا در اتصال: {e}")
        return
    
    if response.status_code != 200:
        print(f"❌ خطا: کد وضعیت {response.status_code}")
        return
    
    # استفاده از parser سریعتر (lxml اگر نصب باشه)
    try:
        soup = BeautifulSoup(response.text, "lxml")
    except Exception:
        soup = BeautifulSoup(response.text, "html.parser")
    
    messages = soup.select('.tgme_widget_message')
    
    if not messages:
        print("⚠️ هیچ پیامی پیدا نشد")
        return
    
    last_id = get_last_processed_id()
    print(f"📌 آخرین ID پردازش شده: {last_id}")
    
    # پیدا کردن پیام‌های جدید
    new_messages = []
    for msg in messages:
        data_post = msg.get('data-post', '')
        if data_post:
            try:
                msg_id = int(data_post.split('/')[-1])
                if msg_id > last_id:
                    new_messages.append((msg_id, msg))
            except Exception:
                pass
    
    # مرتب سازی از قدیمی به جدید
    new_messages.sort(key=lambda x: x[0])
    
    if not new_messages:
        print("📭 پیام جدیدی یافت نشد")
        return
    
    print(f"📨 {len(new_messages)} پیام جدید پیدا شد")
    print("-" * 55)
    
    # پردازش موازی پیام‌ها
    processed_ids = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {
            executor.submit(process_single_message, msg_id, msg): msg_id
            for msg_id, msg in new_messages
        }
        
        for future in as_completed(future_map):
            msg_id = future_map[future]
            try:
                if future.result():
                    processed_ids.append(msg_id)
            except Exception as e:
                print(f"   ✗ خطا در پردازش پیام {msg_id}: {e}")
    
    # ذخیره آخرین ID پردازش شده
    if processed_ids:
        save_last_processed_id(max(processed_ids))
    
    print("\n" + "=" * 55)
    print("✅ اسکرپ با موفقیت کامل شد")
    print("=" * 55)

if __name__ == "__main__":
    scrape()
