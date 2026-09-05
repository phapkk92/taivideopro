import os
import re
import sys
import glob
import time
import shutil
import urllib.parse
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import yt_dlp

# Tự động tìm ffmpeg
def get_ffmpeg_path():
    # 1. Kiểm tra file ffmpeg.exe trong cùng thư mục
    base_dir = os.path.dirname(os.path.abspath(__file__))
    local_ffmpeg = os.path.join(base_dir, "ffmpeg.exe")
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg
    parent_ffmpeg = os.path.join(os.path.dirname(base_dir), "ffmpeg.exe")
    if os.path.exists(parent_ffmpeg):
        return parent_ffmpeg

    # 2. Kiểm tra imageio_ffmpeg nếu có
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

    # 3. Kiểm tra PATH hệ thống
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return ffmpeg_in_path

    return None

FFMPEG_PATH = get_ffmpeg_path()
TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_downloads")
os.makedirs(TEMP_DIR, exist_ok=True)

app = FastAPI(title="SnapDownload Pro API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def format_duration(seconds):
    if not seconds or seconds <= 0:
        return "HD"
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def format_size(bytes_val):
    if not bytes_val or bytes_val <= 0:
        return None
    mb = bytes_val / (1024 * 1024)
    if mb >= 1000:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.1f} MB"

def sanitize_filename(name):
    # Loại bỏ ký tự cấm trong tên file Windows
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = clean.strip().replace("\n", " ").replace("\r", "")
    return clean[:100] if len(clean) > 100 else clean

def cleanup_file(path: str):
    """Xóa file tạm sau khi gửi xong"""
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"Error cleaning up file {path}: {e}")

def get_base_ydl_opts():
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'extractor_args': {
            'youtube': {'player_client': ['android', 'web']},
            'tiktok': {'api_hostname': 'api16-normal-c-useast5.tiktokv.com'}
        }
    }
    if FFMPEG_PATH:
        opts['ffmpeg_location'] = FFMPEG_PATH

    cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
    if os.path.exists(cookie_path):
        opts['cookiefile'] = cookie_path

    return opts

def detect_platform_name(extractor: str, url: str) -> str:
    extractor = (extractor or "").lower()
    url_l = (url or "").lower()
    if "tiktok" in extractor or "tiktok" in url_l:
        return "TikTok"
    elif "youtube" in extractor or "youtu" in url_l:
        return "YouTube"
    elif "facebook" in extractor or "fb" in url_l:
        return "Facebook"
    elif "instagram" in extractor or "instagr" in url_l:
        return "Instagram"
    elif "twitter" in extractor or "x.com" in url_l:
        return "Twitter"
    elif "douyin" in extractor or "douyin" in url_l:
        return "Douyin"
    elif "threads" in extractor or "threads.net" in url_l:
        return "Threads"
    elif "pinterest" in extractor or "pin.it" in url_l:
        return "Pinterest"
    return extractor.capitalize() if extractor else "Video"

@app.get("/api/info")
def get_info(url: str = Query(..., description="Video URL từ bất kỳ nền tảng nào")):
    clean_url = url.strip()
    if not clean_url:
        raise HTTPException(status_code=400, detail="Vui lòng dán liên kết video hợp lệ!")

    ydl_opts = get_base_ydl_opts()
    ydl_opts['skip_download'] = True

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(clean_url, download=False)
            except Exception as first_err:
                # Fallback với extractor mặc định
                if 'extractor_args' in ydl_opts:
                    del ydl_opts['extractor_args']
                with yt_dlp.YoutubeDL(ydl_opts) as ydl_retry:
                    info = ydl_retry.extract_info(clean_url, download=False)

            if not info:
                raise HTTPException(status_code=400, detail="Không tìm thấy thông tin video!")

            # Nếu là playlist, lấy video đầu tiên
            if 'entries' in info and info['entries']:
                info = info['entries'][0]

            title = info.get('title') or "Video không tên"
            thumbnail = info.get('thumbnail') or ""
            duration_sec = info.get('duration') or 0
            duration_str = format_duration(duration_sec)
            author = info.get('uploader') or info.get('channel') or info.get('creator') or "@creator"
            platform = detect_platform_name(info.get('extractor'), clean_url)

            # Phân tích các format chất lượng
            formats = info.get('formats') or []
            video_height = info.get('height') or 1080

            # Ước lượng dung lượng
            filesize = info.get('filesize') or info.get('filesize_approx')
            size_best = format_size(filesize) or (f"{max(5, int(duration_sec * 0.35))} MB" if duration_sec else "Gốc")

            results = []

            # 1. Định dạng Tốt nhất (1080p hoặc chất lượng gốc cao nhất)
            results.append({
                "quality": f"{video_height}p Full HD" if video_height >= 1080 else f"{video_height}p HD - Gốc",
                "type": "MP4 + âm thanh",
                "size": size_best,
                "format_id": "best",
                "url": f"/api/download?url={urllib.parse.quote(clean_url)}&format_id=best&type=video&title={urllib.parse.quote(title)}"
            })

            # 2. Định dạng 720p HD (nếu video gốc >= 720p)
            if video_height > 720:
                size_720 = format_size(int(filesize * 0.6)) if filesize else (f"{max(3, int(duration_sec * 0.2))} MB" if duration_sec else "720p")
                results.append({
                    "quality": "720p HD",
                    "type": "MP4 + âm thanh",
                    "size": size_720,
                    "format_id": "720",
                    "url": f"/api/download?url={urllib.parse.quote(clean_url)}&format_id=720&type=video&title={urllib.parse.quote(title)}"
                })

            # 3. Định dạng Tiết kiệm 480p / 360p
            if video_height > 480:
                size_480 = format_size(int(filesize * 0.35)) if filesize else (f"{max(2, int(duration_sec * 0.12))} MB" if duration_sec else "SD")
                results.append({
                    "quality": "480p Tiết kiệm",
                    "type": "MP4",
                    "size": size_480,
                    "format_id": "480",
                    "url": f"/api/download?url={urllib.parse.quote(clean_url)}&format_id=480&type=video&title={urllib.parse.quote(title)}"
                })

            # 4. Định dạng Âm thanh MP3
            audio_size = (f"{max(1, int(duration_sec * 0.04)):.1f} MB" if duration_sec else "Âm thanh")
            results.append({
                "quality": "Âm thanh gốc",
                "type": "MP3 320kbps",
                "size": audio_size,
                "format_id": "mp3",
                "url": f"/api/download?url={urllib.parse.quote(clean_url)}&format_id=mp3&type=audio&title={urllib.parse.quote(title)}"
            })

            return {
                "platform": platform,
                "title": title,
                "thumbnail": thumbnail,
                "duration": duration_str,
                "author": author,
                "formats": results
            }

    except Exception as e:
        err_msg = str(e)
        if "Private video" in err_msg or "login" in err_msg.lower():
            detail = "Video này ở chế độ riêng tư hoặc yêu cầu đăng nhập."
        elif "Unsupported URL" in err_msg:
            detail = "Đường dẫn không hợp lệ hoặc nền tảng này chưa được hỗ trợ."
        else:
            detail = f"Lỗi lấy thông tin video: {err_msg[:120]}"
        raise HTTPException(status_code=400, detail=detail)

@app.get("/api/download")
def download_video(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="Video URL"),
    format_id: str = Query("best", description="ID định dạng hoặc chất lượng"),
    type: str = Query("video", description="video hoặc audio"),
    title: Optional[str] = Query(None, description="Tên video")
):
    clean_url = url.strip()
    safe_title = sanitize_filename(title or "video_download")
    timestamp = int(time.time() * 1000)

    # Đặt template xuất file
    ext = "mp3" if type == "audio" or format_id == "mp3" else "mp4"
    out_filename = f"{safe_title}_{timestamp}.{ext}"
    out_filepath = os.path.join(TEMP_DIR, out_filename)

    ydl_opts = get_base_ydl_opts()
    ydl_opts['outtmpl'] = os.path.join(TEMP_DIR, f"{safe_title}_{timestamp}.%(ext)s")

    if type == "audio" or format_id == "mp3":
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }]
    elif format_id == "720":
        ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
        ydl_opts['merge_output_format'] = 'mp4'
    elif format_id == "480":
        ydl_opts['format'] = 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'
        ydl_opts['merge_output_format'] = 'mp4'
    else: # best / 1080p
        ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best'
        ydl_opts['merge_output_format'] = 'mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([clean_url])

        # Tìm file thực tế đã được tải
        matched_files = glob.glob(os.path.join(TEMP_DIR, f"{safe_title}_{timestamp}.*"))
        if not matched_files:
            # Tìm file mới nhất trong thư mục temp
            files = [os.path.join(TEMP_DIR, f) for f in os.listdir(TEMP_DIR)]
            if files:
                actual_file = max(files, key=os.path.getctime)
            else:
                raise Exception("Không thể tìm thấy file sau khi tải")
        else:
            actual_file = matched_files[0]

        actual_ext = os.path.splitext(actual_file)[1].lstrip(".")
        download_filename = f"{safe_title}.{actual_ext}"

        # Đăng ký xóa file tạm sau khi gửi
        background_tasks.add_task(cleanup_file, actual_file)

        media_type = "audio/mpeg" if actual_ext == "mp3" else "video/mp4"
        return FileResponse(
            path=actual_file,
            filename=download_filename,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{download_filename}"'
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể tải video: {str(e)}")

@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "ffmpeg": bool(FFMPEG_PATH),
        "ffmpeg_path": FFMPEG_PATH,
        "yt_dlp_version": yt_dlp.version.__version__
    }

@app.get("/")
def root():
    index_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    return FileResponse(index_file)

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  🚀 SNAPDOWNLOAD PRO V3 - KHỞI CHẠY HỆ THỐNG")
    print(f"  FFmpeg: {'Đã sẵn sàng' if FFMPEG_PATH else 'Chưa tìm thấy'}")
    print("  Mở trình duyệt: http://localhost:8000")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000)
