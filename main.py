import os
import re
import sys
import glob
import time
import json
import shutil
import unicodedata
import urllib.parse
import urllib.request
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import yt_dlp

# Tự động tìm ffmpeg
def get_ffmpeg_path():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    local_ffmpeg = os.path.join(base_dir, "ffmpeg.exe")
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg
    parent_ffmpeg = os.path.join(os.path.dirname(base_dir), "ffmpeg.exe")
    if os.path.exists(parent_ffmpeg):
        return parent_ffmpeg

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return ffmpeg_in_path

    return None

FFMPEG_PATH = get_ffmpeg_path()
TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_downloads")
os.makedirs(TEMP_DIR, exist_ok=True)

app = FastAPI(title="SnapDownload Pro API", version="3.2.0")

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
    clean = re.sub(r'[\/*?:"<>|]', "", name)
    clean = clean.strip().replace("\n", " ").replace("\r", "")
    return clean[:80] if len(clean) > 80 else clean

def make_safe_content_disposition(title: str, ext: str) -> str:
    """Tạo header Content-Disposition chuẩn RFC 5987 hỗ trợ tiếng Việt mà không bị lỗi latin-1"""
    safe_title = sanitize_filename(title or "video")
    
    # Tạo tên ascii không dấu
    nfkd = unicodedata.normalize('NFKD', safe_title)
    no_accent = "".join([c for c in nfkd if not unicodedata.combining(c)])
    ascii_clean = re.sub(r'[^a-zA-Z0-9_\-\. ]', '', no_accent).strip()
    if not ascii_clean:
        ascii_clean = "download"
    ascii_filename = f"{ascii_clean}.{ext}"

    # Mã hóa UTF-8 cho tên file có dấu
    encoded_filename = urllib.parse.quote(f"{safe_title}.{ext}")
    return f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}'

def cleanup_file(path: str):
    """Xóa file tạm sau khi gửi xong"""
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"Error cleaning up file {path}: {e}")

def is_tiktok_url(url: str) -> bool:
    u = url.lower()
    return "tiktok.com" in u or "douyin.com" in u

def fetch_tiktok_tikwm(url: str):
    """Trích xuất video TikTok không logo qua TikWM API"""
    try:
        api_url = f"https://www.tikwm.com/api/?url={urllib.parse.quote(url)}"
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == 0:
                d = data.get("data", {})
                raw_title = d.get("title") or "Video TikTok không logo"
                clean_title = raw_title.replace("\n", " ").strip()
                author_name = d.get("author", {}).get("nickname") or d.get("author", {}).get("unique_id") or "@tiktok"
                thumbnail = d.get("cover") or ""
                duration_sec = d.get("duration") or 0
                duration_str = format_duration(duration_sec)
                
                play_url = d.get("hdplay") or d.get("play")
                music_url = d.get("music")
                size_mb = format_size(d.get("size")) or (f"{max(3, int(duration_sec * 0.25))} MB" if duration_sec else "Gốc")

                formats = []
                # 1. Video không logo chất lượng cao
                if play_url:
                    formats.append({
                        "quality": "HD Không logo (Watermark)",
                        "type": "MP4 Không logo",
                        "size": size_mb,
                        "format_id": "tiktok_hd",
                        "url": f"/api/download?url={urllib.parse.quote(url)}&direct_url={urllib.parse.quote(play_url)}&type=video&title={urllib.parse.quote(clean_title)}"
                    })
                # 2. Video SD nếu có
                if d.get("play") and d.get("hdplay") and d.get("play") != d.get("hdplay"):
                    formats.append({
                        "quality": "Tiêu chuẩn (SD Không logo)",
                        "type": "MP4 Không logo",
                        "size": "SD",
                        "format_id": "tiktok_sd",
                        "url": f"/api/download?url={urllib.parse.quote(url)}&direct_url={urllib.parse.quote(d.get('play'))}&type=video&title={urllib.parse.quote(clean_title)}"
                    })
                # 3. Âm thanh gốc MP3
                if music_url:
                    formats.append({
                        "quality": "Âm thanh gốc",
                        "type": "MP3 320kbps",
                        "size": f"{max(1, int(duration_sec * 0.04)):.1f} MB",
                        "format_id": "tiktok_audio",
                        "url": f"/api/download?url={urllib.parse.quote(url)}&direct_url={urllib.parse.quote(music_url)}&type=audio&title={urllib.parse.quote(clean_title)}"
                    })

                return {
                    "platform": "TikTok",
                    "title": clean_title,
                    "thumbnail": thumbnail,
                    "duration": duration_str,
                    "author": author_name,
                    "formats": formats
                }
    except Exception as e:
        print(f"TikWM fetch error: {e}")
    return None

def get_base_ydl_opts():
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'extractor_args': {
            'youtube': {'player_client': ['android', 'web']}
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

    # 1. Nếu là link TikTok/Douyin: dùng TikWM API chuyên dụng cực nhanh, không logo 100%
    if is_tiktok_url(clean_url):
        tiktok_res = fetch_tiktok_tikwm(clean_url)
        if tiktok_res and tiktok_res.get("formats"):
            return tiktok_res

    # 2. Xử lý qua yt-dlp cho mọi nền tảng khác
    ydl_opts = get_base_ydl_opts()
    ydl_opts['skip_download'] = True

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(clean_url, download=False)
            except Exception as first_err:
                if 'extractor_args' in ydl_opts:
                    del ydl_opts['extractor_args']
                with yt_dlp.YoutubeDL(ydl_opts) as ydl_retry:
                    info = ydl_retry.extract_info(clean_url, download=False)

            if not info:
                raise HTTPException(status_code=400, detail="Không tìm thấy thông tin video từ liên kết này!")

            if 'entries' in info and info['entries']:
                info = info['entries'][0]

            title = info.get('title') or "Video không tên"
            thumbnail = info.get('thumbnail') or ""
            duration_sec = info.get('duration') or 0
            duration_str = format_duration(duration_sec)
            author = info.get('uploader') or info.get('channel') or info.get('creator') or "@creator"
            platform = detect_platform_name(info.get('extractor'), clean_url)

            formats = info.get('formats') or []
            video_height = info.get('height') or 1080

            filesize = info.get('filesize') or info.get('filesize_approx')
            size_best = format_size(filesize) or (f"{max(5, int(duration_sec * 0.35))} MB" if duration_sec else "Gốc")

            results = []

            results.append({
                "quality": f"{video_height}p Full HD" if video_height >= 1080 else f"{video_height}p HD - Gốc",
                "type": "MP4 + âm thanh",
                "size": size_best,
                "format_id": "best",
                "url": f"/api/download?url={urllib.parse.quote(clean_url)}&format_id=best&type=video&title={urllib.parse.quote(title)}"
            })

            if video_height > 720:
                size_720 = format_size(int(filesize * 0.6)) if filesize else (f"{max(3, int(duration_sec * 0.2))} MB" if duration_sec else "720p")
                results.append({
                    "quality": "720p HD",
                    "type": "MP4 + âm thanh",
                    "size": size_720,
                    "format_id": "720",
                    "url": f"/api/download?url={urllib.parse.quote(clean_url)}&format_id=720&type=video&title={urllib.parse.quote(title)}"
                })

            if video_height > 480:
                size_480 = format_size(int(filesize * 0.35)) if filesize else (f"{max(2, int(duration_sec * 0.12))} MB" if duration_sec else "SD")
                results.append({
                    "quality": "480p Tiết kiệm",
                    "type": "MP4",
                    "size": size_480,
                    "format_id": "480",
                    "url": f"/api/download?url={urllib.parse.quote(clean_url)}&format_id=480&type=video&title={urllib.parse.quote(title)}"
                })

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
    direct_url: Optional[str] = Query(None, description="Direct URL nếu có"),
    format_id: str = Query("best", description="ID định dạng"),
    type: str = Query("video", description="video hoặc audio"),
    title: Optional[str] = Query(None, description="Tên video")
):
    clean_url = url.strip()
    safe_title = sanitize_filename(title or "video_download")
    timestamp = int(time.time() * 1000)

    # 1. Nếu có direct_url (như link TikTok không logo từ CDN)
    if direct_url:
        try:
            ext = "mp3" if type == "audio" or format_id == "tiktok_audio" else "mp4"
            out_filename = f"temp_{timestamp}.{ext}"
            out_filepath = os.path.join(TEMP_DIR, out_filename)

            req = urllib.request.Request(
                direct_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    "Referer": "https://www.tiktok.com/"
                }
            )
            with urllib.request.urlopen(req, timeout=40) as resp, open(out_filepath, 'wb') as out_f:
                shutil.copyfileobj(resp, out_f)

            if (type == "audio" or format_id == "tiktok_audio") and FFMPEG_PATH:
                mp3_filepath = os.path.join(TEMP_DIR, f"temp_{timestamp}_audio.mp3")
                try:
                    cmd = [FFMPEG_PATH, "-y", "-i", out_filepath, "-vn", "-b:a", "320k", mp3_filepath]
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if os.path.exists(mp3_filepath):
                        os.remove(out_filepath)
                        out_filepath = mp3_filepath
                except Exception:
                    pass

            background_tasks.add_task(cleanup_file, out_filepath)
            media_type = "audio/mpeg" if ext == "mp3" else "video/mp4"
            content_disposition = make_safe_content_disposition(safe_title, ext)

            return FileResponse(
                path=out_filepath,
                media_type=media_type,
                headers={
                    "Content-Disposition": content_disposition
                }
            )
        except Exception as e:
            print(f"Direct download failed, fallback to yt-dlp: {e}")

    # 2. Tải qua yt-dlp
    ext = "mp3" if type == "audio" or format_id == "mp3" else "mp4"
    out_filename = f"temp_{timestamp}.%(ext)s"

    ydl_opts = get_base_ydl_opts()
    ydl_opts['outtmpl'] = os.path.join(TEMP_DIR, out_filename)

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

        matched_files = glob.glob(os.path.join(TEMP_DIR, f"temp_{timestamp}.*"))
        if not matched_files:
            files = [os.path.join(TEMP_DIR, f) for f in os.listdir(TEMP_DIR)]
            if files:
                actual_file = max(files, key=os.path.getctime)
            else:
                raise Exception("Không thể tìm thấy file sau khi tải")
        else:
            actual_file = matched_files[0]

        actual_ext = os.path.splitext(actual_file)[1].lstrip(".")
        background_tasks.add_task(cleanup_file, actual_file)

        media_type = "audio/mpeg" if actual_ext == "mp3" else "video/mp4"
        content_disposition = make_safe_content_disposition(safe_title, actual_ext)

        return FileResponse(
            path=actual_file,
            media_type=media_type,
            headers={
                "Content-Disposition": content_disposition
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
    print("  🚀 SNAPDOWNLOAD PRO V3.2 - KHỞI CHẠY HỆ THỐNG")
    print(f"  FFmpeg: {'Đã sẵn sàng' if FFMPEG_PATH else 'Chưa tìm thấy'}")
    print("  Mở trình duyệt: http://localhost:8000")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000)
