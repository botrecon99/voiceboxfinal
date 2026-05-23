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
import wave

# ==============================================================================
# [CẤU HÌNH HỆ THỐNG & ĐIỀU KHIỂN KHẨN CẤP]
# ==============================================================================
API_PORT = 17493  # Cổng Backend đang chạy
BASE_URL = f"http://127.0.0.1:{API_PORT}"

# Cờ tín hiệu để điều khiển việc DỪNG tiến trình khẩn cấp
cancel_event = threading.Event()

# Lỗi tùy chỉnh để bẻ gãy các vòng lặp khi bấm Dừng
class ProcessCanceledException(Exception):
    pass

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
        # BẪY DỪNG KHẨN CẤP MOVIEPY
        if cancel_event.is_set():
            raise ProcessCanceledException("🛑 Tiến trình Render Video đã bị hủy bởi người dùng!")
            
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
        if cancel_event.is_set(): raise ProcessCanceledException("🛑 Đã hủy!")
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
    if cancel_event.is_set(): raise ProcessCanceledException("🛑 Đã hủy!")
    url = "https://yd.transduck.com/api/v2/translateAll"
    
    # 1. Chuẩn bị payload
    payload = [item['text'] for item in subtitles_list]
    
    # 2. Gọi API với log chi tiết
    try:
        response = requests.post(
            url, 
            params={'language': src_lang, 'to': target_lang, 'videoId': video_id, 'platform': 'pc'}, 
            headers=headers, 
            json=payload, 
            timeout=60
        )
        
        # LOG PHẢN HỒI THỰC TẾ ĐỂ XEM NÓ CÓ DỊCH KHÔNG
        log_info(f"🔍 [DEBUG] Response Text: {response.text[:200]}") 

        if response.status_code != 200:
            raise Exception(f"API Transduck báo lỗi: {response.status_code} - {response.text}")
            
        data = response.json()
        translations = data.get("translations", [])
        
        if not translations:
            log_error("⚠️ API trả về danh sách dịch rỗng!")
            return subtitles_list

        # Cập nhật văn bản
        for i, item in enumerate(subtitles_list):
            if i < len(translations):
                # Lưu ý: Transduck có thể trả về dict hoặc string
                new_val = translations[i]
                item['text'] = (new_val.get("text", "") if isinstance(new_val, dict) else str(new_val)).strip()
        
        return subtitles_list

    except Exception as e:
        log_error("❌ Lỗi nghiêm trọng tại translate_and_map:", str(e))
        raise Exception(f"Không thể dịch được: {str(e)}")

def wait_for_audio_ready(generation_id, output_file, base_url):
    download_url = f"{base_url}/audio/{generation_id}"
    print(f"\n⏳ [POLLING] Đang đợi tải ID: {generation_id}", end="", flush=True)
    
    start_time = time.time()
    while True:
        if cancel_event.is_set(): return False
        
        if time.time() - start_time > 10000:
            print(" ❌ Quá thời gian chờ (10000s)!", flush=True)
            return False

        try:
            resp = requests.get(download_url, stream=True, timeout=10)
            if resp.status_code == 200:
                content_type = resp.headers.get("Content-Type", "").lower()
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

def generate_local_dubbing(video_id, subs, output_folder, target_lang, model_id, profile_id, callback, num_threads=3):
    total = len(subs)
    completed_count = 0
    counter_lock = threading.Lock()

    def process_single_item(item):
        if cancel_event.is_set(): return # BẪY DỪNG KHẨN CẤP
        
        nonlocal completed_count
        idx = item['index'] + 1
        output_file = os.path.join(output_folder, f"audio_{idx:05d}.wav")
        
        if os.path.exists(output_file) and os.path.getsize(output_file) > 1024:
            with counter_lock:
                completed_count += 1
                if callback: callback(20 + int((completed_count / total) * 30), f"Đang gen AI: {completed_count}/{total}")
            return

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
                    success = wait_for_audio_ready(generation_id, output_file, BASE_URL)
                    if not success: print(f"\n⚠️ Câu {idx} gặp lỗi khi tải audio.")
            else:
                print(f"\n❌ Server báo lỗi câu {idx}: {resp.status_code}")
        except Exception as e:
            print(f"\n❌ Lỗi kết nối khi gen câu {idx}: {e}")
        finally:
            with counter_lock:
                completed_count += 1
                if callback: callback(20 + int((completed_count / total) * 30), f"Đang gen AI: {completed_count}/{total}")

    try: max_workers = int(num_threads)
    except: max_workers = 3

    log_info(f"🔥 Đang kích hoạt {max_workers} luồng xử lý song song để gen giọng AI...")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        executor.map(process_single_item, subs)

    if cancel_event.is_set(): raise ProcessCanceledException("🛑 Tiến trình gen AI đã bị hủy!")
    log_success("✅ Đã hoàn thành gen AI cho toàn bộ các câu!")
    return True


def download_video(video_id, output_folder):
    if cancel_event.is_set(): raise ProcessCanceledException("🛑 Đã hủy!")
    
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


def separate_audio_demucs(video_path, output_folder):
    log_info("🎵 Đang bóc tách nhạc nền bằng Demucs...")
    temp_audio = os.path.join(output_folder, "temp_full_audio.mp3")
    subprocess.run([FFMPEG_LOCAL_PATH, "-y", "-i", video_path, "-q:a", "0", "-map", "a", temp_audio], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    cmd = ["python", "-m", "demucs", "-n", "htdemucs", "--two-stems=vocals", "-d", "cuda", "-o", output_folder, temp_audio]
    subprocess.run(cmd)
    
    demucs_out_dir = os.path.join(output_folder, "htdemucs", "temp_full_audio")
    return os.path.join(demucs_out_dir, "vocals.wav"), os.path.join(demucs_out_dir, "no_vocals.wav")

def prepare_audio_segment(input_path, output_path, speed_factor):
    if speed_factor > 1.4: speed_factor = 1.4
    if speed_factor < 0.7: speed_factor = 0.7 
    
    try:
        subprocess.run([
            FFMPEG_LOCAL_PATH, '-y', '-i', input_path, 
            '-filter:a', f"atempo={speed_factor}", 
            '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', '-vn', output_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
            return output_path
    except Exception as e:
        pass
    return None

def smart_mix_video_moviepy(output_folder, bg_vol_pct, vocal_vol_pct, dubbing_vol_pct, video_id, burn_sub=False, progress_callback=None):
    if progress_callback: progress_callback(55, "Đang xử lý Smart Mix Âm thanh...")
    if cancel_event.is_set(): raise ProcessCanceledException("🛑 Đã hủy!")
    
    video_path = next((os.path.join(output_folder, f) for f in os.listdir(output_folder) if f.startswith("source_video")), None)
    if not video_path: raise Exception("Không tìm thấy video gốc.")

    video_clip = VideoFileClip(video_path)
    base_audio_clips = []
    
    try:
        vocals_path, no_vocals_path = separate_audio_demucs(video_path, output_folder)
        base_audio_clips.append(AudioFileClip(no_vocals_path).volumex(bg_vol_pct / 100.0))
        base_audio_clips.append(AudioFileClip(vocals_path).volumex(vocal_vol_pct / 100.0))
    except:
        base_audio_clips = [video_clip.audio.volumex(bg_vol_pct / 100.0)]

    with open(os.path.join(output_folder, "final_subtitles.json"), 'r', encoding='utf-8') as f:
        subs = json.load(f)

    if progress_callback: progress_callback(60, "Đang lắp ráp track lồng tiếng tổng...")
    master_dub_path = os.path.join(output_folder, "master_dubbing_track.wav")
    
    SAMPLE_RATE = 44100
    CHANNELS = 2
    SAMPWIDTH = 2
    BYTES_PER_SEC = SAMPLE_RATE * CHANNELS * SAMPWIDTH
    
    out_wav = wave.open(master_dub_path, 'wb')
    out_wav.setnchannels(CHANNELS)
    out_wav.setsampwidth(SAMPWIDTH)
    out_wav.setframerate(SAMPLE_RATE)
    
    current_bytes_written = 0
    SYNC_OFFSET = 0.8
    
    for i, item in enumerate(subs):
        if cancel_event.is_set(): raise ProcessCanceledException("🛑 Tiến trình Mix âm thanh đã bị hủy!")
        
        idx = item['index'] + 1
        
        audio_file = os.path.join(output_folder, f"audio_{idx:05d}.wav")
        if not os.path.exists(audio_file):
            audio_file = os.path.join(output_folder, f"audio_{idx:05d}.mp3")
            
        if os.path.exists(audio_file) and os.path.getsize(audio_file) > 100:
            actual_start = float(item['start']) + SYNC_OFFSET
            target_duration = float(item['end']) - float(item['start'])
            if target_duration < 0.5: target_duration = 0.5
            
            try:
                temp_audio = AudioFileClip(audio_file)
                current_duration = temp_audio.duration
                temp_audio.close()
            except: continue
                
            ratio = current_duration / target_duration
            speed_factor = max(0.7, min(1.4, ratio))
            
            ready_path = os.path.join(output_folder, f"ready_{idx:05d}.wav")
            prepared_file = prepare_audio_segment(audio_file, ready_path, speed_factor)
            
            if prepared_file:
                target_start_bytes = int(actual_start * BYTES_PER_SEC)
                target_start_bytes -= target_start_bytes % 4 
                
                if target_start_bytes > current_bytes_written:
                    silence_length = target_start_bytes - current_bytes_written
                    out_wav.writeframes(b'\x00' * silence_length)
                    current_bytes_written = target_start_bytes
                    
                try:
                    with wave.open(prepared_file, 'rb') as in_wav:
                        frames = in_wav.readframes(in_wav.getnframes())
                        max_allowed_bytes = int(target_duration * BYTES_PER_SEC)
                        max_allowed_bytes -= max_allowed_bytes % 4
                        
                        if len(frames) > max_allowed_bytes:
                            frames = frames[:max_allowed_bytes]
                            
                        out_wav.writeframes(frames)
                        current_bytes_written += len(frames)
                except:
                    pass
                    
    out_wav.close()
    
    if os.path.exists(master_dub_path) and os.path.getsize(master_dub_path) > 100:
        final_dub_clip = AudioFileClip(master_dub_path).volumex(dubbing_vol_pct / 100.0)
        base_audio_clips.append(final_dub_clip)

    if progress_callback: progress_callback(70, "Bắt đầu Render Video MP4...")

    final_audio = CompositeAudioClip(base_audio_clips).set_duration(video_clip.duration)
    final_video = video_clip.set_audio(final_audio)
    final_output = os.path.join(output_folder, f"{video_id}.mp4")
    
    ffmpeg_params = ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-pix_fmt", "yuv420p"]
    if burn_sub and os.path.exists(os.path.join(output_folder, f"{video_id}.srt")):
        srt_path_escaped = os.path.join(output_folder, f"{video_id}.srt").replace('\\', '/').replace(':', '\\:')
        ffmpeg_params.extend(["-vf", f"subtitles='{srt_path_escaped}':force_style='Fontname=Arial,FontSize=18,PrimaryColour=&HFFFFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=1,Shadow=0,Alignment=2,MarginV=25'"])

    final_video.write_videofile(
        final_output, codec="h264_nvenc", audio_codec="aac", 
        temp_audiofile=os.path.join(output_folder, 'temp-audio.m4a'), remove_temp=True, 
        ffmpeg_params=ffmpeg_params if burn_sub else ["-preset", "p7", "-tune", "hq", "-pix_fmt", "yuv420p"], 
        bitrate="30000k", threads=4, logger=MyBarLogger(progress_callback)
    )
    
    return final_output


# ==============================================================================
# [HÀM CHẠY CHÍNH (MAIN ENTRY POINT)]
# ==============================================================================
def run_process(url, web_cookie, bg_vol, vocal_vol, dub_vol, src, target, model_id, profile_id, create_sub, burn_sub, callback, num_threads=3):
    # LÀM SẠCH CỜ DỪNG TRƯỚC KHI BẮT ĐẦU CHUYẾN MỚI
    cancel_event.clear() 
    
    # --- LOG THÔNG TIN NHẬN TỪ PAYLOAD ---
    log_info(f"📥 [PAYLOAD RECEIVED] Source Lang: {src}, Target Lang: {target}, Model ID: {model_id}")
    
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
        
        callback(10, f"Đang dịch từ {src} sang {target} bằng Transduck...")
        transduck_headers = {
            'User-Agent': 'Mozilla/5.0', 
            'Cookie': web_cookie, 
            'Content-Type': 'application/json'
        }
        
        # Gọi hàm dịch
        translated = translate_and_map(vid, subs, transduck_headers, src, target)
        
        with open(os.path.join(folder, "final_subtitles.json"), "w", encoding="utf-8") as f:
            json.dump(translated, f, ensure_ascii=False)
        
        if create_sub or burn_sub:
            generate_srt_file(translated, os.path.join(folder, f"{vid}.srt"))
        
        callback(20, "Đang khởi động RTX 3060 tạo Giọng Lồng Tiếng...")
        generate_local_dubbing(vid, translated, folder, target, model_id, profile_id, callback, num_threads=num_threads)
        
        callback(50, "Đang tải video gốc...")
        download_video(vid, folder)
        
        path = smart_mix_video_moviepy(folder, float(bg_vol), float(vocal_vol), float(dub_vol), vid, burn_sub, callback)
        
        callback(100, "Hoàn tất Render!")
        return {"status": "success", "file": path, "video_id": vid}
        
    except ProcessCanceledException as e:
        log_warn(str(e))
        callback(0, "🛑 Đã hủy tiến trình!")
        return {"status": "canceled", "msg": str(e)}
        
    except Exception as e: 
        log_error("LỖI QUY TRÌNH CHÍNH:", e)
        return {"status": "error", "msg": str(e)}