import requests
import re
import os
import time
import json
import logging
from bs4 import BeautifulSoup
from io import BytesIO

# ========== تنظیمات ==========
RUBIKA_TOKEN = os.environ.get('RUBIKA_TOKEN')
RUBIKA_CHANNEL = "@NewsLine360"
SOURCE_CHANNEL = "KhabarFuri"
STATE_FILE = "state.json"
DOWNLOAD_DIR = "downloads"

# ========== بهینه‌سازی ==========
CHUNK_SIZE = 65536
DOWNLOAD_TIMEOUT = 15
UPLOAD_TIMEOUT = 15
COMPRESS_IMAGES = True
MAX_IMAGE_SIZE_KB = 500

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
    text = replace_source_links(text)
    text = remove_all_emojis(text)
    text = f"{text.strip()}\n\n{FOOTER.strip()}"
    return text

def load_state():
    """بارگذاری atomic state"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                if "last_id" not in state:
                    state["last_id"] = 0
                return state
        except:
            logging.warning("⚠️ فایل state خراب است، ریست می‌شود")
            return {"last_id": 0}
    return {"last_id": 0}

def save_state_atomic(state):
    """ذخیره atomic state با فایل موقت"""
    tmp_file = STATE_FILE + ".tmp"
    try:
        with open(tmp_file, 'w') as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_file, STATE_FILE)  # atomic operation
        return True
    except Exception as e:
        logging.error(f"❌ خطا در ذخیره state: {e}")
        return False

def download_file_fast(url, file_path):
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive'
    }
    
    try:
        response = requests.get(url, stream=True, headers=headers, timeout=DOWNLOAD_TIMEOUT)
        
        if response.status_code == 200:
            original_size = int(response.headers.get('content-length', 0))
            original_size_kb = original_size / 1024
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
            
            logging.info(f"   ✅ دانلود: {original_size_kb:.0f}KB")
            
            if file_path.endswith(('.jpg', '.jpeg', '.png')) and COMPRESS_IMAGES:
                compress_image_safe(file_path, original_size_kb)
            
            return True
        else:
            return False
            
    except Exception as e:
        logging.error(f"   ❌ خطا در دانلود: {e}")
        return False

def compress_image_safe(file_path, original_size_kb):
    """فشرده‌سازی ایمن با حفظ شفافیت PNG"""
    try:
        from PIL import Image
        
        img = Image.open(file_path)
        original_format = img.format
        
        # فقط عکس‌های بزرگ رو فشرده کن
        if original_size_kb < 100:
            return True
        
        # برای PNG شفاف، فشرده نکن (کیفیت رو حفظ کن)
        if original_format == 'PNG' and img.mode == 'RGBA':
            logging.info(f"   📦 PNG شفاف - فشرده‌سازی نمی‌شود")
            return True
        
        # تبدیل به RGB برای JPEG
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        # کاهش ابعاد اگر خیلی بزرگ بود
        max_dimension = 1280
        if max(img.size) > max_dimension:
            ratio = max_dimension / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # فشرده‌سازی پلکانی
        quality = 85
        output = BytesIO()
        
        while quality > 30:
            output.seek(0)
            output.truncate()
            img.save(output, format='JPEG', quality=quality, optimize=True)
            
            if output.tell() <= MAX_IMAGE_SIZE_KB * 1024:
                break
            
            quality -= 10
        
        # ذخیره فایل فشرده شده
        with open(file_path, 'wb') as f:
            f.write(output.getvalue())
        
        new_size_kb = len(output.getvalue()) / 1024
        saved_percent = (1 - new_size_kb / original_size_kb) * 100 if original_size_kb > 0 else 0
        
        if saved_percent > 10:
            logging.info(f"   📦 فشرده‌سازی: {original_size_kb:.0f}KB → {new_size_kb:.0f}KB (-{saved_percent:.0f}%)")
        
        return True
        
    except Exception as e:
        logging.warning(f"   ⚠️ خطا در فشرده‌سازی: {e}")
        return False

def extract_photo_url(photo_element):
    style = photo_element.get('style', '')
    match = re.search(r"url\('([^']+)'\)", style)
    if match:
        url = match.group(1)
        url = re.sub(r'_[sb]\d+\.', '.', url)
        return url
    return None

def extract_album_photos(message):
    photos = []
    
    grouped_wrap = message.select_one('.tgme_widget_message_grouped_wrap')
    if grouped_wrap:
        photo_wraps = grouped_wrap.select('a.tgme_widget_message_photo_wrap')
        for photo in photo_wraps:
            url = extract_photo_url(photo)
            if url:
                photos.append(url)
        return photos
    
    photo_wrap = message.select_one('a.tgme_widget_message_photo_wrap')
    if photo_wrap:
        url = extract_photo_url(photo_wrap)
        if url:
            photos.append(url)
    
    return photos

def send_to_rubika(content_type, file_path=None, caption=""):
    """ارسال به روبیکا با بازگشت وضعیت موفقیت"""
    if not RUBIKA_TOKEN:
        return False
    
    cleaned_caption = clean_and_format(caption)
    if len(cleaned_caption) > 4000:
        cleaned_caption = cleaned_caption[:3997] + "..."
    
    rubika_url = f"https://botapi.rubika.ir/v3/{RUBIKA_TOKEN}/"
    headers = {"Content-Type": "application/json"}
    
    try:
        if content_type == "text":
            payload = {"chat_id": RUBIKA_CHANNEL, "text": cleaned_caption}
            start_time = time.time()
            response = requests.post(
                rubika_url + "sendMessage",
                data=json.dumps(payload),
                headers=headers,
                timeout=10
            )
            elapsed = time.time() - start_time
            
            if response.status_code == 200 and response.json().get("status") == "OK":
                logging.info(f"   ✓ متن ارسال شد ({elapsed:.1f}s)")
                return True
            else:
                logging.error(f"   ✗ خطا در ارسال متن")
                return False
        
        elif content_type in ["photo", "video"]:
            file_type = "Image" if content_type == "photo" else "Video"
            
            start_time = time.time()
            resp_upload = requests.post(
                rubika_url + "requestSendFile",
                data=json.dumps({"type": file_type}),
                headers=headers,
                timeout=8
            )
            
            if resp_upload.status_code != 200:
                return False
                
            upload_data = resp_upload.json()
            if upload_data.get("status") != "OK":
                return False
                
            upload_url = upload_data["data"]["upload_url"]
            
            with open(file_path, 'rb') as f:
                resp_file = requests.post(
                    upload_url, 
                    files={"file": f}, 
                    timeout=UPLOAD_TIMEOUT
                )
                
            file_data = resp_file.json()
            if file_data.get("status") != "OK":
                return False
                
            file_id = file_data["data"]["file_id"]
            
            payload = {
                "chat_id": RUBIKA_CHANNEL,
                "file_id": file_id,
                "text": cleaned_caption if content_type == "photo" else cleaned_caption
            }
            
            response = requests.post(
                rubika_url + "sendFile",
                data=json.dumps(payload),
                headers=headers,
                timeout=8
            )
            
            elapsed = time.time() - start_time
            file_size_kb = os.path.getsize(file_path) / 1024
            
            if response.status_code == 200 and response.json().get("status") == "OK":
                logging.info(f"   ✓ {content_type} ارسال شد ({file_size_kb:.0f}KB, {elapsed:.1f}s)")
                return True
            else:
                logging.error(f"   ✗ خطا در ارسال {content_type}")
                return False
            
    except Exception as e:
        logging.error(f"   ✗ خطا: {e}")
        return False

def send_album_sequential(photos, caption, msg_id):
    """ارسال پشت سر هم عکس‌های آلبوم با چک موفقیت"""
    downloaded_files = []
    
    # مرحله 1: دانلود همه عکس‌ها
    for idx, photo_url in enumerate(photos):
        file_path = f"{DOWNLOAD_DIR}/album_{msg_id}_{idx}.jpg"
        if download_file_fast(photo_url, file_path):
            downloaded_files.append((file_path, idx))
        else:
            logging.warning(f"   ⚠️ خطا در دانلود عکس {idx+1}")
    
    if not downloaded_files:
        return False
    
    # مرحله 2: ارسال پشت سر هم
    success_count = 0
    for idx, (file_path, _) in enumerate(downloaded_files):
        if idx == len(downloaded_files) - 1:
            success = send_to_rubika("photo", file_path, caption)
        else:
            success = send_to_rubika("photo", file_path, "")
        
        if success:
            success_count += 1
        
        if os.path.exists(file_path):
            os.remove(file_path)
        
        time.sleep(0.2)  # کاهش تاخیر بین عکس‌ها
    
    return success_count == len(downloaded_files)

def scrape():
    """نسخه Production-Grade با atomic state و check success"""
    print("=" * 55)
    print("       اسکرپ کانال خبری - NewsLine360 (نسخه نهایی)")
    print("=" * 55)
    
    if not RUBIKA_TOKEN:
        logging.error("RUBIKA_TOKEN تنظیم نشده")
        return
    
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    if COMPRESS_IMAGES:
        try:
            from PIL import Image
            logging.info("✅ فشرده‌سازی عکس فعال است")
        except ImportError:
            logging.warning("⚠️ PIL نصب نیست - نصب کنید: pip install Pillow")
    
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
    
    # پیدا کردن آخرین و اولین ID در صفحه
    latest_id_in_page = 0
    earliest_id_in_page = float('inf')
    id_map = {}
    
    for msg in messages:
        data_post = msg.get('data-post', '')
        if data_post:
            try:
                msg_id = int(data_post.split('/')[-1])
                latest_id_in_page = max(latest_id_in_page, msg_id)
                earliest_id_in_page = min(earliest_id_in_page, msg_id)
                id_map[msg_id] = msg
            except:
                pass
    
    state = load_state()
    last_id = state["last_id"]
    
    logging.info(f"📌 آخرین ID ذخیره شده: {last_id}")
    logging.info(f"📌 محدوده ID در صفحه: {earliest_id_in_page} تا {latest_id_in_page}")
    
    # ========== مدیریت GAP (فقط هشدار، بدون action) ==========
    if last_id > 0 and earliest_id_in_page > last_id + 1:
        gap_size = earliest_id_in_page - last_id - 1
        gap_start = last_id + 1
        gap_end = earliest_id_in_page - 1
        
        logging.warning("=" * 55)
        logging.warning(f"⚠️ GAP شناسایی شد!")
        logging.warning(f"⚠️ پیام‌های {gap_start} تا {gap_end} (تعداد {gap_size} پیام) از دست رفته")
        logging.warning(f"⚠️ این پیام‌ها در وب تلگرام موجود نیستند")
        logging.warning(f"✅ اما پیام‌های جدید {earliest_id_in_page} تا {latest_id_in_page} ارسال می‌شوند")
        logging.warning("=" * 55)
    
    # ========== پردازش پیام‌های جدید ==========
    new_messages = []
    for msg_id, msg in id_map.items():
        if msg_id > last_id:
            new_messages.append((msg_id, msg))
    
    if not new_messages:
        logging.info("📭 پیام جدیدی یافت نشد")
        
        # اگر پیام جدیدی نبود، اما gap داشتیم، last_id رو آپدیت کن
        if last_id > 0 and latest_id_in_page > last_id:
            logging.info(f"🔄 آپدیت last_id از {last_id} به {latest_id_in_page}")
            state["last_id"] = latest_id_in_page
            save_state_atomic(state)
        return
    
    new_messages.sort(key=lambda x: x[0])
    logging.info(f"📨 {len(new_messages)} پیام جدید برای پردازش")
    
    # پردازش پیام‌ها
    for msg_id, msg in new_messages:
        text_elem = msg.select_one('.tgme_widget_message_text')
        text = text_elem.get_text() if text_elem else ""
        
        # فیلتر تگ با روش ایمن‌تر
        if not text or SOURCE_CHANNEL.lower() not in text.lower():
            logging.info(f"⏩ پیام {msg_id} رد شد (بدون تگ)")
            continue
        
        logging.info(f"\n📥 پردازش پیام {msg_id}")
        start_time = time.time()
        
        # استخراج عکس‌ها
        photos = extract_album_photos(msg)
        
        if photos:
            logging.info(f"   📸 {len(photos)} عکس (ارسال پشت سر هم)")
            success = send_album_sequential(photos, text, msg_id)
            
            if success:
                # فقط بعد از موفقیت کامل، state رو آپدیت کن
                if msg_id > state["last_id"]:
                    state["last_id"] = msg_id
                    save_state_atomic(state)
                    logging.info(f"   💾 state ذخیره شد - last_id: {msg_id}")
            else:
                logging.warning(f"   ⚠️ برخی از عکس‌ها ارسال نشدند - state آپدیت نشد")
            
            elapsed = time.time() - start_time
            logging.info(f"   ⏱️ زمان کل: {elapsed:.1f}s")
            continue
        
        # ویدیو
        video_elem = msg.select_one('video, source')
        if video_elem and video_elem.get('src'):
            video_url = video_elem.get('src')
            file_path = f"{DOWNLOAD_DIR}/video_{msg_id}.mp4"
            if download_file_fast(video_url, file_path):
                success = send_to_rubika("video", file_path, text)
                os.remove(file_path)
                
                if success and msg_id > state["last_id"]:
                    state["last_id"] = msg_id
                    save_state_atomic(state)
                    logging.info(f"   💾 state ذخیره شد - last_id: {msg_id}")
            else:
                logging.warning(f"   ⚠️ خطا در دانلود ویدیو")
            
            elapsed = time.time() - start_time
            logging.info(f"   ⏱️ زمان کل: {elapsed:.1f}s")
            continue
        
        # فقط متن
        success = send_to_rubika("text", caption=text)
        
        if success and msg_id > state["last_id"]:
            state["last_id"] = msg_id
            save_state_atomic(state)
            logging.info(f"   💾 state ذخیره شد - last_id: {msg_id}")
        
        elapsed = time.time() - start_time
        logging.info(f"   ⏱️ زمان کل: {elapsed:.1f}s")
        
        time.sleep(0.2)
    
    # بعد از اتمام، آخرین ID را آپدیت کن
    if latest_id_in_page > state["last_id"]:
        state["last_id"] = latest_id_in_page
        save_state_atomic(state)
        logging.info(f"🔄 آپدیت نهایی last_id به {latest_id_in_page}")
    
    print("=" * 55)
    logging.info(f"✅ اسکرپ کامل شد - آخرین ID: {state['last_id']}")
    print("=" * 55)

if __name__ == "__main__":
    scrape()
