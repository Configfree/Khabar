import requests
import re
import os
import time
import json
import logging
from bs4 import BeautifulSoup
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter

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
COMPRESS_IMAGES = True  # ✅ فعال با کیفیت بالا
MAX_IMAGE_SIZE_KB = 800  # افزایش به 800KB برای کیفیت بهتر
IMAGE_QUALITY = 85  # کیفیت بالا (100 بهترین، 70 معمولی)
MAX_WORKERS = 3
SAVE_EVERY_N_MESSAGES = 3

FOOTER = """
────────────────────
@NewsLine360
────────────────────
"""

# کاهش logging (فقط خطاها)
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ========== Session بهینه ==========
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0',
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive'
})

# افزایش connection pool
adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=2)
session.mount('https://', adapter)
session.mount('http://', adapter)

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
            return {"last_id": 0}
    return {"last_id": 0}

def save_state_atomic(state):
    tmp_file = STATE_FILE + ".tmp"
    try:
        with open(tmp_file, 'w') as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_file, STATE_FILE)
        return True
    except Exception as e:
        logging.error(f"❌ خطا در ذخیره state: {e}")
        return False

def download_file_fast(url, file_path):
    try:
        response = session.get(url, stream=True, timeout=(5, DOWNLOAD_TIMEOUT))
        if response.status_code == 200:
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
            return True
        return False
    except Exception:
        return False

def compress_image_high_quality(file_path, original_size_kb):
    """فشرده‌سازی عکس با حفظ کیفیت بالا"""
    try:
        from PIL import Image
        
        # عکس‌های کوچک رو فشرده نکن
        if original_size_kb < 150:
            return True
        
        img = Image.open(file_path)
        original_format = img.format
        
        # برای PNG شفاف، حفظ شفافیت
        if original_format == 'PNG' and img.mode == 'RGBA':
            # فقط ابعاد رو کم کن اگر خیلی بزرگه
            max_dimension = 1600
            if max(img.size) > max_dimension:
                ratio = max_dimension / max(img.size)
                new_size = tuple(int(dim * ratio) for dim in img.size)
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                img.save(file_path, format='PNG', optimize=True)
            return True
        
        # تبدیل به RGB برای JPEG
        if img.mode in ('RGBA', 'P'):
            # ایجاد پس‌زمینه سفید برای شفافیت
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                background.paste(img, mask=img.split()[3])
            else:
                background.paste(img)
            img = background
        
        # کاهش ابعاد فقط اگر خیلی بزرگ باشه (کیفیت حفظ بشه)
        max_dimension = 1600
        if max(img.size) > max_dimension:
            ratio = max_dimension / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # فشرده‌سازی با کیفیت بالا
        output = BytesIO()
        img.save(output, format='JPEG', quality=IMAGE_QUALITY, optimize=True)
        
        # اگر حجم باز هم زیاد بود، کیفیت رو کم کم کاهش بده
        if output.tell() > MAX_IMAGE_SIZE_KB * 1024:
            quality = IMAGE_QUALITY
            while quality > 65 and output.tell() > MAX_IMAGE_SIZE_KB * 1024:
                quality -= 5
                output.seek(0)
                output.truncate()
                img.save(output, format='JPEG', quality=quality, optimize=True)
        
        # ذخیره فایل فشرده شده
        with open(file_path, 'wb') as f:
            f.write(output.getvalue())
        
        new_size_kb = os.path.getsize(file_path) / 1024
        saved_percent = (1 - new_size_kb / original_size_kb) * 100 if original_size_kb > 0 else 0
        
        if saved_percent > 10:
            # فقط با لاگ معمولی (نه خطا)
            pass
        
        return True
        
    except Exception as e:
        return False

def download_and_compress(url, file_path):
    """دانلود و فشرده‌سازی عکس"""
    try:
        response = session.get(url, stream=True, timeout=(5, DOWNLOAD_TIMEOUT))
        if response.status_code == 200:
            # دریافت حجم اصلی
            original_size = int(response.headers.get('content-length', 0))
            original_size_kb = original_size / 1024
            
            # دانلود
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
            
            # فشرده‌سازی با کیفیت بالا
            if COMPRESS_IMAGES and file_path.endswith(('.jpg', '.jpeg', '.png')):
                compress_image_high_quality(file_path, original_size_kb)
            
            return True
        return False
    except Exception:
        return False

def download_photos_parallel(photos, msg_id):
    """دانلود موازی عکس‌ها با فشرده‌سازی"""
    jobs = []
    for idx, photo_url in enumerate(photos):
        file_path = f"{DOWNLOAD_DIR}/album_{msg_id}_{idx}.jpg"
        jobs.append((photo_url, file_path, idx))
    
    downloaded = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_and_compress, url, path): (path, idx) 
                   for url, path, idx in jobs}
        
        for future in as_completed(futures):
            file_path, idx = futures[future]
            if future.result():
                downloaded.append((file_path, idx))
    
    downloaded.sort(key=lambda x: x[1])
    return [path for path, _ in downloaded]

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
    """ارسال به روبیکا"""
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
            response = session.post(
                rubika_url + "sendMessage",
                data=json.dumps(payload),
                headers=headers,
                timeout=(5, 15)
            )
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    if result.get("status") == "OK":
                        return True
                except:
                    pass
            return False
        
        elif content_type in ["photo", "video"]:
            file_type = "Image" if content_type == "photo" else "Video"
            
            resp_upload = session.post(
                rubika_url + "requestSendFile",
                data=json.dumps({"type": file_type}),
                headers=headers,
                timeout=(5, 15)
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
                resp_file = session.post(
                    upload_url, 
                    files={"file": f}, 
                    timeout=(5, UPLOAD_TIMEOUT)
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
            
            response = session.post(
                rubika_url + "sendFile",
                data=json.dumps(payload),
                headers=headers,
                timeout=(5, 15)
            )
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    if result.get("status") == "OK":
                        return True
                except:
                    pass
            return False
            
    except Exception:
        return False

def send_album_parallel(photos, caption, msg_id):
    """ارسال آلبوم - دانلود موازی با فشرده‌سازی"""
    downloaded_files = download_photos_parallel(photos, msg_id)
    
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
    """نسخه نهایی با فشرده‌سازی باکیفیت"""
    print("=" * 55)
    print("       اسکرپ کانال خبری - NewsLine360 (نسخه نهایی)")
    print("=" * 55)
    
    if not RUBIKA_TOKEN:
        logging.error("RUBIKA_TOKEN تنظیم نشده")
        return
    
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    # بررسی PIL
    if COMPRESS_IMAGES:
        try:
            from PIL import Image
            print("✅ فشرده‌سازی عکس با کیفیت بالا فعال است")
        except ImportError:
            print("⚠️ PIL نصب نیست - نصب کنید: pip install Pillow")
    
    url = f"https://t.me/s/{SOURCE_CHANNEL}"
    
    try:
        response = session.get(url, timeout=(5, 30))
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
    
    print(f"📌 آخرین ID: {last_id}")
    print(f"📌 محدوده ID: {earliest_id_in_page} تا {latest_id_in_page}")
    
    new_msg_ids = [msg_id for msg_id in msg_dict.keys() if msg_id > last_id]
    
    if not new_msg_ids:
        if latest_id_in_page > last_id:
            state["last_id"] = latest_id_in_page
            save_state_atomic(state)
        return
    
    new_msg_ids.sort()
    print(f"📨 {len(new_msg_ids)} پیام جدید")
    
    max_processed_id = last_id
    messages_since_last_save = 0
    
    for msg_id in new_msg_ids:
        msg = msg_dict[msg_id]
        
        if msg_id > max_processed_id:
            max_processed_id = msg_id
        
        text_elem = msg.select_one('.tgme_widget_message_text')
        text = text_elem.text if text_elem else ""
        
        if '@KhabarFuri' not in text:
            continue
        
        print(f"\n📥 پیام {msg_id}")
        start_time = time.time()
        
        photos = extract_album_photos(msg)
        
        if photos:
            print(f"   📸 {len(photos)} عکس (فشرده‌سازی با کیفیت)")
            if send_album_parallel(photos, text, msg_id):
                messages_since_last_save += 1
            continue
        
        video_elem = msg.select_one('video, source')
        if video_elem and video_elem.get('src'):
            video_url = video_elem.get('src')
            file_path = f"{DOWNLOAD_DIR}/video_{msg_id}.mp4"
            if download_file_fast(video_url, file_path):
                if send_to_rubika("video", file_path, text):
                    messages_since_last_save += 1
                os.remove(file_path)
            continue
        
        if send_to_rubika("text", caption=text):
            messages_since_last_save += 1
        
        elapsed = time.time() - start_time
        print(f"   ⏱️ {elapsed:.1f}s")
        
        if messages_since_last_save >= SAVE_EVERY_N_MESSAGES:
            state["last_id"] = max_processed_id
            save_state_atomic(state)
            messages_since_last_save = 0
    
    if latest_id_in_page > max_processed_id:
        state["last_id"] = latest_id_in_page
    else:
        state["last_id"] = max_processed_id
    save_state_atomic(state)
    
    print("=" * 55)
    print(f"✅ اسکرپ کامل شد - آخرین ID: {state['last_id']}")
    print("=" * 55)

if __name__ == "__main__":
    scrape()
