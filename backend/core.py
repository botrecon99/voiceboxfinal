# core.py
# -*- coding: utf-8 -*-
import requests
import json
import re
import os
import asyncio
import edge_tts
import shutil
import yt_dlp
import hashlib
import subprocess
import imageio_ffmpeg
import textwrap
import platform
import traceback
import http.cookiejar
import threading
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip, vfx
from proglog import ProgressBarLogger
import time

# ==============================================================================
# [CẤU HÌNH HỆ THỐNG]
# ==============================================================================
API_PORT = 17493  # Cổng Backend đang chạy
BASE_URL = f"http://127.0.0.1:{API_PORT}"

# ==============================================================================
# [LOGGING UTILS]
# ==============================================================================
def log_info(msg): print(f"🔵 [INFO] {msg}")
def log_success(msg): print(f"✅ [SUCCESS] {msg}")
def log_warn(msg): print(f"⚠️ [WARN] {msg}")
def log_error(msg, e=None): 
    print(f"❌ [ERROR] {msg}")
    if e: print(f"👉 Chi tiết lỗi: {e}")
def log_step(msg): print(f"\n🚀 >>> {msg} <<<")

# ==============================================================================
# [FIX LỖI MAX STDIO (ERRNO 24)]
# ==============================================================================
if platform.system() == 'Windows':
    import ctypes
    try:
        ctypes.windll.msvcrt._setmaxstdio(2048)
    except: pass

# ==============================================================================
# [CẤU HÌNH FFMPEG & COOKIES]
# ==============================================================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG_LOCAL_PATH = os.path.join(CURRENT_DIR, "ffmpeg.exe")
COOKIE_YOUTUBE_FILE = os.path.join(CURRENT_DIR, "cookies.txt")

if os.path.exists(FFMPEG_LOCAL_PATH):
    os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_LOCAL_PATH
else:
    FFMPEG_LOCAL_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_LOCAL_PATH

BASE_DATA_FOLDER = "downloaded_data"
COOKIE_TRACK_FILE = "cookie_tracker.json"
cookie_lock = threading.Lock()

class MyBarLogger(ProgressBarLogger):
    def __init__(self, progress_func=None):
        super().__init__()
        self.progress_func = progress_func

    def bars_callback(self, bar, attr, value, old_value=None):
        if bar == 't' and self.progress_func:
            try:
                total = self.bars[bar]['total']
                if total > 0:
                    pct = 60 + ((value / total) * 100 * 0.4)
                    self.progress_func(int(pct), f"Đang Render Video MP4: {int((value/total)*100)}%")
            except: pass

def extract_video_id(url):
    regex = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(regex, url)
    return match.group(1) if match else None

def check_and_track_cookie(cookie_string, video_id):
    if not cookie_string: return
    cookie_hash = hashlib.md5(cookie_string.strip().encode('utf-8')).hexdigest()
    today_str = str(date.today())
    
    with cookie_lock:
        data = {}
        if os.path.exists(COOKIE_TRACK_FILE):
            try:
                with open(COOKIE_TRACK_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
            except: pass
        
        user_data = data.get(cookie_hash, {})
        if isinstance(user_data, list): user_data = {"date": today_str, "videos": []}

        last_date = user_data.get("date", "")
        used_videos = user_data.get("videos", [])
        
        if last_date != today_str:
            used_videos = []
            last_date = today_str
        
        if len(used_videos) >= 5 and video_id not in used_videos:
            raise Exception(f"⛔ HẾT LƯỢT HÔM NAY! Đã dùng 5 lượt ngày {today_str}.")
        
        if video_id not in used_videos:
            used_videos.append(video_id)
            data[cookie_hash] = {"date": last_date, "videos": used_videos}
            with open(COOKIE_TRACK_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)

def generate_srt_file(subtitles, output_path):
    def format_timestamp(seconds):
        millis = int((seconds - int(seconds)) * 1000)
        seconds = int(seconds)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"
        
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, sub in enumerate(subtitles):
            f.write(f"{i+1}\n{format_timestamp(sub['start'])} --> {format_timestamp(sub['end'])}\n{sub['text']}\n\n")

def time_stretch_audio(input_path, output_path, speed_factor):
    if speed_factor > 2.0: speed_factor = 2.0
    subprocess.run([FFMPEG_LOCAL_PATH, '-y', '-i', input_path, '-filter:a', f"atempo={speed_factor}", '-vn', output_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path if os.path.exists(output_path) else input_path

class YouTubeProExtractor:
    def __init__(self, headers):
        self.session = requests.Session()
        self.session.headers.update(headers)
        if os.path.exists(COOKIE_YOUTUBE_FILE):
            try:
                cj = http.cookiejar.MozillaCookieJar(COOKIE_YOUTUBE_FILE)
                cj.load(ignore_discard=True, ignore_expires=True)
                self.session.cookies = cj
            except: pass

    def get_subtitle_data(self, video_id, output_folder, lang_code='en'):
        log_step(f"Đang trích xuất phụ đề gốc cho ID: {video_id}")
        try:
            ydl_opts = {
                'quiet': True, 'skip_download': True, 'writesubtitles': True,
                'writeautomaticsub': True, 'subtitleslangs': [lang_code, 'en'],
                'ignore_no_formats_error': True, 'format': 'none',
                'extractor_args': {'youtube': {'player_client': ['all']}},
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': 'https://www.youtube.com'
                },
                'javascript_runtimes': ['node'] 
            }
            if os.path.exists(COOKIE_YOUTUBE_FILE): ydl_opts['cookiefile'] = COOKIE_YOUTUBE_FILE

            with yt_dlp.YoutubeDL(ydl_opts) as ydl: info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

            sub_url = None
            target_track = info.get('subtitles', {}).get(lang_code) or info.get('automatic_captions', {}).get(lang_code) or info.get('subtitles', {}).get('en') or info.get('automatic_captions', {}).get('en')
            
            if not target_track: return []

            for fmt in target_track:
                if fmt.get('ext') == 'json3' or 'json3' in fmt.get('url', ''):
                    sub_url = fmt.get('url'); break

            if not sub_url: return []

            sub_resp = self.session.get(sub_url, timeout=15)
            if sub_resp.status_code != 200: return []
            raw_data = sub_resp.json()
            
            all_segments = []
            noise_pattern = re.compile(r'^(\[.*\]|\(.*\))$')

            for e in raw_data.get("events", []):
                if "segs" not in e: continue
                event_start_ms = e.get('tStartMs', 0)
                for s in e["segs"]:
                    text_chunk = s.get("utf8", "").strip()
                    if text_chunk: all_segments.append({"text": text_chunk, "start_ms": event_start_ms + s.get('tOffsetMs', 0), "is_noise": bool(noise_pattern.match(text_chunk))})
            
            all_segments.sort(key=lambda x: x["start_ms"])

            parsed_subs = []; current_text = ""; current_start_ms = -1
            for i, seg in enumerate(all_segments):
                if current_start_ms == -1:
                    if seg["is_noise"]: continue
                    else: current_start_ms = seg["start_ms"]
                
                current_text += (" " if current_text and not current_text.endswith(" ") else "") + seg["text"]
                clean_word = seg["text"].strip()
                is_end = (clean_word and clean_word[-1] in ['.', '?', '!', '。']) or (seg["start_ms"] - current_start_ms > 5000) or (i == len(all_segments) - 1)

                if is_end:
                    if current_start_ms == -1: current_start_ms = seg["start_ms"]
                    end_ms = all_segments[i+1]["start_ms"] if i < len(all_segments) - 1 else current_start_ms + 1500
                    if current_text.strip(): parsed_subs.append({"text": current_text.strip(), "index": len(parsed_subs), "start": current_start_ms/1000.0, "end": end_ms/1000.0})
                    current_text = ""; current_start_ms = -1
            return parsed_subs
        except Exception as e: 
            traceback.print_exc()
            return []

def translate_and_map(video_id, subtitles_list, headers, src_lang, target_lang):
    url = "https://yd.transduck.com/api/v2/translateAll"
    try:
        response = requests.post(url, params={'language': src_lang, 'to': target_lang, 'videoId': video_id, 'platform': 'pc'}, headers=headers, json=[item['text'] for item in subtitles_list], timeout=60)
        if response.status_code != 200: raise Exception("Lỗi API Dịch Transduck")
        translations = response.json().get("translations", [])
        for i, item in enumerate(subtitles_list):
            if i < len(translations): item['text'] = (translations[i].get("text", "") if isinstance(translations[i], dict) else str(translations[i])).strip()
        return subtitles_list
    except Exception as e: raise Exception(str(e))

def wait_for_audio_ready(generation_id, output_file, base_url):
    """
    Hàm Polling: Đợi server xử lý xong và tải file wav xuống đĩa.
    """
    # Thay đổi sang endpoint lấy audio trực tiếp
    download_url = f"{base_url}/audio/{generation_id}"
    print(f"\n⏳ [POLLING] Đang đợi tải ID: {generation_id}", end="", flush=True)
    
    start_time = time.time()
    # Thời gian đợi tối đa 1 phút mỗi file
    while True:
        if time.time() - start_time > 60:
            print(" ❌ Quá thời gian chờ (1 phút)!", flush=True)
            return False

        try:
            # Dùng stream=True để chỉ tải file nếu status_code = 200
            resp = requests.get(download_url, stream=True, timeout=10)
            
            if resp.status_code == 200:
                content_type = resp.headers.get("Content-Type", "").lower()
                
                # Xác nhận là file audio hoặc RIFF header
                if "audio" in content_type or resp.content.startswith(b'RIFF'):
                    with open(output_file, 'wb') as f:
                        f.write(resp.content)
                    print(f" ✅ Tải xong! ({os.path.getsize(output_file)} bytes)", flush=True)
                    return True
            
            print(".", end="", flush=True)
            time.sleep(2) 
            
        except Exception as e:
            print(f"\n⚠️ Lỗi mạng khi polling: {e}", flush=True)
            time.sleep(2)

def generate_local_dubbing(video_id, subs, output_folder, target_lang, model_id, profile_id, callback):
    total = len(subs)
    
    for i, item in enumerate(subs):
        idx = item['index'] + 1
        output_file = os.path.join(output_folder, f"audio_{idx:05d}.wav")
        
        # Bỏ qua nếu file đã tồn tại và đủ dung lượng
        if os.path.exists(output_file) and os.path.getsize(output_file) > 1024:
            continue

        if callback:
            callback(20 + int((i / total) * 30), f"Đang gen AI: {idx}/{total}")

        # BƯỚC 1: RA LỆNH GEN
        api_url = f"{BASE_URL}/generate"
        payload = {
            "text": item['text'],
            "model_id": model_id.strip(),
            "profile_id": profile_id.strip(),
            "language": target_lang
        }
        
        try:
            resp = requests.post(api_url, json=payload, timeout=30)
            if resp.status_code == 200:
                task_data = resp.json()
                generation_id = task_data.get("id")
                
                if generation_id:
                    # BƯỚC 2: POLLING TRỰC TIẾP
                    success = wait_for_audio_ready(generation_id, output_file, BASE_URL)
                    if not success:
                        print(f"⚠️ Câu {idx} không tải được audio.")
            else:
                print(f"❌ Server báo lỗi câu {idx}: {resp.status_code}")
        except Exception as e:
            print(f"❌ Lỗi kết nối gen câu {idx}: {e}")

    return True

# ==============================================================================
# [TẢI VIDEO GỐC BẰNG BAT FILE]
# ==============================================================================
def download_video(video_id, output_folder):
    for f in os.listdir(output_folder):
        if f.startswith("source_video") and f.endswith(('.mp4','.webm','.mkv')):
            file_path = os.path.join(output_folder, f)
            if os.path.getsize(file_path) > 1024 * 1024: 
                log_info("Video gốc đã tồn tại, bỏ qua tải mới.")
                return
            else:
                try: os.remove(file_path) 
                except: pass

    log_info(f"Đang gọi taiok.bat để tải video ID: {video_id}...")
    bat_file_path = os.path.abspath(os.path.join(CURRENT_DIR, "taiok.bat"))
    
    # Kiểm tra xem bat có nằm ở thư mục cha không
    if not os.path.exists(bat_file_path):
        bat_file_path = os.path.abspath(os.path.join(CURRENT_DIR, "..", "taiok.bat"))
        if not os.path.exists(bat_file_path):
             raise Exception(f"Không tìm thấy file bat tại: {bat_file_path}")

    list_txt_path = os.path.join(os.path.dirname(bat_file_path), "list.txt")
    downloads_dir = os.path.join(os.path.dirname(bat_file_path), "downloads")
    
    with open(list_txt_path, "w", encoding="utf-8") as f: 
        f.write(f"https://www.youtube.com/watch?v={video_id}\n")

    try:
        subprocess.run([bat_file_path], cwd=os.path.dirname(bat_file_path), shell=True, input=b'\r\n')
        with open(list_txt_path, "w", encoding="utf-8") as f: f.write("")

        downloaded_file = None
        for f in os.listdir(downloads_dir):
            if f"[{video_id}]" in f and f.endswith(('.mp4', '.mkv', '.webm')):
                downloaded_file = os.path.join(downloads_dir, f); break

        if not downloaded_file:
            raise Exception("taiok.bat chạy xong nhưng không tìm thấy file video.")

        ext = downloaded_file.split('.')[-1]
        final_target = os.path.join(output_folder, f"source_video.{ext}")
        shutil.move(downloaded_file, final_target)
        log_success("✅ Đã tải xong video gốc!")
    except Exception as e: raise Exception(f"Lỗi tải video (taiok.bat): {str(e)}")


# ==============================================================================
# [TÁCH NHẠC VÀ MIX AUDIO MP4]
# ==============================================================================
def separate_audio_demucs(video_path, output_folder):
    log_info("🎵 Đang bóc tách nhạc nền bằng Demucs...")
    temp_audio = os.path.join(output_folder, "temp_full_audio.mp3")
    subprocess.run([FFMPEG_LOCAL_PATH, "-y", "-i", video_path, "-q:a", "0", "-map", "a", temp_audio], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    cmd = ["python", "-m", "demucs", "-n", "htdemucs", "--two-stems=vocals", "-d", "cuda", "-o", output_folder, temp_audio]
    subprocess.run(cmd)
    
    demucs_out_dir = os.path.join(output_folder, "htdemucs", "temp_full_audio")
    return os.path.join(demucs_out_dir, "vocals.wav"), os.path.join(demucs_out_dir, "no_vocals.wav")

def smart_mix_video_moviepy(output_folder, bg_vol_pct, vocal_vol_pct, dubbing_vol_pct, video_id, burn_sub=False, progress_callback=None):
    if progress_callback: 
        progress_callback(55, "Đang xử lý Smart Mix Âm thanh...")
    
    video_path = next((os.path.join(output_folder, f) for f in os.listdir(output_folder) if f.startswith("source_video")), None)
    
    if not video_path: 
        raise Exception(f"Không tìm thấy video gốc (source_video) trong thư mục: {output_folder}")

    video_clip = None
    final_audio = None
    final_video = None
    bg_audio_clip = None
    vocal_audio_clip = None
    base_audio_clips = []
    dubbing_clips = []
    
    try:
        video_clip = VideoFileClip(video_path)
        
        try:
            vocals_path, no_vocals_path = separate_audio_demucs(video_path, output_folder)
            bg_audio_clip = AudioFileClip(no_vocals_path).volumex(bg_vol_pct / 100.0)
            vocal_audio_clip = AudioFileClip(vocals_path).volumex(vocal_vol_pct / 100.0)
            base_audio_clips = [bg_audio_clip, vocal_audio_clip]
        except Exception as e:
            log_warn(f"Demucs lỗi hoặc không khả dụng ({str(e)}), quay về dùng âm thanh gốc.")
            base_audio_clips = [video_clip.audio.volumex(bg_vol_pct / 100.0)]

        sub_json_path = os.path.join(output_folder, "final_subtitles.json")
        if not os.path.exists(sub_json_path):
            raise Exception("Thiếu file final_subtitles.json để thực hiện lồng tiếng.")

        with open(sub_json_path, 'r', encoding='utf-8') as f:
            subs = json.load(f)

        SYNC_OFFSET = 0.2
        for i, item in enumerate(subs):
            idx = item['index'] + 1
            
            # Ưu tiên stretch audio
            audio_file = os.path.join(output_folder, f"audio_{idx:05d}_stretched.wav")
            
            if not os.path.exists(audio_file):
                audio_file = os.path.join(output_folder, f"audio_{idx:05d}.wav")
            
            if os.path.exists(audio_file):
                try:
                    actual_start = float(item['start']) + SYNC_OFFSET
                    # Stretch audio time 
                    max_duration = (float(subs[i+1]['start']) - float(item['start'])) if i < len(subs)-1 else (video_clip.duration - actual_start)
                    
                    temp_clip = AudioFileClip(audio_file)
                    if temp_clip.duration > max_duration and max_duration > 0.5:
                         speed = min(temp_clip.duration / max_duration, 1.4)
                         audio_file = time_stretch_audio(audio_file, os.path.join(output_folder, f"audio_{idx:05d}_stretched.wav"), speed)
                    temp_clip.close()

                    dub_clip = (AudioFileClip(audio_file).set_start(actual_start).volumex(dubbing_vol_pct / 100.0))
                    dubbing_clips.append(dub_clip)
                except Exception as e:
                    pass

        if progress_callback: 
            progress_callback(70, "Bắt đầu Render Video MP4...")

        final_audio = CompositeAudioClip(base_audio_clips + dubbing_clips).set_duration(video_clip.duration)
        final_video = video_clip.set_audio(final_audio)
        final_output = os.path.join(output_folder, f"{video_id}.mp4")
        
        ffmpeg_params = ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-pix_fmt", "yuv420p"]
        
        if burn_sub:
            srt_path = os.path.join(output_folder, f"{video_id}.srt")
            if os.path.exists(srt_path):
                safe_srt_path = srt_path.replace('\\', '/').replace(':', '\\:')
                ffmpeg_params.extend(["-vf", f"subtitles='{safe_srt_path}'"])

        final_video.write_videofile(
            final_output, 
            codec="h264_nvenc", 
            audio_codec="aac", 
            temp_audiofile=os.path.join(output_folder, 'temp-audio.m4a'), 
            remove_temp=False, 
            ffmpeg_params=ffmpeg_params, 
            bitrate="30000k", 
            threads=4, 
            logger=MyBarLogger(progress_callback)
        )
        
        return final_output

    except Exception as e:
        log_error("Lỗi trong hàm smart_mix_video_moviepy:", e)
        raise e
        
    finally:
        log_info("🧹 Dọn dẹp bộ nhớ MoviePy...")
        if final_video: final_video.close()
        if final_audio: final_audio.close()
        if video_clip: video_clip.close()
        if bg_audio_clip: bg_audio_clip.close()
        if vocal_audio_clip: vocal_audio_clip.close()
        for clip in dubbing_clips:
            try: clip.close()
            except: pass

def run_process(url, web_cookie, bg_vol, vocal_vol, dub_vol, src, target, model_id, profile_id, create_sub, burn_sub, callback):
    try:
        web_cookie = web_cookie.strip().replace('\n','').replace('\r','') if web_cookie else ""
        model_id = model_id.strip() if model_id else "kokoro"
        profile_id = profile_id.strip() if profile_id else ""

        vid = extract_video_id(url)
        if not vid: raise Exception("Link YouTube không hợp lệ!")
        
        check_and_track_cookie(web_cookie, vid)
        folder = os.path.join(BASE_DATA_FOLDER, vid)
        
        if not os.path.exists(folder):
            os.makedirs(folder)
        
        callback(5, "Đang trích xuất phụ đề YouTube...")
        yt_headers = {'User-Agent': 'Mozilla/5.0'}
        yt = YouTubeProExtractor(yt_headers)
        subs = yt.get_subtitle_data(vid, folder, src)
        if not subs: raise Exception("Không tìm thấy phụ đề cho video này.")
        
        callback(10, "Đang dịch bằng Transduck...")
        transduck_headers = {
            'User-Agent': 'Mozilla/5.0', 
            'Cookie': web_cookie, 
            'Content-Type': 'application/json'
        }
        translated = translate_and_map(vid, subs, transduck_headers, src, target)
        
        with open(os.path.join(folder, "final_subtitles.json"), "w", encoding="utf-8") as f:
            json.dump(translated, f, ensure_ascii=False)
        
        if create_sub or burn_sub:
            generate_srt_file(translated, os.path.join(folder, f"{vid}.srt"))
        
        callback(20, "Đang khởi động RTX 3060 tạo Giọng Lồng Tiếng...")
        generate_local_dubbing(vid, translated, folder, target, model_id, profile_id, callback)
        
        callback(50, "Đang tải video gốc...")
        download_video(vid, folder)
        
        path = smart_mix_video_moviepy(folder, float(bg_vol), float(vocal_vol), float(dub_vol), vid, burn_sub, callback)
        
        callback(100, "Hoàn tất Render!")
        return {"status": "success", "file": path, "video_id": vid}
    except Exception as e: 
        log_error("LỖI QUY TRÌNH CHÍNH:", e)
        return {"status": "error", "msg": str(e)}