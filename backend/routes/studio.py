from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse
import uuid
import os
import re

# Import core từ thư mục backend
from .. import core

router = APIRouter()

# --- CẤU HÌNH HỆ THỐNG ---
BACKEND_URL = "http://127.0.0.1:17493"
DATA_DIR = r"D:\voicebox\opensource\voicebox\downloaded_data"

tasks_db = {}

class StudioRequest(BaseModel):
    url: str
    cookie: str
    target_lang: str
    model_id: str
    profile_id: str
    bg_vol: int
    vocal_vol: int
    dub_vol: int
    create_sub: bool
    burn_sub: bool

import shutil

# --- HÀM HỖ TRỢ DỌN DẸP ---
def cleanup_files(video_id: str):
    """Xóa tất cả file tạm trong folder video_id, chỉ giữ lại mp4 và srt."""
    target_dir = os.path.join(DATA_DIR, video_id)
    
    if not os.path.exists(target_dir):
        return

    # Danh sách các file cần giữ lại (thành phẩm)
    keep_extensions = ('.mp4', '.srt')
    
    try:
        files_deleted = 0
        for filename in os.listdir(target_dir):
            # Nếu không phải file mp4 hoặc srt thì tiễn lên đường
            if not filename.lower().endswith(keep_extensions):
                file_path = os.path.join(target_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    files_deleted += 1
                elif os.path.is_dir(file_path):
                    shutil.rmtree(file_path)
        
        if files_deleted > 0:
            print(f"✅ Cleanup: Đã xóa {files_deleted} file rác trong folder {video_id}")
    except Exception as e:
        print(f"❌ Cleanup Error: Không thể dọn dẹp folder {video_id}: {e}")


# --- HÀM CHẠY NGẦM CHÍNH ---
def background_runner(task_id: str, req: StudioRequest):
    def update_progress(percent: int, msg: str):
        tasks_db[task_id]["percent"] = percent
        tasks_db[task_id]["status"] = msg

    try:
        tasks_db[task_id]["status"] = "Đang khởi tạo tiến trình..."
        
        # 1. Gọi Core xử lý render
        result = core.run_process(
            url=req.url, 
            web_cookie=req.cookie,
            bg_vol=req.bg_vol, 
            vocal_vol=req.vocal_vol, 
            dub_vol=req.dub_vol,
            src="en", 
            target=req.target_lang,
            model_id=req.model_id, 
            profile_id=req.profile_id,
            create_sub=req.create_sub, 
            burn_sub=req.burn_sub,
            callback=update_progress
        )

        # 2. Xử lý sau khi Render xong
        if result.get("status") == "success":
            vid = result.get("video_id")
            
            # --- THỰC HIỆN DỌN DẸP NGAY SAU KHI THÀNH CÔNG ---
            cleanup_files(vid)
            # -----------------------------------------------

            tasks_db[task_id].update({
                "percent": 100,
                "status": "Hoàn tất & Đã dọn dẹp bộ nhớ!",
                "video_id": vid,
                "video_url": f"{BACKEND_URL}/api/files/{vid}/{vid}.mp4",
                "sub_url": f"{BACKEND_URL}/api/files/{vid}/{vid}.srt" if (req.create_sub or req.burn_sub) else None
            })
        else:
            # Nếu core báo lỗi
            tasks_db[task_id].update({
                "percent": -1, 
                "status": f"Lỗi: {result.get('msg')}"
            })
            
    except Exception as e:
        # Nếu sập cả hệ thống
        tasks_db[task_id].update({
            "percent": -1, 
            "status": f"Lỗi hệ thống: {str(e)}"
        })

# --- API CHECK HÀNG CŨ ---
@router.get("/check-exists")
async def check_video_exists(url: str):
    video_id_match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    if not video_id_match:
        return {"exists": False}
    
    vid = video_id_match.group(1)
    file_path = os.path.join(DATA_DIR, vid, f"{vid}.mp4")
    
    if os.path.exists(file_path):
        return {
            "exists": True,
            "video_id": vid,
            "video_url": f"{BACKEND_URL}/api/files/{vid}/{vid}.mp4",
            "sub_url": f"{BACKEND_URL}/api/files/{vid}/{vid}.srt" if os.path.exists(os.path.join(DATA_DIR, vid, f"{vid}.srt")) else None
        }
    return {"exists": False}

@router.post("/process")
async def start_process(req: StudioRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    tasks_db[task_id] = {"percent": 0, "status": "Đang xếp hàng...", "video_url": None}
    background_tasks.add_task(background_runner, task_id, req)
    return {"task_id": task_id}

@router.get("/progress/{task_id}")
async def get_progress(task_id: str):
    return tasks_db.get(task_id, {"percent": -1, "status": "Not found"})

# --- API ÉP TẢI XUỐNG (FIX MỞ TAB MỚI) ---
@router.get("/download-file/{vid}")
async def download_file(vid: str, type: str = "mp4"):
    ext = "mp4" if type == "mp4" else "srt"
    full_path = os.path.join(DATA_DIR, vid, f"{vid}.{ext}")
    
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File không tồn tại")

    return FileResponse(
        path=full_path,
        filename=f"PN_Media_{vid}.{ext}",
        media_type='application/octet-stream' # Header ép tải xuống
    )
