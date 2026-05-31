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

# ========== فوتر خطی ساده ==========
FOOTER = """
────────────────────
@NewsLine360
────────────────────
"""

# کامپایل regexها برای سرعت (امن)
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

def remove_all_emojis(text):
    """حذف همه ایموجی‌ها - پرچم‌ها و صورتک‌ها"""
    if not text:
        return ""
    
    text = EMOJI_PATTERN.sub(r'', text)
    text = re.sub(r'[ ]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def replace_source_links(text):
    """جایگزینی لینک‌های کانال مبدأ با کانال خودمون"""
    if not text:
        return ""
    
    text = re.sub(r'@KhabarFuri\b', RUBIKA_CHANNEL, text)
    text = re.sub(r'https?://t\.me/KhabarFuri[^\s]*', 'https://t.me/NewsLine360', text)
    text = re.sub(r'https?://t\.me/s/KhabarFuri[^\s]*', 'https://t.me/NewsLine360', text)
    
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
    
    text = re.sub(r'@KhabarFuri\s*', '', text)
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
        response = requests.post(
            rubika_url + "sendMessage",
            data=json.dumps(payload),
            headers=RUBIKA_HEADERS
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
        resp_upload = requests.post(
            rubika_url + "requestSendFile",
            data=json.dumps({"type": file_type}),
            headers=RUBIKA_HEADERS
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
            resp_file = requests.post(upload_url, files={"file": f})
            
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
        response = requests.post(
            rubika_url + "sendFile",
            data=json.dumps(payload),
            headers=RUBIKA_HEADERS
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "OK":
                print(f"   ✓ {content_type} ارسال شد")
            else:
                print(f"   ✗ خطا: {result}")
        return response

def download_file(url, file_path):
    """دانلود فایل از لینک با chunk بزرگتر برای سرعت"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, stream=True, headers=headers, timeout=30)
        if response.status_code == 200:
            with open(file_path, 'wb') as f:
                # افزایش سایز chunk از 8KB به 256KB برای سرعت بیشتر
                for chunk in response.iter_content(chunk_size=262144):
                    f.write(chunk)
            return True
    except:
        pass
    return False

def extract_media_urls(message):
    """استخراج لینک عکس و ویدیو از پیام"""
    # عکس
    photo = message.select_one('a.tgme_widget_message_photo_wrap')
    if photo:
        style = photo.get('style', '')
        match = re.search(r"url\('([^']+)'\)", style)
        if match:
            url = match.group(1)
            url = re.sub(r'_[sb]\d+\.jpg', '.jpg', url)
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
            except:
                return 0
    return 0

def save_last_processed_id(msg_id):
    """ذخیره آخرین ID پردازش شده"""
    with open(LAST_ID_FILE, 'w') as f:
        f.write(str(msg_id))

def process_message(msg_id, msg):
    """پردازش یک پیام (برای استفاده در thread)"""
    print(f"\n📥 پردازش پیام {msg_id}")
    
    # استخراج متن
    text_elem = msg.select_one('.tgme_widget_message_text')
    text = text_elem.get_text() if text_elem else ""
    
    # فقط پیام‌هایی که تگ دارند
    if '@KhabarFuri' not in text:
        print("   ⏩ رد شد (تگ @KhabarFuri ندارد)")
        return None
    
    print(f"   📝 متن: {text[:80]}..." if len(text) > 80 else f"   📝 متن: {text}")
    
    # استخراج لینک رسانه
    media_url, media_type = extract_media_urls(msg)
    
    try:
        if media_url and media_type == 'photo':
            print(f"   📸 در حال دانلود عکس...")
            file_path = f"downloads/{msg_id}.jpg"
            if download_file(media_url, file_path):
                send_to_rubika("photo", file_path, text)
                try:
                    os.remove(file_path)
                except:
                    pass
            else:
                print(f"   ✗ خطا در دانلود عکس")
        
        elif media_url and media_type == 'video':
            print(f"   🎥 در حال دانلود ویدیو...")
            file_path = f"downloads/{msg_id}.mp4"
            if download_file(media_url, file_path):
                send_to_rubika("video", file_path, text)
                try:
                    os.remove(file_path)
                except:
                    pass
            else:
                print(f"   ✗ خطا در دانلود ویدیو")
        
        else:
            print(f"   📝 ارسال متن...")
            send_to_rubika("text", caption=text)
        
        return msg_id
        
    except Exception as e:
        print(f"   ✗ خطا: {e}")
        return None

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
        response = requests.get(url, timeout=30)
    except Exception as e:
        print(f"❌ خطا در اتصال: {e}")
        return
    
    if response.status_code != 200:
        print(f"❌ خطا: کد وضعیت {response.status_code}")
        return
    
    soup = BeautifulSoup(response.text, 'html.parser')
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
            except:
                pass
    
    # مرتب سازی از قدیمی به جدید
    new_messages.sort(key=lambda x: x[0])
    
    if not new_messages:
        print("📭 پیام جدیدی یافت نشد")
        return
    
    print(f"📨 {len(new_messages)} پیام جدید پیدا شد")
    print("-" * 55)
    
    # پردازش موازی با 2 worker (امن و بدون تداخل)
    processed_ids = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(process_message, msg_id, msg): msg_id 
                   for msg_id, msg in new_messages}
        
        for future in as_completed(futures):
            result = future.result()
            if result:
                processed_ids.append(result)
    
    # ذخیره آخرین ID پردازش شده
    if processed_ids:
        save_last_processed_id(max(processed_ids))
    
    print("\n" + "=" * 55)
    print("✅ اسکرپ با موفقیت کامل شد")
    print("=" * 55)

if __name__ == "__main__":
    scrape()
