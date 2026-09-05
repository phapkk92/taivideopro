
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import yt_dlp
import os

app = FastAPI(title="SnapDownload Pro API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def detect_platform(url: str):
    u = url.lower()
    if "tiktok.com" in u: return "tiktok"
    if "facebook.com" in u or "fb.watch" in u: return "facebook"
    if "instagram.com" in u: return "instagram"
    if "youtube.com" in u or "youtu.be" in u: return "youtube"
    if "twitter.com" in u or "x.com" in u: return "twitter"
    if "threads.net" in u: return "threads"
    return "unknown"

@app.get("/api/info")
def get_info(url: str = Query(..., description="Video URL")):
    platform = detect_platform(url)

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'skip_download': True,
        'extractor_args': {
            'tiktok': {'api_hostname': 'api16-normal-c-useast5.tiktokv.com'},
            'youtube': {'player_client': ['android']}
        }
    }
    # if cookies.txt exists, use it (for FB/IG)
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = "cookies.txt"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # build formats list
            formats = []
            # best combined
            if info.get('url'):
                formats.append({
                    "label": "Gốc - Tốt nhất",
                    "quality": info.get('height') or 1080,
                    "ext": info.get('ext', 'mp4'),
                    "url": info.get('url')
                })

            for f in info.get('formats', [])[::-1]:
                if f.get('vcodec') != 'none' and f.get('acodec') != 'none' and f.get('url'):
                    h = f.get('height') or 0
                    if h >= 360:
                        formats.append({
                            "label": f"{h}p - {f.get('ext','mp4').upper()}",
                            "quality": h,
                            "ext": f.get('ext','mp4'),
                            "url": f.get('url'),
                            "filesize": f.get('filesize')
                        })
                if len(formats) > 6:
                    break

            # deduplicate by quality
            seen = set()
            uniq = []
            for fm in formats:
                if fm['quality'] not in seen:
                    uniq.append(fm)
                    seen.add(fm['quality'])

            uniq = sorted(uniq, key=lambda x: x['quality'], reverse=True)

            return {
                "platform": platform,
                "title": info.get('title', 'Video'),
                "thumbnail": info.get('thumbnail'),
                "uploader": info.get('uploader') or info.get('channel'),
                "duration": info.get('duration'),
                "formats": uniq
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Serve frontend
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

@app.get("/")
def root():
    return FileResponse(os.path.join(frontend_path, "index.html"))
