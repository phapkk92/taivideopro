
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import yt_dlp, os

app = FastAPI(title="taivideopro")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/info")
def get_info(url: str = Query(..., description="Video URL")):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'skip_download': True,
        'extractor_args': {
            'youtube': {'player_client': ['android']},
            'tiktok': {'api_hostname': 'api16-normal-c-useast5.tiktokv.com'}
        }
    }
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = "cookies.txt"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            fmts = []
            if info.get('url'):
                fmts.append({"label": f"{info.get('height') or 1080}p - BEST", "quality": info.get('height') or 1080, "url": info.get('url')})
            for f in (info.get('formats') or [])[::-1]:
                if f.get('vcodec') != 'none' and f.get('acodec') != 'none' and f.get('url') and f.get('height'):
                    fmts.append({"label": f"{f['height']}p - {f.get('ext','mp4').upper()}", "quality": f['height'], "url": f['url']})
                if len(fmts) > 8:
                    break
            seen=set()
            uniq=[]
            for x in fmts:
                if x['quality'] not in seen:
                    uniq.append(x); seen.add(x['quality'])
            uniq = sorted(uniq, key=lambda x: x['quality'], reverse=True)
            return {"platform": "video", "title": info.get('title'), "thumbnail": info.get('thumbnail'), "uploader": info.get('uploader') or info.get('channel'), "formats": uniq}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/")
def root():
    return FileResponse("index.html")
