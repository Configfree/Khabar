import requests
import re
import os
import time
import json
import logging
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

# ========== تنظیمات ==========
RUBIKA_TOKEN = os.environ.get('RUBIKA_TOKEN')
RUBIKA_CHANNEL = "@NewsLine360"
SOURCE_CHANNEL = "KhabarFuri"
STATE_FILE = "state.json"
DOWNLOAD_DIR = "downloads"

# ========== بهینه‌سازی سرعت ==========
MAX_WORKERS = 2  # تعداد ارسال همزمان
CHUNK_SIZE = 65536  # 64KB برای دانلود سریعتر
DOWNLOAD_TIMEOUT = 15
UPLOAD_TIMEOUT = 15
COMPRESS_IMAGES = True  # فشرده‌سازی عکس‌ها
MAX_IMAGE_SIZE_KB = 300  # حداکثر حجم عکس بعد از فشرده‌سازی

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

def compress_image(file_path):
    """فشرده‌سازی عکس برای آپلود سریعتر"""
    if not COMPRESS_IMAGES:
        return True
    
    try:
        from PIL import Image
        
        # باز کردن عکس
        img = Image.open(file_path)
        
        # تبدیل به RGB اگر RGBA بود
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        # محاسبه ابعاد جدید (اگر خیلی بزرگ بود)
        max_dimension = 1280
        if max(img.size) > max_dimension:
            ratio = max_dimension / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # فشرده‌سازی با کیفیت متغیر
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
        
        original_size = os.path.getsize(file_path)
        compressed_size = len(output.getvalue())
        
        logging.info(f"   📦 فشرده‌سازی: {original_size/1024:.0f}KB → {compressed_size/1024:.0f}KB")
        return True
        
    except Exception as e:
        logging.warning(f"   ⚠️ خطا در فشرده‌سازی: {e}")
        return False

def download_file_fast(url, file_path):
    """دانلود سریع با بهینه‌سازی"""
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive'
    }
    
    try:
        response = requests.get(url, stream=True, headers=headers, timeout=DOWNLOAD_TIMEOUT)
        
        if response.status_code == 200:
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
            
            file_size_kb = os.path.getsize(file_path) / 1024
            logging.info(f"   ✅ دانلود: {file_size_kb:.0f}KB")
            
            # فشرده‌سازی عکس
            if file_path.endswith(('.jpg', '.jpeg', '.png')) and COMPRESS_IMAGES:
                compress_image(file_path)
            
            return True
        else:
            return False
            
    except Exception as e:
        logging.error(f"   ❌ خطا: {e}")
        return False

def send_to_rubika_optimized(content_type, file_path=None, caption=""):
    """ارسال بهینه به روبیکا با timeout کمتر"""
    if not RUBIKA_TOKEN:
        return None
    
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
            logging.info(f"   ✓ متن ارسال شد ({elapsed:.1f}s)")
            return response
        
        elif content_type in ["photo", "video"]:
            file_type = "Image" if content_type == "photo" else "Video"
            
            # مرحله 1: درخواست آپلود
            start_time = time.time()
            resp_upload = requests.post(
                rubika_url + "requestSendFile",
                data=json.dumps({"type": file_type}),
                headers=headers,
                timeout=8
            )
            
            if resp_upload.status_code != 200:
                return None
                
            upload_data = resp_upload.json()
            if upload_data.get("status") != "OK":
                return None
                
            upload_url = upload_data["data"]["upload_url"]
            
            # مرحله 2: آپلود فایل
            with open(file_path, 'rb') as f:
                resp_file = requests.post(
                    upload_url, 
                    files={"file": f}, 
                    timeout=UPLOAD_TIMEOUT
                )
                
            file_data = resp_file.json()
            if file_data.get("status") != "OK":
                return None
                
            file_id = file_data["data"]["file_id"]
            
            # مرحله 3: ارسال نهایی
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
            logging.info(f"   ✓ {content_type} ارسال شد ({file_size_kb:.0f}KB, {elapsed:.1f}s)")
            
            return response
            
    except Exception as e:
        logging.error(f"   ✗ خطا: {e}")
        return None

def send_album_parallel(photos, caption, msg_id):
    """ارسال همزمان عکس‌های آلبوم برای افزایش سرعت"""
    downloaded_files = []
    
    # مرحله 1: دانلود همه عکس‌ها
    for idx, photo_url in enumerate(photos):
        file_path = f"{DOWNLOAD_DIR}/album_{msg_id}_{idx}.jpg"
        if download_file_fast(photo_url, file_path):
            downloaded_files.append((file_path, idx))
        else:
            logging.warning(f"   ⚠️ خطا در دانلود عکس {idx+1}")
    
    if not downloaded_files:
        return
    
    # مرحله 2: ارسال همزمان
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        
        for file_path, idx in downloaded_files:
            if idx == len(photos) - 1:
                future = executor.submit(send_to_rubika_optimized, "photo", file_path, caption)
            else:
                future = executor.submit(send_to_rubika_optimized, "photo", file_path, "")
            futures.append((future, file_path))
        
        # مرحله 3: انتظار برای اتمام و پاکسازی
        for future, file_path in futures:
            try:
                future.result(timeout=30)
            except:
                pass
            if os.path.exists(file_path):
                os.remove(file_path)
        
        time.sleep(0.1)  # تاخیر کم بین گروه‌ها

def extract_album_photos(message):
    """استخراج تمام عکس‌های آلبوم"""
    photos = []
    
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
    
    photo_wrap = message.select_one('a.tgme_widget_message_photo_wrap')
    if photo_wrap:
        style = photo_wrap.get('style', '')
        match = re.search(r"url\('([^']+)'\)", style)
        if match:
            url = match.group(1)
            url = re.sub(r'_[sb]\d+\.jpg', '.jpg', url)
            photos.append(url)
    
    return photos

def scrape():
    """تابع اصلی اسکرپ"""
    print("=" * 55)
    print("       اسکرپ کانال خبری - NewsLine360 (بهینه)")
    print("=" * 55)
    
    if not RUBIKA_TOKEN:
        logging.error("RUBIKA_TOKEN تنظیم نشده")
        return
    
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    # بررسی وجود PIL برای فشرده‌سازی
    if COMPRESS_IMAGES:
        try:
            from PIL import Image
            logging.info("✅ فشرده‌سازی عکس فعال است")
        except ImportError:
            logging.warning("⚠️ PIL نصب نیست - لطفاً نصب کنید: pip install Pillow")
    
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
    
    # پردازش پیام‌های جدید
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
    
    new_messages.sort(key=lambda x: x[0])
    logging.info(f"📨 {len(new_messages)} پیام جدید")
    
    # پردازش پیام‌ها
    max_id = last_id
    total_start = time.time()
    
    for msg_id, msg in new_messages:
        text_elem = msg.select_one('.tgme_widget_message_text')
        text = text_elem.get_text() if text_elem else ""
        
        if '@KhabarFuri' not in text:
            continue
        
        logging.info(f"\n📥 پیام {msg_id}")
        start_time = time.time()
        
        # استخراج عکس‌ها
        photos = extract_album_photos(msg)
        
        if photos:
            logging.info(f"   📸 {len(photos)} عکس")
            send_album_parallel(photos, text, msg_id)
            max_id = max(max_id, msg_id)
            elapsed = time.time() - start_time
            logging.info(f"   ⏱️ زمان کل: {elapsed:.1f}s")
            continue
        
        # ویدیو
        video_elem = msg.select_one('video, source')
        if video_elem and video_elem.get('src'):
            video_url = video_elem.get('src')
            file_path = f"{DOWNLOAD_DIR}/video_{msg_id}.mp4"
            if download_file_fast(video_url, file_path):
                send_to_rubika_optimized("video", file_path, text)
                os.remove(file_path)
            max_id = max(max_id, msg_id)
            elapsed = time.time() - start_time
            logging.info(f"   ⏱️ زمان کل: {elapsed:.1f}s")
            continue
        
        # فقط متن
        send_to_rubika_optimized("text", caption=text)
        max_id = max(max_id, msg_id)
        elapsed = time.time() - start_time
        logging.info(f"   ⏱️ زمان کل: {elapsed:.1f}s")
    
    # ذخیره state
    if max_id > last_id:
        save_state({"last_id": max_id, "processed_groups": []})
        logging.info(f"✅ ذخیره شد - آخرین ID: {max_id}")
    
    total_elapsed = time.time() - total_start
    print("=" * 55)
    print(f"✅ اسکرپ کامل شد - زمان کل: {total_elapsed:.1f} ثانیه")
    print("=" * 55)

if __name__ == "__main__":
    scrape()
