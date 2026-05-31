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

# ========== بهینه‌سازی سرعت ==========
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
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                if "last_id" not in state:
                    state["last_id"] = 0
                return state
        except (json.JSONDecodeError, ValueError):
            logging.warning("⚠️ فایل state خراب است، ریست می‌شود")
            return {"last_id": 0}
    return {"last_id": 0}

def save_state_atomic(state):
    """ذخیره اتمیک state - از corruption جلوگیری می‌کند"""
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
                compress_image_fast(file_path, original_size_kb)
            
            return True
        else:
            return False
            
    except Exception as e:
        logging.error(f"   ❌ خطا در دانلود: {e}")
        return False

def compress_image_fast(file_path, original_size_kb):
    """فشرده‌سازی سریع عکس"""
    try:
        from PIL import Image
        
        if original_size_kb < 100:
            return True
        
        img = Image.open(file_path)
        
        if img.mode in ('RGBA', 'P'):
            if img.format == 'PNG' and img.mode == 'RGBA':
                max_dimension = 1280
                if max(img.size) > max_dimension:
                    ratio = max_dimension / max(img.size)
                    new_size = tuple(int(dim * ratio) for dim in img.size)
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                    img.save(file_path, format='PNG', optimize=True)
                    new_size_kb = os.path.getsize(file_path) / 1024
                    logging.info(f"   📦 بهینه‌سازی PNG: {original_size_kb:.0f}KB → {new_size_kb:.0f}KB")
                return True
            else:
                img = img.convert('RGB')
        
        max_dimension = 1280
        if max(img.size) > max_dimension:
            ratio = max_dimension / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        quality = 75
        img.save(file_path, format='JPEG', quality=quality, optimize=True)
        
        new_size_kb = os.path.getsize(file_path) / 1024
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
    """ارسال به روبیکا با مدیریت خطای JSON"""
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
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    if result.get("status") == "OK":
                        logging.info(f"   ✓ متن ارسال شد ({elapsed:.1f}s)")
                        return True
                except:
                    pass
            
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
                
            try:
                upload_data = resp_upload.json()
            except:
                return False
                
            if upload_data.get("status") != "OK":
                return False
                
            upload_url = upload_data["data"]["upload_url"]
            
            with open(file_path, 'rb') as f:
                resp_file = requests.post(
                    upload_url, 
                    files={"file": f}, 
                    timeout=UPLOAD_TIMEOUT
                )
                
            try:
                file_data = resp_file.json()
            except:
                return False
                
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
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    if result.get("status") == "OK":
                        logging.info(f"   ✓ {content_type} ارسال شد ({file_size_kb:.0f}KB, {elapsed:.1f}s)")
                        return True
                except:
                    pass
            
            logging.error(f"   ✗ خطا در ارسال {content_type}")
            return False
            
    except Exception as e:
        logging.error(f"   ✗ خطا: {e}")
        return False

def send_album_sequential(photos, caption, msg_id):
    """ارسال پشت سر هم عکس‌های آلبوم"""
    downloaded_files = []
    
    for idx, photo_url in enumerate(photos):
        file_path = f"{DOWNLOAD_DIR}/album_{msg_id}_{idx}.jpg"
        if download_file_fast(photo_url, file_path):
            downloaded_files.append(file_path)
        else:
            logging.warning(f"   ⚠️ خطا در دانلود عکس {idx+1}")
    
    if not downloaded_files:
        return False
    
    success = True
    for idx, file_path in enumerate(downloaded_files):
        if idx == len(downloaded_files) - 1:
            if not send_to_rubika("photo", file_path, caption):
                success = False
        else:
            if not send_to_rubika("photo", file_path, ""):
                success = False
        
        if os.path.exists(file_path):
            os.remove(file_path)
    
    return success

def scrape():
    """نسخه نهایی با atomic state و حذف sleep اضافی"""
    print("=" * 55)
    print("       اسکرپ کانال خبری - NewsLine360")
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
    
    msg_dict = {}
    for msg in messages:
        data_post = msg.get('data-post', '')
        if data_post:
            try:
                msg_id = int(data_post.split('/')[-1])
                msg_dict[msg_id] = msg
            except:
                pass
    
    if not msg_dict:
        logging.warning("⚠️ هیچ ID معتبری پیدا نشد")
        return
    
    latest_id_in_page = max(msg_dict.keys())
    earliest_id_in_page = min(msg_dict.keys())
    
    state = load_state()
    last_id = state.get("last_id", 0)
    
    logging.info(f"📌 آخرین ID ذخیره شده: {last_id}")
    logging.info(f"📌 محدوده ID در صفحه: {earliest_id_in_page} تا {latest_id_in_page}")
    
    # پیدا کردن پیام‌های جدید
    new_msg_ids = [msg_id for msg_id in msg_dict.keys() if msg_id > last_id]
    
    if not new_msg_ids:
        logging.info("📭 پیام جدیدی یافت نشد")
        if latest_id_in_page > last_id:
            state["last_id"] = latest_id_in_page
            save_state_atomic(state)
            logging.info(f"🔄 آپدیت last_id به {latest_id_in_page}")
        return
    
    new_msg_ids.sort()
    logging.info(f"📨 {len(new_msg_ids)} پیام جدید برای پردازش")
    
    # پردازش - بدون sleep اضافی
    max_processed_id = last_id
    
    for msg_id in new_msg_ids:
        msg = msg_dict[msg_id]
        
        # آپدیت ID بدون شرط (نکته 2)
        if msg_id > max_processed_id:
            max_processed_id = msg_id
        
        # استخراج متن
        text_elem = msg.select_one('.tgme_widget_message_text')
        text = text_elem.get_text() if text_elem else ""
        
        # چک کردن تگ
        if '@KhabarFuri' not in text:
            logging.info(f"⏩ پیام {msg_id} رد شد (بدون تگ)")
            continue
        
        logging.info(f"\n📥 پردازش پیام {msg_id}")
        start_time = time.time()
        
        photos = extract_album_photos(msg)
        
        if photos:
            logging.info(f"   📸 {len(photos)} عکس")
            if send_album_sequential(photos, text, msg_id):
                state["last_id"] = max_processed_id
                save_state_atomic(state)
                logging.info(f"   💾 state ذخیره شد - last_id: {max_processed_id}")
            continue
        
        video_elem = msg.select_one('video, source')
        if video_elem and video_elem.get('src'):
            video_url = video_elem.get('src')
            file_path = f"{DOWNLOAD_DIR}/video_{msg_id}.mp4"
            if download_file_fast(video_url, file_path):
                if send_to_rubika("video", file_path, text):
                    state["last_id"] = max_processed_id
                    save_state_atomic(state)
                    logging.info(f"   💾 state ذخیره شد - last_id: {max_processed_id}")
                os.remove(file_path)
            continue
        
        if send_to_rubika("text", caption=text):
            state["last_id"] = max_processed_id
            save_state_atomic(state)
            logging.info(f"   💾 state ذخیره شد - last_id: {max_processed_id}")
        
        elapsed = time.time() - start_time
        logging.info(f"   ⏱️ زمان: {elapsed:.1f}s")
    
    # آپدیت نهایی
    if latest_id_in_page > max_processed_id:
        state["last_id"] = latest_id_in_page
        save_state_atomic(state)
        logging.info(f"🔄 آپدیت نهایی last_id به {latest_id_in_page}")
    
    print("=" * 55)
    logging.info(f"✅ اسکرپ کامل شد - آخرین ID: {state['last_id']}")
    print("=" * 55)

if __name__ == "__main__":
    scrape()
