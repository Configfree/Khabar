import requests
import re
import os
import time
import json
import logging
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

# ========== تنظیمات ==========
RUBIKA_TOKEN = os.environ.get('RUBIKA_TOKEN')
RUBIKA_CHANNEL = "@NewsLine360"
SOURCE_CHANNEL = "KhabarFuri"
STATE_FILE = "state.json"
DOWNLOAD_DIR = "downloads"

# ========== بهینه‌سازی سرعت ==========
MAX_WORKERS = 3  # دانلود همزمان
CHUNK_SIZE = 32768  # 32KB برای سرعت بیشتر
DOWNLOAD_TIMEOUT = 20

FOOTER = """
────────────────────
@NewsLine360
────────────────────
"""

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def remove_all_emojis(text):
    if not text:
        return ""
    emoji_pattern = re.compile(
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
    text = emoji_pattern.sub(r'', text)
    text = re.sub(r'[ ]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def replace_source_links(text):
    if not text:
        return ""
    text = re.sub(r'@KhabarFuri\b', RUBIKA_CHANNEL, text)
    text = re.sub(r'https?://t\.me/KhabarFuri[^\s]*', 'https://t.me/NewsLine360', text)
    text = re.sub(r'https?://t\.me/s/KhabarFuri[^\s]*', 'https://t.me/NewsLine360', text)
    return text

def clean_and_format(text):
    if not text or not text.strip():
        return FOOTER.strip()
    text = re.sub(r'@KhabarFuri\s*', '', text)
    text = remove_all_emojis(text)
    text = replace_source_links(text)
    text = f"{text.strip()}\n\n{FOOTER.strip()}"
    return text

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"last_id": 0, "processed_groups": []}
    return {"last_id": 0, "processed_groups": []}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def download_file_fast(url, file_path):
    """دانلود سریع با بهینه‌سازی برای GitHub Actions"""
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive'
    }
    
    try:
        # افزایش timeout و استفاده از stream
        response = requests.get(url, stream=True, headers=headers, timeout=DOWNLOAD_TIMEOUT)
        
        if response.status_code == 200:
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # نمایش پیشرفت دانلود
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            if percent % 25 < 1:  # هر 25 درصد یکبار لاگ بده
                                logging.info(f"   📥 دانلود: {percent:.0f}%")
            
            logging.info(f"   ✅ دانلود شد: {os.path.getsize(file_path)/1024:.1f}KB")
            return True
        else:
            logging.warning(f"   ⚠️ کد خطا: {response.status_code}")
            return False
            
    except Exception as e:
        logging.error(f"   ❌ خطا: {e}")
        return False

def extract_album_group(messages):
    """تشخیص درست آلبوم‌ها با استفاده از ساختار HTML تلگرام"""
    groups = {}
    
    for msg in messages:
        # بررسی پیام‌های گروهی (آلبوم)
        grouped_wrap = msg.select_one('.tgme_widget_message_grouped_wrap')
        if grouped_wrap:
            # پیدا کردن والد مشترک برای گروه
            parent = msg.find_previous_sibling(class_='tgme_widget_message_grouped_wrap')
            if parent:
                # از data-post اولین و آخرین پیام گروه استفاده کن
                first_msg = parent.find_next(class_='tgme_widget_message')
                if first_msg:
                    group_key = first_msg.get('data-post', '').split('/')[-1]
                    if group_key not in groups:
                        groups[group_key] = []
                    groups[group_key].append(msg)
    
    return groups

def extract_album_photos(message):
    """استخراج تمام عکس‌های آلبوم"""
    photos = []
    
    # بررسی آلبوم گروهی
    grouped_wrap = message.select_one('.tgme_widget_message_grouped_wrap')
    if grouped_wrap:
        photo_wraps = grouped_wrap.select('a.tgme_widget_message_photo_wrap')
        for photo in photo_wraps:
            style = photo.get('style', '')
            match = re.search(r"url\('([^']+)'\)", style)
            if match:
                url = match.group(1)
                url = re.sub(r'_[sb]\d+\.jpg', '.jpg', url)
                photos.append(url)
        return photos
    
    # تک عکس
    photo_wrap = message.select_one('a.tgme_widget_message_photo_wrap')
    if photo_wrap:
        style = photo_wrap.get('style', '')
        match = re.search(r"url\('([^']+)'\)", style)
        if match:
            url = match.group(1)
            url = re.sub(r'_[sb]\d+\.jpg', '.jpg', url)
            photos.append(url)
    
    return photos

def send_to_rubika_fast(content_type, file_path=None, caption=""):
    """ارسال سریع به روبیکا"""
    if not RUBIKA_TOKEN:
        logging.error("RUBIKA_TOKEN تنظیم نشده")
        return None
    
    cleaned_caption = clean_and_format(caption)
    
    if len(cleaned_caption) > 4000:
        cleaned_caption = cleaned_caption[:3997] + "..."
    
    rubika_url = f"https://botapi.rubika.ir/v3/{RUBIKA_TOKEN}/"
    headers = {"Content-Type": "application/json"}
    
    try:
        if content_type == "text":
            payload = {"chat_id": RUBIKA_CHANNEL, "text": cleaned_caption}
            response = requests.post(
                rubika_url + "sendMessage",
                data=json.dumps(payload),
                headers=headers,
                timeout=15
            )
            
            if response.status_code == 200 and response.json().get("status") == "OK":
                logging.info("   ✓ متن ارسال شد")
            return response
        
        elif content_type in ["photo", "video"]:
            file_type = "Image" if content_type == "photo" else "Video"
            
            # دریافت آدرس آپلود
            resp_upload = requests.post(
                rubika_url + "requestSendFile",
                data=json.dumps({"type": file_type}),
                headers=headers,
                timeout=15
            )
            
            if resp_upload.status_code != 200:
                return None
                
            upload_data = resp_upload.json()
            if upload_data.get("status") != "OK":
                return None
                
            upload_url = upload_data["data"]["upload_url"]
            
            # آپلود فایل با chunk مناسب
            with open(file_path, 'rb') as f:
                resp_file = requests.post(upload_url, files={"file": f}, timeout=30)
                
            file_data = resp_file.json()
            if file_data.get("status") != "OK":
                return None
                
            file_id = file_data["data"]["file_id"]
            
            # ارسال به کانال
            payload = {
                "chat_id": RUBIKA_CHANNEL,
                "file_id": file_id,
                "text": cleaned_caption if content_type == "photo" else cleaned_caption
            }
            
            response = requests.post(
                rubika_url + "sendFile",
                data=json.dumps(payload),
                headers=headers,
                timeout=15
            )
            
            if response.status_code == 200 and response.json().get("status") == "OK":
                logging.info(f"   ✓ {content_type} ارسال شد")
            return response
            
    except Exception as e:
        logging.error(f"   ✗ خطا: {e}")
        return None

def scrape():
    """تابع اصلی اسکرپ"""
    print("=" * 55)
    print("       اسکرپ کانال خبری - NewsLine360")
    print("=" * 55)
    
    if not RUBIKA_TOKEN:
        logging.error("RUBIKA_TOKEN تنظیم نشده")
        return
    
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    url = f"https://t.me/s/{SOURCE_CHANNEL}"
    logging.info(f"\n🔍 در حال بررسی کانال: t.me/{SOURCE_CHANNEL}")
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        logging.error(f"❌ خطا: {e}")
        return
    
    soup = BeautifulSoup(response.text, 'html.parser')
    messages = soup.select('.tgme_widget_message')
    
    if not messages:
        logging.warning("⚠️ هیچ پیامی پیدا نشد")
        return
    
    state = load_state()
    last_id = state["last_id"]
    logging.info(f"📌 آخرین ID: {last_id}")
    
    # پردازش از جدید به قدیم
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
    
    if not new_messages:
        logging.info("📭 پیام جدیدی یافت نشد")
        return
    
    # مرتب‌سازی از قدیم به جدید
    new_messages.sort(key=lambda x: x[0])
    logging.info(f"📨 {len(new_messages)} پیام جدید")
    
    # پردازش پیام‌ها
    max_id = last_id
    
    for msg_id, msg in new_messages:
        # استخراج متن
        text_elem = msg.select_one('.tgme_widget_message_text')
        text = text_elem.get_text() if text_elem else ""
        
        # فقط پیام‌هایی که تگ دارند
        if '@KhabarFuri' not in text:
            continue
        
        logging.info(f"\n📥 پیام {msg_id}")
        
        # استخراج عکس‌ها (آلبوم یا تک عکس)
        photos = extract_album_photos(msg)
        
        if photos:
            logging.info(f"   📸 {len(photos)} عکس")
            # ارسال عکس اول بدون متن، بقیه با متن
            for idx, photo_url in enumerate(photos):
                file_path = f"{DOWNLOAD_DIR}/photo_{msg_id}_{idx}.jpg"
                if download_file_fast(photo_url, file_path):
                    if idx == len(photos) - 1:
                        send_to_rubika_fast("photo", file_path, text)
                    else:
                        send_to_rubika_fast("photo", file_path, "")
                    os.remove(file_path)
                    time.sleep(0.3)
            max_id = max(max_id, msg_id)
            continue
        
        # ویدیو
        video_elem = msg.select_one('video, source')
        if video_elem and video_elem.get('src'):
            video_url = video_elem.get('src')
            logging.info(f"   🎥 دانلود ویدیو...")
            file_path = f"{DOWNLOAD_DIR}/video_{msg_id}.mp4"
            if download_file_fast(video_url, file_path):
                send_to_rubika_fast("video", file_path, text)
                os.remove(file_path)
            max_id = max(max_id, msg_id)
            continue
        
        # فقط متن
        logging.info(f"   📝 ارسال متن")
        send_to_rubika_fast("text", caption=text)
        max_id = max(max_id, msg_id)
        
        time.sleep(0.5)
    
    # ذخیره آخرین ID
    if max_id > last_id:
        save_state({"last_id": max_id, "processed_groups": []})
        logging.info(f"✅ ذخیره شد - آخرین ID: {max_id}")
    
    print("=" * 55)

if __name__ == "__main__":
    scrape()
