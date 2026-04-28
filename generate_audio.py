import requests
import time
import json
import os
import re
import sys
import io

# Cấu hình encoding cho console Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Cấu hình
SESSION_ID = "tab-1777094127588-xl9qucol"
BASE_URL = "https://tts.hotai.dev/api"
INPUT_FILE = "truyen.txt"
OUTPUT_DIR = "audio_output"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

HEADERS = {
    "accept": "*/*",
    "accept-language": "vi,en;q=0.9,en-US;q=0.8",
    "origin": "https://tts.hotai.dev",
    "referer": "https://tts.hotai.dev/vi",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
}

COOKIES = {
    "_ga": "GA1.1.752552191.1776818870",
    "_ga_6B4KDTB0PH": "GS2.1.s1777093309$o8$g1$t1777095839$j34$l0$h0"
}

def send_heartbeat():
    url = f"{BASE_URL}/presence/heartbeat"
    payload = {
        "sessionId": SESSION_ID,
        "path": "/vi"
    }
    try:
        response = requests.post(url, headers=HEADERS, cookies=COOKIES, json=payload)
        print(f"Heartbeat sent: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"Heartbeat error: {e}")
        return False

def generate_audio(text, index):
    url = f"{BASE_URL}/generate"
    
    # Đọc file audio mẫu nếu tồn tại
    ref_audio_path = '2.MP3'
    ref_audio_data = b''
    if os.path.exists(ref_audio_path):
        with open(ref_audio_path, 'rb') as f:
            ref_audio_data = f.read()
        print(f"Da tim thay file mau: {ref_audio_path} ({len(ref_audio_data)} bytes)")
    else:
        print(f"CANH BAO: Khong tim thay file mau {ref_audio_path}. Gui du lieu trong co the gay loi server.")

    files = {
        'mode': (None, 'clone'),
        'text': (None, text),
        'language': (None, 'vietnamese'),
        'design_prompt': (None, ''),
        'reference_text': (None, ''),
        'num_step': (None, '32'),
        'guidance_scale': (None, '2.0'),
        'speed': (None, '1.0'),
        'duration': (None, ''),
        'denoise': (None, 'true'),
        'preprocess_prompt': (None, 'true'),
        'postprocess_output': (None, 'true'),
        'trim_silence': (None, 'false'),
        'reference_audio': (ref_audio_path, ref_audio_data, 'audio/mpeg'),
        'trim_start': (None, '0.00'),
        'trim_end': (None, '124.91')
    }

    try:
        # Lưu ý: requests sẽ tự động set Content-Type với boundary khi dùng files parameter
        # Chúng ta bỏ Content-Type trong HEADERS mặc định để requests tự xử lý
        gen_headers = HEADERS.copy()
        if "content-type" in gen_headers:
            del gen_headers["content-type"]
            
        response = requests.post(url, headers=gen_headers, cookies=COOKIES, files=files)
        print(f"Generate request sent for part {index}: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            # Giả định kết quả trả về có chứa id hoặc jobId
            job_id = data.get("id") or data.get("jobId") or data.get("job_id")
            return job_id
        else:
            print(f"Error response: {response.text}")
            return None
    except Exception as e:
        print(f"Generate error: {e}")
        return None

def check_status(job_id, index):
    url = f"{BASE_URL}/status/{job_id}"
    print(f"Checking status for job {job_id}...")
    
    while True:
        try:
            response = requests.get(url, headers=HEADERS, cookies=COOKIES)
            if response.status_code == 200:
                data = response.json()
                status = data.get("status")
                print(f"Status: {status}")
                
                if status == "success" or status == "completed":
                    audio_url = data.get("audioUrl") or data.get("url")
                    if audio_url:
                        return audio_url
                    else:
                        print("Job success but no audio URL found.")
                        return None
                elif status == "failed" or status == "error":
                    print(f"Job failed/error. Full response: {json.dumps(data, indent=2)}")
                    return None
                else:
                    print(f"Unknown status: {status}. Full response: {json.dumps(data, indent=2)}")
            else:
                print(f"Status check error {response.status_code}: {response.text}")
        except Exception as e:
            print(f"Status check error: {e}")
            
        time.sleep(5) # Đợi 5 giây trước khi kiểm tra lại

def download_audio(url_or_data, index):
    try:
        file_path = os.path.join(OUTPUT_DIR, f"{index}.wav")
        
        # Kiểm tra nếu là dữ liệu Base64
        if url_or_data.startswith("data:") or len(url_or_data) > 500:
            import base64
            # Loại bỏ phần header của data URI nếu có (vd: data:audio/wav;base64,)
            if "," in url_or_data:
                data = url_or_data.split(",")[1]
            else:
                data = url_or_data
            
            audio_data = base64.b64decode(data)
            with open(file_path, "wb") as f:
                f.write(audio_data)
            print(f"Saved Base64 audio to: {file_path}")
            return file_path
        
        # Nếu là URL bình thường
        response = requests.get(url_or_data)
        if response.status_code == 200:
            with open(file_path, "wb") as f:
                f.write(response.content)
            print(f"Downloaded: {file_path}")
            return file_path
    except Exception as e:
        print(f"Download error: {e}")
    return None

def split_sentences(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    # Tách theo dấu câu . ! ? ... hoặc xuống dòng
    parts = re.split(r"(?<=[.!?…])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"File {INPUT_FILE} không tồn tại.")
        return

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    with open(INPUT_FILE, "r", encoding="utf-8", errors="ignore") as f:
        raw_text = f.read()
    
    sentences = split_sentences(raw_text)
    print(f"Tìm thấy {len(sentences)} câu để xử lý.")

    # Tạo metadata.csv giống vbee
    metadata_path = os.path.join(OUTPUT_DIR, "metadata.csv")
    with open(metadata_path, "w", encoding="utf-8") as f:
        for idx, sentence in enumerate(sentences, start=1):
            clean_s = re.sub(r'\s+', ' ', sentence).strip()
            f.write(f"{idx}.wav|{clean_s}\n")
    print(f"Đã tạo file metadata tại: {metadata_path}")

    i = 0
    while i < len(sentences):
        sentence = sentences[i]
        file_path = os.path.join(OUTPUT_DIR, f"{i+1}.wav")
        
        if os.path.exists(file_path):
            print(f"--- Câu {i+1}/{len(sentences)} đã tồn tại, bỏ qua ---")
            i += 1
            continue

        print(f"\n--- Đang xử lý câu {i+1}/{len(sentences)} ---")
        print(f"Nội dung: {sentence[:50]}...")
        
        send_heartbeat()
        
        response_data = None
        url = f"{BASE_URL}/generate"
        
        # Đọc file audio mẫu
        ref_audio_path = '2.MP3'
        ref_audio_data = b''
        if os.path.exists(ref_audio_path):
            with open(ref_audio_path, 'rb') as f:
                ref_audio_data = f.read()
        
        files = {
            'mode': (None, 'clone'),
            'text': (None, sentence),
            'language': (None, 'vietnamese'),
            'num_step': (None, '32'),
            'guidance_scale': (None, '2.0'),
            'speed': (None, '1.0'),
            'denoise': (None, 'true'),
            'preprocess_prompt': (None, 'true'),
            'postprocess_output': (None, 'true'),
            'trim_silence': (None, 'false'),
            'reference_audio': (ref_audio_path, ref_audio_data, 'audio/mpeg'),
            'trim_start': (None, '0.00'),
            'trim_end': (None, '124.91')
        }

        gen_headers = HEADERS.copy()
        if "content-type" in gen_headers: del gen_headers["content-type"]
        
        resp = requests.post(url, headers=gen_headers, cookies=COOKIES, files=files)
        
        if resp.status_code == 429:
            err_msg = resp.json().get("error", "")
            # Tìm số giây cần đợi trong thông báo lỗi (vd: "22 giây")
            wait_time = 20
            match = re.search(r'(\d+)', err_msg)
            if match:
                wait_time = int(match.group(1)) + 2
            
            print(f"Rate limit hit. Waiting {wait_time}s as requested by server...")
            time.sleep(wait_time)
            continue # Thử lại câu này

        if resp.status_code == 200:
            job_id = resp.json().get("id") or resp.json().get("jobId")
            if job_id:
                audio_url = check_status(job_id, i+1)
                if audio_url:
                    if audio_url.startswith("/") and not audio_url.startswith("data:"):
                        audio_url = "https://tts.hotai.dev" + audio_url
                    download_audio(audio_url, i+1)
                    print("Dang nghi 15s truoc khi tiep tuc...")
                    time.sleep(15)
            i += 1 # Xong câu này, chuyển sang câu tiếp theo
        else:
            print(f"Error {resp.status_code}: {resp.text}")
            time.sleep(5)
            i += 1

if __name__ == "__main__":
    main()
