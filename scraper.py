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
from html import unescape
import hashlib

# ========== تنظیمات ==========
RUBIKA_TOKEN = os.environ.get('RUBIKA_TOKEN')
RUBIKA_CHANNEL = "@NewsLine360"
SOURCE_CHANNEL = "KhabarFuri"
STATE_FILE = "state.json"
DOWNLOAD_DIR = "downloads"
LOG_FILE = "scraper.log"

# ========== تنظیمات پیشرفته ==========
CHUNK_SIZE = 65536
DOWNLOAD_TIMEOUT = 30
UPLOAD_TIMEOUT = 30
MAX_WORKERS = 5
SAVE_EVERY_N_MESSAGES = 2
MAX_CAPTION_LENGTH = 4000
RETRY_COUNT = 3
RETRY_DELAY = 2

FOOTER = """
────────────────────
@NewsLine360
────────────────────
"""

# تنظیم لاگینگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# ========== Session ==========
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Cache-Control': 'no-cache'
})
adapter = HTTPAdapter(pool_connections=30, pool_maxsize=30, max_retries=3)
session.mount('https://', adapter)
session.mount('http://', adapter)

# ========== توابع کمکی ==========
def clean_text(text):
    """تمیز کردن متن و حفظ ساختار"""
    if not text:
        return ""
    
    # حذف ایموجی‌ها
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
    
    # جایگزینی لینک‌ها
    text = re.sub(r'@KhabarFuri\b', RUBIKA_CHANNEL, text)
    text = re.sub(r'https?://t\.me/KhabarFuri[^\s]*', 'https://t.me/NewsLine360', text)
    text = re.sub(r'https?://t\.me/s/KhabarFuri[^\s]*', 'https://t.me/NewsLine360', text)
    
    # حذف فاصله‌های اضافی
    text = re.sub(r'[ ]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def format_text_for_rubika(html_content):
    """تبدیل HTML به متن ساده برای روبیکا"""
    if not html_content:
        return ""
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # استخراج متن با ساختار
    for tag in soup.find_all(['b', 'strong']):
        tag.replace_with(f"*{tag.text}*")
    
    for tag in soup.find_all(['i', 'em']):
        tag.replace_with(f"_{tag.text}_")
    
    for tag in soup.find_all('u'):
        tag.replace_with(f"__{tag.text}__")
    
    for tag in soup.find_all('s'):
        tag.replace_with(f"~{tag.text}~")
    
    for tag in soup.find_all('a'):
        href = tag.get('href', '')
        if href:
            tag.replace_with(f"{tag.text} ({href})")
        else:
            tag.replace_with(tag.text)
    
    for tag in soup.find_all('code'):
        tag.replace_with(f"`{tag.text}`")
    
    for tag in soup.find_all('span', class_='tg-spoiler'):
        tag.replace_with(f"[SPOILER: {tag.text}]")
    
    # استخراج متن نهایی
    text = soup.get_text(separator='\n')
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def extract_message_data(message):
    """استخراج کامل اطلاعات پیام"""
    data = {
        'text': '',
        'html': '',
        'photos': [],
        'video': None,
        'audio': None,
        'gif': None,
        'file': None,
        'msg_id': None,
        'is_forward': False,
        'forward_from': None
    }
    
    # استخراج ID
    data_post = message.get('data-post', '')
    if data_post:
        try:
            data['msg_id'] = int(data_post.split('/')[-1])
        except:
            pass
    
    # تشخیص فوروارد
    forward_elem = message.select_one('.tgme_widget_message_forwarded_from')
    if forward_elem:
        data['is_forward'] = True
        forward_text = forward_elem.get_text(strip=True)
        data['forward_from'] = forward_text.replace('Forwarded from', '').strip()
    
    # استخراج متن
    text_elem = message.select_one('.tgme_widget_message_text')
    if text_elem:
        data['html'] = str(text_elem)
        data['text'] = text_elem.get_text(separator='\n')
    
    # استخراج عکس‌های آلبوم
    grouped_wrap = message.select_one('.tgme_widget_message_grouped_wrap')
    if grouped_wrap:
        photo_wraps = grouped_wrap.select('a.tgme_widget_message_photo_wrap')
        for photo in photo_wraps:
            style = photo.get('style', '')
            match = re.search(r"url\('([^']+)'\)", style)
            if match:
                url = match.group(1)
                url = re.sub(r'_[sb]\d+\.', '.', url)
                data['photos'].append(url)
    else:
        photo_wrap = message.select_one('a.tgme_widget_message_photo_wrap')
        if photo_wrap:
            style = photo_wrap.get('style', '')
            match = re.search(r"url\('([^']+)'\)", style)
            if match:
                url = match.group(1)
                url = re.sub(r'_[sb]\d+\.', '.', url)
                data['photos'].append(url)
    
    # استخراج ویدیو
    video_elem = message.select_one('video')
    if video_elem and video_elem.get('src'):
        data['video'] = video_elem.get('src')
    
    # استخراج فایل صوتی
    audio_elem = message.select_one('audio')
    if audio_elem and audio_elem.get('src'):
        data['audio'] = audio_elem.get('src')
    
    # استخراج GIF
    gif_elem = message.select_one('.tgme_widget_message_photo_wrap[style*="gif"]')
    if gif_elem:
        style = gif_elem.get('style', '')
        match = re.search(r"url\('([^']+)'\)", style)
        if match:
            data['gif'] = match.group(1)
    
    # استخراج فایل
    file_elem = message.select_one('a.tgme_widget_message_document')
    if file_elem and file_elem.get('href'):
        data['file'] = file_elem.get('href')
    
    return data

def download_with_retry(url, file_path, max_retries=RETRY_COUNT):
    """دانلود با تلاش مجدد"""
    for attempt in range(max_retries):
        try:
            response = session.get(url, stream=True, timeout=(10, DOWNLOAD_TIMEOUT))
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                return True
        except Exception as e:
            logging.warning(f"تلاش {attempt+1}/{max_retries} ناموفق: {e}")
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
    return False

def download_photos_parallel(photos, msg_id):
    """دانلود موازی عکس‌ها"""
    if not photos:
        return []
    
    downloaded = []
    
    def download_single(idx, url):
        ext = url.split('.')[-1].split('?')[0] or 'jpg'
        if ext not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
            ext = 'jpg'
        file_path = f"{DOWNLOAD_DIR}/photo_{msg_id}_{idx}.{ext}"
        if download_with_retry(url, file_path):
            return (file_path, idx)
        return None
    
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(photos))) as executor:
        futures = [executor.submit(download_single, i, url) for i, url in enumerate(photos)]
        for future in as_completed(futures):
            result = future.result()
            if result:
                downloaded.append(result)
    
    downloaded.sort(key=lambda x: x[1])
    return [path for path, _ in downloaded]

def send_to_rubika(content_type, file_path=None, caption="", msg_id=0):
    """ارسال به روبیکا با مدیریت خطا"""
    if not RUBIKA_TOKEN:
        logging.error("RUBIKA_TOKEN تنظیم نشده")
        return False
    
    # پردازش متن
    if caption:
        if '<' in caption and '>' in caption:
            caption = format_text_for_rubika(caption)
        caption = clean_text(caption)
        caption = f"{caption}\n\n{FOOTER}"
        
        if len(caption) > MAX_CAPTION_LENGTH:
            caption = caption[:MAX_CAPTION_LENGTH-3] + "..."
    
    rubika_url = f"https://botapi.rubika.ir/v3/{RUBIKA_TOKEN}/"
    headers = {"Content-Type": "application/json"}
    
    for attempt in range(RETRY_COUNT):
        try:
            if content_type == "text":
                payload = {"chat_id": RUBIKA_CHANNEL, "text": caption}
                response = session.post(
                    rubika_url + "sendMessage",
                    data=json.dumps(payload, ensure_ascii=False),
                    headers=headers,
                    timeout=(10, 15)
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("status") == "OK":
                        return True
                
            elif content_type in ["photo", "video", "audio", "document"]:
                # تعیین نوع فایل برای روبیکا
                file_type_map = {
                    "photo": "Image",
                    "video": "Video",
                    "audio": "Voice",
                    "document": "Document"
                }
                file_type = file_type_map.get(content_type, "Document")
                
                # درخواست آپلود
                resp_upload = session.post(
                    rubika_url + "requestSendFile",
                    data=json.dumps({"type": file_type}),
                    headers=headers,
                    timeout=(10, 15)
                )
                
                if resp_upload.status_code != 200:
                    logging.error(f"خطا در requestSendFile: {resp_upload.status_code}")
                    continue
                
                upload_data = resp_upload.json()
                if upload_data.get("status") != "OK":
                    logging.error(f"خطا در پاسخ requestSendFile: {upload_data}")
                    continue
                
                upload_url = upload_data["data"]["upload_url"]
                
                # آپلود فایل
                with open(file_path, 'rb') as f:
                    resp_file = session.post(
                        upload_url,
                        files={"file": f},
                        timeout=(10, UPLOAD_TIMEOUT)
                    )
                
                if resp_file.status_code != 200:
                    logging.error(f"خطا در آپلود فایل: {resp_file.status_code}")
                    continue
                
                file_data = resp_file.json()
                if file_data.get("status") != "OK":
                    logging.error(f"خطا در پاسخ آپلود: {file_data}")
                    continue
                
                file_id = file_data["data"]["file_id"]
                
                # ارسال فایل
                payload = {
                    "chat_id": RUBIKA_CHANNEL,
                    "file_id": file_id,
                    "text": caption or ""
                }
                
                response = session.post(
                    rubika_url + "sendFile",
                    data=json.dumps(payload, ensure_ascii=False),
                    headers=headers,
                    timeout=(10, 15)
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("status") == "OK":
                        return True
                
            logging.error(f"تلاش {attempt+1} ناموفق")
            if attempt < RETRY_COUNT - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
                
        except Exception as e:
            logging.error(f"خطا در ارسال: {e}")
            if attempt < RETRY_COUNT - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
    
    return False

def send_album(photos, caption, msg_id):
    """ارسال آلبوم با حفظ ترتیب"""
    if not photos:
        return False
    
    # دانلود عکس‌ها
    downloaded_files = download_photos_parallel(photos, msg_id)
    
    if not downloaded_files:
        logging.error(f"هیچ عکسی دانلود نشد برای پیام {msg_id}")
        return False
    
    success = True
    
    # ارسال اولین عکس با کپشن
    first_file = downloaded_files[0]
    if not send_to_rubika("photo", first_file, caption, msg_id):
        success = False
    if os.path.exists(first_file):
        os.remove(first_file)
    
    # ارسال بقیه عکس‌ها بدون کپشن
    for file_path in downloaded_files[1:]:
        if not send_to_rubika("photo", file_path, "", msg_id):
            success = False
        if os.path.exists(file_path):
            os.remove(file_path)
    
    return success

def load_state():
    """بارگذاری state"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
                if "last_id" not in state:
                    state["last_id"] = 0
                if "processed_ids" not in state:
                    state["processed_ids"] = []
                return state
        except Exception as e:
            logging.error(f"خطا در بارگذاری state: {e}")
            return {"last_id": 0, "processed_ids": []}
    return {"last_id": 0, "processed_ids": []}

def save_state(state):
    """ذخیره state"""
    try:
        # محدود کردن لیست processed_ids
        if "processed_ids" in state and len(state["processed_ids"]) > 1000:
            state["processed_ids"] = state["processed_ids"][-1000:]
        
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"خطا در ذخیره state: {e}")
        return False

def scrape():
    """اسکرپ اصلی"""
    print("=" * 60)
    print("       اسکرپ کانال خبری - نسخه کامل")
    print("=" * 60)
    
    if not RUBIKA_TOKEN:
        logging.error("RUBIKA_TOKEN تنظیم نشده")
        return
    
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    url = f"https://t.me/s/{SOURCE_CHANNEL}"
    
    try:
        response = session.get(url, timeout=(10, 30))
        response.raise_for_status()
    except Exception as e:
        logging.error(f"خطا در دریافت صفحه: {e}")
        return
    
    soup = BeautifulSoup(response.text, 'html.parser')
    messages = soup.select('.tgme_widget_message')
    
    if not messages:
        logging.warning("هیچ پیامی پیدا نشد")
        return
    
    # استخراج اطلاعات
    msg_data = {}
    for msg in messages:
        data = extract_message_data(msg)
        if data['msg_id']:
            msg_data[data['msg_id']] = data
    
    if not msg_data:
        logging.warning("هیچ ID معتبری پیدا نشد")
        return
    
    latest_id = max(msg_data.keys())
    earliest_id = min(msg_data.keys())
    
    state = load_state()
    last_id = state.get("last_id", 0)
    processed_ids = set(state.get("processed_ids", []))
    
    print(f"📌 آخرین ID ذخیره شده: {last_id}")
    print(f"📌 محدوده ID: {earliest_id} تا {latest_id}")
    
    # پیدا کردن پیام‌های جدید
    new_ids = [
        msg_id for msg_id in msg_data.keys() 
        if msg_id > last_id and msg_id not in processed_ids
    ]
    
    if not new_ids:
        if latest_id > last_id:
            state["last_id"] = latest_id
            save_state(state)
        print("✅ هیچ پیام جدیدی نیست")
        return
    
    new_ids.sort()
    print(f"📨 {len(new_ids)} پیام جدید پیدا شد")
    
    max_processed = last_id
    count_since_save = 0
    total_sent = 0
    
    for msg_id in new_ids:
        data = msg_data[msg_id]
        
        # فقط پیام‌های حاوی @KhabarFuri
        if '@KhabarFuri' not in data['text']:
            logging.info(f"⏭️ رد شدن پیام {msg_id} (بدون @KhabarFuri)")
            processed_ids.add(msg_id)
            continue
        
        print(f"\n📥 پردازش پیام {msg_id}")
        if data.get('is_forward'):
            print(f"   🔄 فوروارد از: {data.get('forward_from', 'نامشخص')}")
        
        start_time = time.time()
        success = False
        
        try:
            # انتخاب نوع محتوا
            if data['photos']:
                print(f"   📸 {len(data['photos'])} عکس")
                success = send_album(data['photos'], data['html'] or data['text'], msg_id)
                
            elif data['video']:
                print("   🎬 ویدیو")
                file_path = f"{DOWNLOAD_DIR}/video_{msg_id}.mp4"
                if download_with_retry(data['video'], file_path):
                    success = send_to_rubika("video", file_path, data['html'] or data['text'], msg_id)
                    os.remove(file_path)
                else:
                    logging.error(f"دانلود ویدیو ناموفق: {msg_id}")
                    
            elif data['audio']:
                print("   🎵 فایل صوتی")
                file_path = f"{DOWNLOAD_DIR}/audio_{msg_id}.mp3"
                if download_with_retry(data['audio'], file_path):
                    success = send_to_rubika("audio", file_path, data['html'] or data['text'], msg_id)
                    os.remove(file_path)
                else:
                    logging.error(f"دانلود صوتی ناموفق: {msg_id}")
                    
            elif data['gif']:
                print("   🎞️ GIF")
                file_path = f"{DOWNLOAD_DIR}/gif_{msg_id}.gif"
                if download_with_retry(data['gif'], file_path):
                    success = send_to_rubika("document", file_path, data['html'] or data['text'], msg_id)
                    os.remove(file_path)
                else:
                    logging.error(f"دانلود GIF ناموفق: {msg_id}")
                    
            elif data['file']:
                print("   📄 فایل")
                file_path = f"{DOWNLOAD_DIR}/file_{msg_id}"
                if download_with_retry(data['file'], file_path):
                    success = send_to_rubika("document", file_path, data['html'] or data['text'], msg_id)
                    os.remove(file_path)
                else:
                    logging.error(f"دانلود فایل ناموفق: {msg_id}")
                    
            else:
                print("   📝 متن")
                success = send_to_rubika("text", caption=data['html'] or data['text'], msg_id=msg_id)
            
            if success:
                total_sent += 1
                count_since_save += 1
                processed_ids.add(msg_id)
                print("   ✅ ارسال شد")
            else:
                print("   ❌ خطا در ارسال")
                
        except Exception as e:
            logging.error(f"خطا در پردازش پیام {msg_id}: {e}")
        
        elapsed = time.time() - start_time
        print(f"   ⏱️ {elapsed:.1f} ثانیه")
        
        # به‌روزرسانی last_id
        if msg_id > max_processed:
            max_processed = msg_id
        
        # ذخیره دوره‌ای
        if count_since_save >= SAVE_EVERY_N_MESSAGES:
            state["last_id"] = max_processed
            state["processed_ids"] = list(processed_ids)
            save_state(state)
            count_since_save = 0
    
    # ذخیره نهایی
    state["last_id"] = max(latest_id, max_processed)
    state["processed_ids"] = list(processed_ids)
    save_state(state)
    
    print("\n" + "=" * 60)
    print(f"✅ اسکرپ کامل شد")
    print(f"📊 تعداد پیام‌های ارسال شده: {total_sent}")
    print(f"📌 آخرین ID: {state['last_id']}")
    print("=" * 60)

if __name__ == "__main__":
    try:
        scrape()
    except KeyboardInterrupt:
        print("\n⚠️ اسکرپ متوقف شد")
    except Exception as e:
        logging.error(f"خطای غیرمنتظره: {e}")
