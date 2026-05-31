import requests
import re
import os
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ========== تنظیمات روبیکا ==========
RUBIKA_TOKEN = os.environ.get('RUBIKA_TOKEN')
RUBIKA_CHANNEL = "@NewsLine360"
RUBIKA_HEADERS = {"Content-Type": "application/json"}

# ========== تنظیمات تلگرام ==========
SOURCE_CHANNEL = "KhabarFuri"
LAST_ID_FILE = "last_message_id.txt"

# ========== فوتر ==========
FOOTER = """
────────────────────
@NewsLine360
────────────────────
"""

def clean_and_format(text):
    if not text:
        return FOOTER.strip()
    # حذف تگ
    text = re.sub(r'@KhabarFuri\s*', '', text)
    # حذف ایموجی‌ها (از جمله پرچم)
    text = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]+', '', text)
    # حذف لینک‌های کانال مبدأ
    text = re.sub(r'https?://t\.me/[^\s]+', '', text)
    # حذف فاصله‌های اضافی
    text = re.sub(r'[ ]{2,}', ' ', text)
    # حذف خطوط خالی تکراری
    text = re.sub(r'\n{3,}', '\n\n', text)
    return f"{text.strip()}\n\n{FOOTER.strip()}"

def extract_data_from_page(html):
    """استخراج مستقیم با regex بدون BeautifulSoup (فقط برای سرعت)"""
    # الگوی پیام‌ها
    msg_pattern = r'data-post="([^"]+)"[^>]*>(.*?)<div class="tgme_widget_message_footer'
    msgs = re.findall(msg_pattern, html, re.DOTALL)
    
    results = []
    for data_post, content in msgs:
        if not data_post:
            continue
        
        msg_id = int(data_post.split('/')[-1])
        
        # استخراج متن
        text_match = re.search(r'<div class="tgme_widget_message_text"[^>]*>(.*?)</div>', content, re.DOTALL)
        text = re.sub(r'<[^>]+>', '', text_match.group(1)) if text_match else ""
        
        # استخراج عکس‌ها (آلبوم)
        photo_matches = re.findall(r'<a class="tgme_widget_message_photo_wrap"[^>]+style="background-image:url\(\'([^\']+)\'\)"', content)
        photos = [re.sub(r'_[sb]\d+\.jpg', '.jpg', p) for p in photo_matches]
        
        # استخراج ویدیو
        video_match = re.search(r'<video[^>]+src="([^"]+)"', content)
        video = video_match.group(1) if video_match else None
        if not video:
            video_match = re.search(r'<source[^>]+src="([^"]+)"', content)
            video = video_match.group(1) if video_match else None
        
        # فقط پیام‌های حاوی تگ
        if '@KhabarFuri' in text:
            results.append({
                'id': msg_id,
                'text': text,
                'photos': photos,
                'video': video
            })
    
    return results

def upload_and_send(file_path, file_type, caption):
    """آپلود و ارسال یک فایل به روبیکا (همان متد موفق قبلی)"""
    rubika_url = f"https://botapi.rubika.ir/v3/{RUBIKA_TOKEN}/"
    
    # مرحله 1: دریافت آدرس آپلود
    resp = requests.post(rubika_url + "requestSendFile", 
                        data=json.dumps({"type": file_type}),
                        headers=RUBIKA_HEADERS, timeout=10)
    if resp.status_code != 200:
        return False
    upload_url = resp.json()["data"]["upload_url"]
    
    # مرحله 2: آپلود فایل (با بافر 128KB برای سرعت)
    with open(file_path, 'rb') as f:
        resp2 = requests.post(upload_url, files={"file": f}, timeout=30)
    if resp2.status_code != 200:
        return False
    file_id = resp2.json()["data"]["file_id"]
    
    # مرحله 3: ارسال به کانال
    payload = {"chat_id": RUBIKA_CHANNEL, "file_id": file_id, "text": clean_and_format(caption)}
    resp3 = requests.post(rubika_url + "sendFile", data=json.dumps(payload),
                         headers=RUBIKA_HEADERS, timeout=10)
    
    return resp3.status_code == 200 and resp3.json().get("status") == "OK"

def download_media(url, msg_id, idx):
    """دانلود فایل از تلگرام با کیفیت اصلی"""
    # تشخیص نوع فایل از URL
    ext = 'jpg' if 'photo' in url or '.jpg' in url else 'mp4'
    file_path = f"downloads/{msg_id}_{idx}.{ext}"
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, stream=True, headers=headers, timeout=15)
        if resp.status_code == 200:
            with open(file_path, 'wb') as f:
                # بافر 128KB برای سرعت بالاتر و کیفیت یکسان
                for chunk in resp.iter_content(chunk_size=131072):
                    f.write(chunk)
            return file_path
    except Exception as e:
        print(f"   ✗ خطا در دانلود: {e}")
    return None

def scrape():
    print("=" * 50)
    print("اسکرپ کانال خبری (فوق سریع)")
    print("=" * 50)
    
    if not RUBIKA_TOKEN:
        print("❌ RUBIKA_TOKEN تنظیم نشده است")
        return
    
    # آماده‌سازی
    os.makedirs("downloads", exist_ok=True)
    
    # دریافت صفحه کانال
    url = f"https://t.me/s/{SOURCE_CHANNEL}"
    print(f"\n🔍 دریافت صفحه کانال...")
    
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        if response.status_code != 200:
            print(f"❌ خطا: کد وضعیت {response.status_code}")
            return
    except Exception as e:
        print(f"❌ خطا در اتصال: {e}")
        return
    
    # استخراج داده‌ها با regex
    print("📊 استخراج اطلاعات پیام‌ها...")
    messages = extract_data_from_page(response.text)
    
    if not messages:
        print("⚠️ هیچ پیامی با تگ مورد نظر پیدا نشد")
        return
    
    # خواندن آخرین ID پردازش شده
    last_id = 0
    if os.path.exists(LAST_ID_FILE):
        with open(LAST_ID_FILE, 'r') as f:
            try:
                last_id = int(f.read().strip())
            except:
                pass
    
    # فیلتر پیام‌های جدید
    new_messages = [m for m in messages if m['id'] > last_id]
    new_messages.sort(key=lambda x: x['id'])
    
    if not new_messages:
        print("📭 پیام جدیدی یافت نشد")
        return
    
    print(f"📨 {len(new_messages)} پیام جدید پیدا شد")
    print("-" * 50)
    
    # پردازش پیام‌ها (از قدیمی به جدید)
    for msg in new_messages:
        print(f"\n📥 پردازش پیام {msg['id']}")
        print(f"   📝 متن: {msg['text'][:50]}..." if len(msg['text']) > 50 else f"   📝 متن: {msg['text']}")
        
        # لیست فایل‌های دانلود شده
        downloaded_files = []
        
        # دانلود همزمان عکس‌ها و ویدیو (حداکثر ۳ ترد)
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = []
            # عکس‌ها
            for idx, photo_url in enumerate(msg['photos']):
                futures.append(executor.submit(download_media, photo_url, msg['id'], idx))
            # ویدیو
            if msg['video']:
                futures.append(executor.submit(download_media, msg['video'], msg['id'], 0))
            
            # جمع‌آوری نتایج
            for future in as_completed(futures):
                file_path = future.result()
                if file_path:
                    downloaded_files.append(file_path)
        
        # آپلود و ارسال همزمان فایل‌ها
        if downloaded_files:
            print(f"   📦 {len(downloaded_files)} فایل دانلود شد")
            with ThreadPoolExecutor(max_workers=2) as executor:
                upload_futures = []
                for file_path in downloaded_files:
                    file_type = "Image" if file_path.endswith('.jpg') else "Video"
                    upload_futures.append(executor.submit(upload_and_send, file_path, file_type, msg['text']))
                
                for future in as_completed(upload_futures):
                    if future.result():
                        print("   ✓ فایل با موفقیت ارسال شد")
                    else:
                        print("   ✗ خطا در ارسال فایل")
            
            # پاک کردن فایل‌های موقت
            for file_path in downloaded_files:
                try:
                    os.remove(file_path)
                except:
                    pass
        else:
            # فقط متن (بدون فایل)
            try:
                rubika_url = f"https://botapi.rubika.ir/v3/{RUBIKA_TOKEN}/sendMessage"
                payload = {"chat_id": RUBIKA_CHANNEL, "text": clean_and_format(msg['text'])}
                resp = requests.post(rubika_url, json=payload, headers=RUBIKA_HEADERS, timeout=10)
                if resp.status_code == 200 and resp.json().get("status") == "OK":
                    print("   ✓ متن با موفقیت ارسال شد")
                else:
                    print("   ✗ خطا در ارسال متن")
            except Exception as e:
                print(f"   ✗ خطا: {e}")
        
        # ذخیره آخرین ID پردازش شده
        with open(LAST_ID_FILE, 'w') as f:
            f.write(str(msg['id']))
        
        # تاخیر کوتاه برای جلوگیری از محدودیت
        time.sleep(0.5)
    
    print("\n" + "=" * 50)
    print("✅ فرآیند اسکرپ با موفقیت به پایان رسید")
    print("=" * 50)

if __name__ == "__main__":
    scrape()
