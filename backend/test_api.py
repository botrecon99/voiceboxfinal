import requests
import time
import os

BASE_URL = "http://127.0.0.1:17493"
TEST_TEXT = "good good good good good good good good good good "
OUTPUT_FILE = "ket_qua_audio.wav"

def test_tts_api():
    print("🚀 BƯỚC 1: GỬI LỆNH GENERATE...")
    payload = {
        "text": TEST_TEXT,
        "model_id": "qwen", 
        "profile_id": "fb6a1585-81b6-4cb1-98f5-61859f25c38d",
        "language": "ko" 
    }
    
    try:
        resp = requests.post(f"{BASE_URL}/generate", json=payload, timeout=30)
        data = resp.json()
        generation_id = data.get("id")
        print(f"-> Đã lấy được ID: {generation_id}")
    except Exception as e:
        print(f"❌ Lỗi POST: {e}")
        return

    print("\n⏳ BƯỚC 2: ĐANG ĐỢI SERVER RENDER VÀ TẢI FILE...")
    # Đây là link bạn soi được trong Network
    download_url = f"{BASE_URL}/audio/{generation_id}"
    
    max_retries = 30  # Đợi tối đa 30 giây
    for i in range(max_retries):
        try:
            # Thử tải file trực tiếp
            r = requests.get(download_url, stream=True, timeout=5)
            
            # Nếu status là 200 và có nội dung audio
            if r.status_code == 200:
                content_type = r.headers.get('Content-Type', '').lower()
                # Kiểm tra xem có phải audio thật không hay là JSON báo lỗi
                if "audio" in content_type or r.content.startswith(b'RIFF'):
                    with open(OUTPUT_FILE, 'wb') as f:
                        f.write(r.content)
                    print(f"\n✅ THÀNH CÔNG! Đã lưu file: {os.path.abspath(OUTPUT_FILE)}")
                    return
            
            # Nếu chưa có (404) hoặc đang xử lý, in ra dấu chấm để theo dõi
            print(f".", end="", flush=True)
            
        except Exception:
            pass
            
        time.sleep(1)
    
    print("\n❌ Quá thời gian chờ (Timeout) mà server chưa nhả file audio.")

if __name__ == "__main__":
    test_tts_api()