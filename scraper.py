import requests
import re
import os
import time
import json
import logging
from bs4 import BeautifulSoup
from pathlib import Path

# ========== تنظیمات ==========
RUBIKA_TOKEN = os.environ.get('RUBIKA_TOKEN')
RUBIKA_CHANNEL = "@NewsLine360"
SOURCE_CHANNEL = "KhabarFuri"
STATE_FILE = "state.json"  # فایل جدید برای ذخیره state کامل
DOWNLOAD_DIR = "downloads"

# ========== فوتر ==========
FOOTER = """
────────────────────
@NewsLine360
────────────────────
"""

# ========== تنظیمات لاگینگ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def remove_all_emojis(text):
    """حذف همه ایموجی‌ها"""
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
    """جایگزینی لینک‌های کانال مبدأ"""
    if not text:
        return ""
    
    text = re.sub(r'@KhabarFuri\b', RUBIKA_CHANNEL, text)
    text = re.sub(r'https?://t\.me/KhabarFuri[^\s]*', 'https://t.me/NewsLine360', text)
    text = re.sub(r'https?://t\.me/s/KhabarFuri[^\s]*', 'https://t.me/NewsLine360', text)
    
    return text

def clean_and_format(text):
    """تمیزکاری کامل متن قبل از ارسال"""
    if not text or not text.strip():
        return FOOTER.strip()
    
    text = re.sub(r'@KhabarFuri\s*', '', text)
    text = remove_all_emojis(text)
    text = replace_source_links(text)
    text = f"{text.strip()}\n\n{FOOTER.strip()}"
    
    return text

def load_state():
    """بارگذاری state از فایل JSON"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"last_id": 0, "processed_groups": []}
    return {"last_id": 0, "processed_groups": []}

def save_state(state):
    """ذخیره state در فایل JSON"""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def download_file(url, file_path, max_retries=3):
    """دانلود فایل با قابلیت تکرار مجدد"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, stream=True, headers=headers, timeout=30)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
            else:
                logging.warning(f"تلاش {attempt+1}: کد وضعیت {response.status_code}")
        except Exception as e:
            logging.warning(f"تلاش {attempt+1}: خطا - {e}")
            time.sleep(2)
    
    return False

def extract_album_photos(message):
    """استخراج تمام عکس‌های آلبوم"""
    photos = []
    
    # چک کردن آلبوم گروهی
    grouped_wrap = message.select_one('.tgme_widget_message_grouped_wrap')
    if grouped_wrap:
        # آلبوم با چند عکس
        photo_wraps = grouped_wrap.select('a.tgme_widget_message_photo_wrap')
        for photo in photo_wraps:
            style = photo.get('style', '')
            match = re.search(r"url\('([^']+)'\)", style)
            if match:
                url = match.group(1)
                url = re.sub(r'_[sb]\d+\.jpg', '.jpg', url)
                photos.append(url)
    else:
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

def extract_video(message):
    """استخراج ویدیو از پیام"""
    video_elem = message.select_one('video, source')
    if video_elem:
        video_url = video_elem.get('src')
        if video_url:
            return video_url
    return None

def send_album_to_rubika(photos, caption):
    """ارسال آلبوم عکس به روبیکا (به صورت جداگانه)"""
    cleaned_caption = clean_and_format(caption)
    
    for idx, photo_url in enumerate(photos):
        file_path = f"{DOWNLOAD_DIR}/album_{int(time.time())}_{idx}.jpg"
        
        if download_file(photo_url, file_path):
            if idx == len(photos) - 1:
                # آخرین عکس با متن کامل
                send_to_rubika("photo", file_path, caption)
            else:
                # عکس‌های قبلی بدون متن
                send_to_rubika("photo", file_path, "")
            
            os.remove(file_path)
            time.sleep(0.5)  # تاخیر بین عکس‌های آلبوم

def send_to_rubika(content_type, file_path=None, caption=""):
    """ارسال به روبیکا با مدیریت خطای بهتر"""
    if not RUBIKA_TOKEN:
        logging.error("RUBIKA_TOKEN تنظیم نشده است")
        return None
    
    cleaned_caption = clean_and_format(caption)
    
    # محدودیت طول متن
    if len(cleaned_caption) > 4000:
        cleaned_caption = cleaned_caption[:3997] + "..."
    
    rubika_url = f"https://botapi.rubika.ir/v3/{RUBIKA_TOKEN}/"
    headers = {"Content-Type": "application/json"}
    
    try:
        # فقط متن
        if content_type == "text":
            payload = {"chat_id": RUBIKA_CHANNEL, "text": cleaned_caption}
            response = requests.post(
                rubika_url + "sendMessage",
                data=json.dumps(payload),
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "OK":
                    logging.info("   ✓ متن ارسال شد")
                else:
                    logging.error(f"   ✗ خطا: {result}")
            return response
        
        # عکس یا ویدیو
        elif content_type in ["photo", "video"]:
            file_type = "Image" if content_type == "photo" else "Video"
            
            # دریافت آدرس آپلود
            resp_upload = requests.post(
                rubika_url + "requestSendFile",
                data=json.dumps({"type": file_type}),
                headers=headers,
                timeout=30
            )
            
            if resp_upload.status_code != 200:
                logging.error("   ✗ خطا در دریافت آدرس آپلود")
                return None
                
            upload_data = resp_upload.json()
            if upload_data.get("status") != "OK":
                logging.error(f"   ✗ خطا: {upload_data}")
                return None
                
            upload_url = upload_data["data"]["upload_url"]
            
            # آپلود فایل
            with open(file_path, 'rb') as f:
                resp_file = requests.post(upload_url, files={"file": f}, timeout=30)
                
            file_data = resp_file.json()
            if file_data.get("status") != "OK":
                logging.error("   ✗ خطا در آپلود فایل")
                return None
                
            file_id = file_data["data"]["file_id"]
            
            # ارسال به کانال
            payload = {
                "chat_id": RUBIKA_CHANNEL,
                "file_id": file_id,
                "text": cleaned_caption if content_type == "photo" else ""
            }
            
            if content_type == "video":
                payload["text"] = cleaned_caption
            
            response = requests.post(
                rubika_url + "sendFile",
                data=json.dumps(payload),
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "OK":
                    logging.info(f"   ✓ {content_type} ارسال شد")
                else:
                    logging.error(f"   ✗ خطا: {result}")
            return response
            
    except Exception as e:
        logging.error(f"   ✗ خطا در ارسال: {e}")
        return None

def process_messages_grouped(messages):
    """پردازش پیام‌ها با در نظر گرفتن آلبوم‌ها"""
    state = load_state()
    last_id = state["last_id"]
    processed_groups = set(state.get("processed_groups", []))
    
    # گروه‌بندی پیام‌ها بر اساس grouped_id
    groups = {}
    single_messages = []
    
    for msg in messages:
        data_post = msg.get('data-post', '')
        if not data_post:
            continue
            
        try:
            msg_id = int(data_post.split('/')[-1])
            if msg_id <= last_id:
                continue
        except:
            continue
        
        # بررسی grouped_id
        grouped_id = msg.get('data-grouped-id', '')
        if grouped_id:
            if grouped_id not in groups:
                groups[grouped_id] = []
            groups[grouped_id].append(msg)
        else:
            single_messages.append(msg)
    
    # حذف گروه‌های قبلاً پردازش شده
    for group_id in list(groups.keys()):
        if group_id in processed_groups:
            del groups[group_id]
    
    # پردازش گروه‌ها (آلبوم‌ها)
    for group_id, group_msgs in groups.items():
        logging.info(f"\n📸 پردازش آلبوم {group_id} با {len(group_msgs)} عکس")
        
        # مرتب‌سازی بر اساس ID
        group_msgs.sort(key=lambda x: int(x.get('data-post', '').split('/')[-1]))
        
        # استخراج همه عکس‌ها
        all_photos = []
        caption = ""
        
        for msg in group_msgs:
            photos = extract_album_photos(msg)
            all_photos.extend(photos)
            
            # متن از آخرین پیام آلبوم
            text_elem = msg.select_one('.tgme_widget_message_text')
            if text_elem and '@KhabarFuri' in text_elem.get_text():
                caption = text_elem.get_text()
        
        if all_photos and '@KhabarFuri' in caption:
            logging.info(f"   📸 ارسال آلبوم با {len(all_photos)} عکس")
            send_album_to_rubika(all_photos, caption)
            
            # به‌روزرسانی state
            last_msg_id = int(group_msgs[-1].get('data-post', '').split('/')[-1])
            if last_msg_id > last_id:
                last_id = last_msg_id
            processed_groups.add(group_id)
    
    # پردازش پیام‌های تکی
    for msg in single_messages:
        data_post = msg.get('data-post', '')
        msg_id = int(data_post.split('/')[-1])
        
        if msg_id <= last_id:
            continue
        
        # استخراج متن
        text_elem = msg.select_one('.tgme_widget_message_text')
        text = text_elem.get_text() if text_elem else ""
        
        # فقط پیام‌هایی که تگ دارند
        if '@KhabarFuri' not in text:
            logging.info(f"   ⏩ پیام {msg_id} رد شد (بدون تگ)")
            continue
        
        logging.info(f"\n📥 پردازش پیام {msg_id}")
        logging.info(f"   📝 متن: {text[:80]}..." if len(text) > 80 else f"   📝 متن: {text}")
        
        # بررسی ویدیو
        video_url = extract_video(msg)
        if video_url:
            logging.info(f"   🎥 دانلود ویدیو...")
            file_path = f"{DOWNLOAD_DIR}/video_{msg_id}.mp4"
            if download_file(video_url, file_path):
                send_to_rubika("video", file_path, text)
                os.remove(file_path)
            continue
        
        # بررسی عکس (تک عکس)
        photos = extract_album_photos(msg)
        if photos:
            logging.info(f"   📸 ارسال عکس...")
            send_album_to_rubika(photos, text)
            continue
        
        # فقط متن
        logging.info(f"   📝 ارسال متن...")
        send_to_rubika("text", caption=text)
        
        # به‌روزرسانی last_id
        if msg_id > last_id:
            last_id = msg_id
        
        time.sleep(1)
    
    # ذخیره state نهایی
    save_state({
        "last_id": last_id,
        "processed_groups": list(processed_groups)
    })
    
    return last_id

def scrape():
    """تابع اصلی اسکرپ کانال"""
    print("=" * 55)
    print("       اسکرپ کانال خبری - NewsLine360")
    print("=" * 55)
    
    if not RUBIKA_TOKEN:
        logging.error("RUBIKA_TOKEN در محیط تعریف نشده است")
        return
    
    # ساخت پوشه موقت
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    # دریافت صفحه کانال
    url = f"https://t.me/s/{SOURCE_CHANNEL}"
    logging.info(f"\n🔍 در حال بررسی کانال: t.me/{SOURCE_CHANNEL}")
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        logging.error(f"❌ خطا در اتصال: {e}")
        return
    
    soup = BeautifulSoup(response.text, 'html.parser')
    messages = soup.select('.tgme_widget_message')
    
    if not messages:
        logging.warning("⚠️ هیچ پیامی پیدا نشد")
        return
    
    state = load_state()
    logging.info(f"📌 آخرین ID پردازش شده: {state['last_id']}")
    logging.info(f"📌 گروه‌های پردازش شده: {len(state.get('processed_groups', []))}")
    
    # پردازش پیام‌ها
    new_last_id = process_messages_grouped(messages)
    
    if new_last_id == state['last_id']:
        logging.info("📭 پیام جدیدی یافت نشد")
    else:
        logging.info(f"✅ اسکرپ با موفقیت کامل شد - آخرین ID: {new_last_id}")
    
    print("=" * 55)

if __name__ == "__main__":
    scrape()
