import os
import sys
import re
import json
import time
import shutil
import asyncio
import gc
import uuid
import urllib.parse
import urllib.request
from typing import Optional
from contextlib import asynccontextmanager

import httpx
from starlette.background import BackgroundTask
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
import yt_dlp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp_downloads")
os.makedirs(TEMP_DIR, exist_ok=True)

# Limit concurrent heavy yt-dlp & ffmpeg processes to prevent 512MB RAM OOM crash
YTDLP_SEMAPHORE = asyncio.Semaphore(2)

# Global persistent AsyncClient with optimized connection pool for low-memory environments
http_client: Optional[httpx.AsyncClient] = None

def cleanup_temp_file(file_path: str):
    """Safely remove a temporary file to keep disk usage at 0."""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass

async def periodic_temp_cleanup():
    """Periodically purge orphaned temporary files older than 5 minutes."""
    while True:
        try:
            await asyncio.sleep(600)  # Every 10 minutes
            now = time.time()
            if os.path.exists(TEMP_DIR):
                for fname in os.listdir(TEMP_DIR):
                    p = os.path.join(TEMP_DIR, fname)
                    if os.path.isfile(p):
                        try:
                            if now - os.path.getmtime(p) > 300:
                                os.remove(p)
                        except Exception:
                            pass
            gc.collect()
        except asyncio.CancelledError:
            break
        except Exception:
            pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    # Optimized limits for Render 512MB RAM:
    # 20 keep-alive connections max, 50 total connections
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=30.0)
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
    http_client = httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=True)
    cleanup_task = asyncio.create_task(periodic_temp_cleanup())
    yield
    cleanup_task.cancel()
    if http_client:
        await http_client.aclose()

async def get_http_client() -> httpx.AsyncClient:
    global http_client
    if http_client is None or http_client.is_closed:
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=30.0)
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
        http_client = httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=True)
    return http_client

app = FastAPI(title="TaiVideoPro API", version="2.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Length", "Accept-Ranges"]
)

FFMPEG_PATH = None
local_ffmpeg = os.path.join(BASE_DIR, "ffmpeg.exe")
if os.path.exists(local_ffmpeg):
    FFMPEG_PATH = local_ffmpeg
elif shutil.which("ffmpeg"):
    FFMPEG_PATH = shutil.which("ffmpeg")
else:
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass


def format_size(bytes_val):
    if not bytes_val or bytes_val <= 0:
        return ""
    try:
        bytes_val = float(bytes_val)
        if bytes_val >= 1024 * 1024 * 1024:
            return f"{bytes_val / (1024 * 1024 * 1024):.1f} GB"
        elif bytes_val >= 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.1f} MB"
        elif bytes_val >= 1024:
            return f"{bytes_val / 1024:.1f} KB"
    except Exception:
        pass
    return ""

def format_duration(seconds):
    if not seconds:
        return "N/A"
    try:
        s = int(seconds)
        m, sec = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"
    except Exception:
        return "N/A"

def clean_filename(s: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", s).strip()
    return cleaned if cleaned else "video"

# --- 1. TIKTOK & DOUYIN HANDLER ---
import http.cookiejar

def fetch_douyin_savetik(target_url: str):
    try:
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        home_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        req_home = urllib.request.Request("https://savetik.co/en", headers=home_headers)
        try:
            opener.open(req_home, timeout=6)
        except Exception:
            pass

        ajax_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://savetik.co/en",
            "Origin": "https://savetik.co"
        }
        post_data = urllib.parse.urlencode({"q": target_url, "lang": "en"}).encode("utf-8")
        req_ajax = urllib.request.Request("https://savetik.co/api/ajaxSearch", data=post_data, headers=ajax_headers)
        with opener.open(req_ajax, timeout=12) as resp:
            res_json = json.loads(resp.read().decode("utf-8", errors="ignore"))
            html = res_json.get("data", "")
            if not html:
                return None

        # Extract title
        title_m = re.search(r'<h3>(.*?)</h3>', html, re.DOTALL)
        clean_title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else "Douyin Video"
        clean_title = clean_title[:100]

        # Extract duration
        dur_m = re.search(r'<p>([0-9]+:[0-9]+(?::[0-9]+)?)</p>', html)
        duration_str = dur_m.group(1) if dur_m else "N/A"

        # Extract thumbnail
        thumb_m = re.search(r'<div class="thumbnail"[^>]*>.*?<img[^>]*src=["\']([^"\']+)["\']', html, re.DOTALL)
        if not thumb_m:
            thumb_m = re.search(r'<img[^>]*src=["\']([^"\']+)["\']', html)
        raw_thumb = thumb_m.group(1).replace("&amp;", "&") if thumb_m else ""

        formats = []
        a_tags = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.DOTALL)
        seen_urls = set()

        for href, inner in a_tags:
            clean_label = re.sub(r'<[^>]+>', '', inner).strip()
            clean_href = href.replace("&amp;", "&")
            if not clean_href.startswith("http") or clean_href in seen_urls:
                continue
            if "tiktokio" in clean_href or clean_href == "/":
                continue
            seen_urls.add(clean_href)

            if "HD" in clean_label:
                formats.append({
                    "quality": "Full HD Không logo (Watermark)",
                    "type": "MP4 Không logo",
                    "size": "HD",
                    "format_id": "douyin_hd",
                    "downloadUrl": clean_href,
                    "url": clean_href,
                    "direct_url": clean_href
                })
            elif "MP4" in clean_label:
                formats.append({
                    "quality": "Tiêu chuẩn (SD Không logo)",
                    "type": "MP4 Không logo",
                    "size": "SD",
                    "format_id": "douyin_sd",
                    "downloadUrl": clean_href,
                    "url": clean_href,
                    "direct_url": clean_href
                })
            elif "MP3" in clean_label or "Audio" in clean_label:
                formats.append({
                    "quality": "Âm thanh gốc (MP3)",
                    "type": "MP3 320kbps",
                    "size": "Audio",
                    "format_id": "douyin_audio",
                    "downloadUrl": clean_href,
                    "url": clean_href,
                    "direct_url": clean_href
                })

        # Check photo slideshow
        photo_tags = re.findall(r'<div class="photo-item"[^>]*>.*?<a[^>]*href=["\']([^"\']+)["\']', html, re.DOTALL)
        for idx, p_href in enumerate(photo_tags):
            p_clean = p_href.replace("&amp;", "&")
            formats.append({
                "quality": f"Ảnh {idx + 1}",
                "type": "Hình ảnh HD",
                "size": "HD",
                "format_id": f"douyin_img_{idx + 1}",
                "downloadUrl": p_clean,
                "url": p_clean,
                "direct_url": p_clean
            })

        if formats:
            return {
                "platform": "Douyin",
                "title": clean_title,
                "thumbnail": f"/api/proxy_image?url={urllib.parse.quote(raw_thumb)}" if raw_thumb else "",
                "duration": duration_str,
                "author": "Douyin Creator",
                "formats": formats
            }
    except Exception as e:
        print(f"Douyin SaveTik error: {e}")
    return None

def fetch_tiktok_douyin(url: str):
    # Extract clean URL from copied share text (handles Chinese Douyin share texts)
    url_m = re.search(r'https?://[^\s<>"\']+', url)
    clean_target = url_m.group(0) if url_m else url.strip()
    is_douyin = "douyin.com" in clean_target or "iesdouyin.com" in clean_target
    plat_name = "Douyin" if is_douyin else "TikTok"
    
    # If Douyin short link v.douyin.com, follow redirect to canonical URL
    if "v.douyin.com" in clean_target:
        try:
            req_head = urllib.request.Request(clean_target, headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
            })
            with urllib.request.urlopen(req_head, timeout=8) as r_head:
                redirected = r_head.geturl()
                if redirected and "douyin.com" in redirected and redirected != "https://www.douyin.com/":
                    clean_target = redirected
        except Exception as ex_redir:
            print(f"Douyin redirect resolution notice: {ex_redir}")

    # If Douyin, try SaveTik engine first
    if is_douyin:
        res_dy = fetch_douyin_savetik(clean_target)
        if res_dy:
            return res_dy

    # TikTok / Douyin via TikWM
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    
    try:
        data = None
        tikwm_endpoint = "https://www.tikwm.com/api/"
        req = urllib.request.Request(
            tikwm_endpoint,
            data=urllib.parse.urlencode({"url": clean_target, "hd": 1}).encode("utf-8"),
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            res_json = json.loads(response.read().decode("utf-8", errors="ignore"))
            if res_json.get("code") == 0 and res_json.get("data"):
                data = res_json["data"]

        if not data:
            get_url = f"https://www.tikwm.com/api/?url={urllib.parse.quote(clean_target)}&hd=1"
            req = urllib.request.Request(get_url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as response:
                res_json = json.loads(response.read().decode("utf-8", errors="ignore"))
                if res_json.get("code") == 0 and res_json.get("data"):
                    data = res_json["data"]

        if data:
            d = data
            clean_title = (d.get("title") or f"{plat_name} Video").strip()[:100]
            author_info = d.get("author") or {}
            author_name = author_info.get("nickname") or author_info.get("unique_id") or "Creator"
            duration_sec = d.get("duration", 0)
            duration_str = format_duration(duration_sec)

            def make_absolute_url(u):
                if not u:
                    return None
                if u.startswith("//"):
                    return "https:" + u
                if u.startswith("/"):
                    return "https://www.tikwm.com" + u
                return u

            raw_cover = d.get("origin_cover") or d.get("cover") or d.get("ai_dynamic_cover")
            thumbnail = make_absolute_url(raw_cover)
            
            play_hd = make_absolute_url(d.get("hdplay"))
            play_sd = make_absolute_url(d.get("play")) or make_absolute_url(d.get("wmplay"))
            play_url = play_hd or play_sd
            music_url = make_absolute_url(d.get("music"))
            size_mb = format_size(d.get("size")) or (f"{max(3, int(duration_sec * 0.25))} MB" if duration_sec else "Gốc")

            formats = []
            if play_url:
                formats.append({
                    "quality": "HD Không logo (Watermark)",
                    "type": "MP4 Không logo",
                    "size": size_mb,
                    "format_id": "tiktok_hd",
                    "downloadUrl": play_url,
                    "url": play_url,
                    "direct_url": play_url
                })
            if play_sd and play_hd and play_sd != play_hd:
                formats.append({
                    "quality": "Tiêu chuẩn (SD Không logo)",
                    "type": "MP4 Không logo",
                    "size": "SD",
                    "format_id": "tiktok_sd",
                    "downloadUrl": play_sd,
                    "url": play_sd,
                    "direct_url": play_sd
                })

            images = d.get("images")
            if images and isinstance(images, list):
                for idx, img in enumerate(images):
                    img_url = make_absolute_url(img)
                    formats.append({
                        "quality": f"Ảnh {idx + 1}",
                        "type": "Hình ảnh HD",
                        "size": "HD",
                        "format_id": f"tiktok_img_{idx + 1}",
                        "downloadUrl": img_url,
                        "url": img_url,
                        "direct_url": img_url
                    })

            if music_url:
                formats.append({
                    "quality": "Âm thanh gốc",
                    "type": "MP3 320kbps",
                    "size": f"{max(1, int(duration_sec * 0.04)):.1f} MB",
                    "format_id": "tiktok_audio",
                    "downloadUrl": music_url,
                    "url": music_url,
                    "direct_url": music_url
                })

            return {
                "platform": plat_name,
                "title": clean_title,
                "thumbnail": f"/api/proxy_image?url={urllib.parse.quote(thumbnail)}" if thumbnail else "",
                "duration": duration_str,
                "author": author_name,
                "formats": formats
            }
    except Exception as e:
        print(f"TikTok/Douyin TikWM error: {e}")

    # Fallback to SaveTik for TikTok if TikWM failed
    res_fallback = fetch_douyin_savetik(clean_target)
    if res_fallback:
        res_fallback["platform"] = plat_name
        return res_fallback

    return None
# --- 2. INSTAGRAM HANDLER (EMBED CAPTIONED) ---
def fetch_instagram(url: str):
    m = re.search(r'instagram\.com/(?:reel|p|tv)/([A-Za-z0-9_-]+)', url)
    if not m:
        return None
    shortcode = m.group(1)
    embed_url = f"https://www.instagram.com/reel/{shortcode}/embed/captioned/"
    req = urllib.request.Request(embed_url, headers={
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        
        mp4s = re.findall(r'https?:[\\/]+[^"\'\s<>]+\.mp4[^"\'\s<>]*', html)
        if not mp4s:
            return None
        video_url = mp4s[0].replace(r"\/", "/").replace("&amp;", "&")
        
        thumb = ""
        img_match = re.search(r'<img[^>]*class="[^"]*EmbeddedMediaImage[^"]*"[^>]*>', html)
        if img_match:
            src_m = re.search(r'src="([^"]+)"', img_match.group(0))
            if src_m:
                thumb = src_m.group(1).replace("&amp;", "&")
        if not thumb:
            imgs = re.findall(r'https?:[\\/]+[^"\'\s<>]+\.(?:jpg|jpeg|webp)[^"\'\s<>]*', html)
            for im in imgs:
                clean_im = im.replace(r"\/", "/").replace("&amp;", "&")
                if "fbcdn" in clean_im or "scontent" in clean_im:
                    thumb = clean_im
                    break
        
        title = f"Instagram Video {shortcode}"
        cap = re.search(r'class="Caption"[^>]*>(.*?)</div>', html)
        if cap:
            clean_cap = re.sub(r'<[^>]+>', '', cap.group(1)).strip()
            if clean_cap:
                title = clean_cap[:70]
        
        author = "@instagram"
        user = re.search(r'class="UsernameText"[^>]*>(.*?)</span>', html)
        if user:
            author = "@" + re.sub(r'<[^>]+>', '', user.group(1)).strip()
        
        formats = [
            {
                "quality": "HD Gốc (Instagram)",
                "type": "MP4 Video",
                "size": "HD",
                "format_id": "ig_hd",
                "downloadUrl": video_url,
                "url": video_url,
                "direct_url": video_url
            },
            {
                "quality": "Âm thanh gốc",
                "type": "MP3 320kbps",
                "size": "MP3",
                "format_id": "ig_audio",
                "downloadUrl": video_url,
                "url": video_url,
                "direct_url": video_url
            }
        ]
        return {
            "platform": "Instagram",
            "title": title,
            "author": author,
            "thumbnail": thumb or "",
            "duration": "N/A",
            "formats": formats
        }
    except Exception as e:
        print(f"Instagram error: {e}")
    return None

# --- 3. TWITTER / X HANDLER (FXTWITTER API) ---
def fetch_twitter(url: str):
    m = re.search(r'(?:twitter\.com|x\.com)/(?:[^/]+)/status/(\d+)', url)
    if not m:
        return None
    tweet_id = m.group(1)
    api_url = f"https://api.fxtwitter.com/i/status/{tweet_id}"
    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        
        tweet = data.get("tweet")
        if not tweet:
            return None
        
        media = tweet.get("media") or {}
        videos = media.get("videos") or []
        if not videos and tweet.get("video"):
            videos = [tweet.get("video")]
        
        if not videos:
            return None
        
        vid = videos[0]
        video_url = vid.get("url")
        thumb = vid.get("thumbnail_url")
        title = (tweet.get("text") or f"X Video {tweet_id}").strip()[:80]
        author = tweet.get("author", {}).get("name") or ("@" + tweet.get("author", {}).get("screen_name", "x"))
        duration = format_duration(vid.get("duration", 0))

        formats = [
            {
                "quality": "HD Gốc (Twitter/X)",
                "type": "MP4 Video",
                "size": "HD",
                "format_id": "twitter_hd",
                "downloadUrl": video_url,
                "url": video_url,
                "direct_url": video_url
            },
            {
                "quality": "Âm thanh",
                "type": "MP3 320kbps",
                "size": "MP3",
                "format_id": "twitter_audio",
                "downloadUrl": video_url,
                "url": video_url,
                "direct_url": video_url
            }
        ]
        return {
            "platform": "Twitter",
            "title": title,
            "author": author,
            "thumbnail": thumb or "",
            "duration": duration,
            "formats": formats
        }
    except Exception as e:
        print(f"Twitter error: {e}")
    return None

# --- 4. META AI HANDLER (BYPASS CLIENT CHALLENGE VIA FACEBOOKEXTERNALHIT) ---
def fetch_meta_ai_share(url: str):
    if "meta.ai" not in url:
        return None
    try:
        clean_url = url.strip()
        req = urllib.request.Request(
            clean_url,
            headers={
                "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9"
            }
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            html = response.read().decode("utf-8", errors="ignore")

        title = "Meta AI Media"
        m_title = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', html, re.I) or \
                  re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
        if m_title:
            t = m_title.group(1).strip()
            if len(t) > 2:
                title = t.replace("Meta AI - ", "").replace(" - Meta AI", "").strip()

        v_url = None
        m_vid = re.search(r'<meta\s+property=["\']og:video(?::url)?["\']\s+content=["\']([^"\']+)["\']', html, re.I)
        if m_vid:
            v_url = m_vid.group(1).replace("&amp;", "&")
        else:
            mp4s = re.findall(r'https?:[\\/]+[^"\'\s<>]+\.mp4[^"\'\s<>]*', html)
            if mp4s:
                v_url = mp4s[0].replace(r"\/", "/").replace("&amp;", "&")

        thumb = None
        m_img = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html, re.I) or \
                re.search(r'<meta\s+name=["\']twitter:image["\']\s+content=["\']([^"\']+)["\']', html, re.I)
        if m_img:
            thumb = m_img.group(1).replace("&amp;", "&")
        else:
            imgs = re.findall(r'https?:[\\/]+[^"\'\s<>]+\.(?:jpg|jpeg|png|webp)[^"\'\s<>]*', html)
            for im in imgs:
                clean_im = im.replace(r"\/", "/").replace("&amp;", "&")
                if "fbcdn" in clean_im or "scontent" in clean_im:
                    thumb = clean_im
                    break

        formats = []
        if v_url:
            formats.append({
                "quality": "HD Gốc (Meta AI Video)",
                "type": "MP4 Video",
                "size": "HD",
                "format_id": "meta_video",
                "downloadUrl": v_url,
                "url": v_url,
                "direct_url": v_url
            })
            formats.append({
                "quality": "Âm thanh gốc",
                "type": "MP3",
                "size": "MP3",
                "format_id": "meta_audio",
                "downloadUrl": v_url,
                "url": v_url,
                "direct_url": v_url
            })

        if thumb:
            formats.append({
                "quality": "Hình ảnh AI gốc (HD)",
                "type": "Hình ảnh HD",
                "size": "Gốc",
                "format_id": "meta_image",
                "downloadUrl": thumb,
                "url": thumb,
                "direct_url": thumb
            })

        if formats:
            return {
                "platform": "Meta AI",
                "title": title,
                "thumbnail": thumb or "",
                "duration": "N/A",
                "author": "Meta AI",
                "formats": formats
            }
    except Exception as e:
        print(f"Meta AI error: {e}")
    return None

# --- 5. YT-DLP GENERAL HANDLER ---
def fetch_ytdlp(url: str):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo+bestaudio/best",
        "skip_download": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "no_color": True,
        "socket_timeout": 15,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    
    cookies_path = os.path.join(BASE_DIR, "cookies.txt")
    if os.path.exists(cookies_path):
        ydl_opts["cookiefile"] = cookies_path

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            return None

        clean_title = (info.get("title") or "Video").strip()
        thumbnail = info.get("thumbnail") or ""
        duration_str = format_duration(info.get("duration"))
        author = info.get("uploader") or info.get("channel") or info.get("extractor_key") or "Tác giả"
        extractor_key = info.get("extractor_key", "").lower()

        formats = []
        raw_formats = info.get("formats", [])

        # Check for progressive formats (video + audio muxed) to allow 0-disk direct streaming
        best_prog = None
        for f in reversed(raw_formats):
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            f_url = f.get("url")
            if vcodec != "none" and acodec != "none" and f_url and f_url.startswith("http"):
                best_prog = f
                break

        best_direct = best_prog["url"] if best_prog else (info.get("url") or (raw_formats[-1].get("url") if raw_formats else ""))
        formats.append({
            "quality": "1080p / Tốt nhất (HD+)",
            "type": "MP4 Video + Audio",
            "size": format_size(info.get("filesize") or info.get("filesize_approx")) or "Gốc",
            "format_id": "best",
            "downloadUrl": best_direct,
            "url": best_direct,
            "direct_url": best_direct
        })

        seen_heights = set()
        for f in reversed(raw_formats):
            h = f.get("height")
            vcodec = f.get("vcodec", "none")
            f_url = f.get("url")
            
            if h and h >= 360 and vcodec != "none" and h not in seen_heights and f_url:
                seen_heights.add(h)
                f_size = format_size(f.get("filesize") or f.get("filesize_approx"))
                formats.append({
                    "quality": f"{h}p HD",
                    "type": f"MP4 {f.get('ext', 'mp4').upper()}",
                    "size": f_size or "Chuẩn",
                    "format_id": f"h_{h}",
                    "downloadUrl": f_url,
                    "url": f_url,
                    "direct_url": f_url
                })
                if len(seen_heights) >= 3:
                    break

        # Best direct audio stream
        best_audio_url = ""
        best_audio_size = None
        for f in reversed(raw_formats):
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            f_url = f.get("url")
            if vcodec == "none" and acodec != "none" and f_url and f_url.startswith("http"):
                best_audio_url = f_url
                best_audio_size = f.get("filesize")
                break

        if not best_audio_url:
            best_audio_url = best_direct

        formats.append({
            "quality": "Âm thanh tốt nhất (MP3)",
            "type": "MP3 320kbps",
            "size": format_size(best_audio_size) or "Âm thanh",
            "format_id": "audio_mp3",
            "downloadUrl": best_audio_url,
            "url": best_audio_url,
            "direct_url": best_audio_url
        })

        platform_name = "YouTube" if "youtube" in extractor_key else (info.get("extractor_key") or "Web")
        final_thumb = thumbnail or ""

        return {
            "platform": platform_name,
            "title": clean_title,
            "thumbnail": final_thumb,
            "duration": duration_str,
            "author": author,
            "formats": formats
        }

# --- PROXY IMAGE ENDPOINT (ASYNC STREAMING & 24H EDGE CACHING) ---
@app.get("/api/proxy_image")
async def proxy_image(url: str = Query(...)):
    target_url = url.strip()
    if not target_url or not target_url.startswith("http"):
        return Response(status_code=400)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
    }
    if "fbcdn" in target_url or "instagram" in target_url:
        headers["Referer"] = "https://www.instagram.com/"
    elif "twimg" in target_url or "twitter" in target_url or "x.com" in target_url:
        headers["Referer"] = "https://x.com/"
    elif "tiktok" in target_url or "byteoversea" in target_url:
        headers["Referer"] = "https://www.tiktok.com/"
    elif "ytimg" in target_url or "youtube" in target_url:
        headers["Referer"] = "https://www.youtube.com/"
    else:
        headers["Referer"] = ""

    try:
        client = await get_http_client()
        req = client.build_request("GET", target_url, headers=headers)
        upstream = await client.send(req, stream=True)
        if upstream.status_code >= 400:
            await upstream.aclose()
            raise HTTPException(status_code=upstream.status_code, detail="Image fetch failed")

        content_type = upstream.headers.get("Content-Type", "image/jpeg")
        content_len = upstream.headers.get("Content-Length")
        
        # Avoid streaming huge files through image proxy (> 5MB)
        if content_len and int(content_len) > 5 * 1024 * 1024:
            await upstream.aclose()
            return Response(status_code=413)

        resp_headers = {
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=86400, s-maxage=86400, immutable",
            "Content-Type": content_type
        }
        if content_len:
            resp_headers["Content-Length"] = content_len

        async def stream_img():
            try:
                async for chunk in upstream.aiter_bytes(chunk_size=16384):
                    yield chunk
            finally:
                await upstream.aclose()

        return StreamingResponse(stream_img(), media_type=content_type, headers=resp_headers)
    except Exception as e:
        # Return fallback SVG
        svg = b'''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400">
            <rect width="100%" height="100%" fill="#e0f2fe"/>
            <text x="50%" y="45%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="32" font-weight="bold" fill="#0284c7">TaiVideoPro Media</text>
            <text x="50%" y="60%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="18" fill="#38bdf8">&#10004; Video Preview</text>
        </svg>'''
        return Response(content=svg, media_type="image/svg+xml", headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600"
        })


# --- API INFO DISPATCHER ---
@app.get("/api/info")
def get_video_info(url: str = Query(...)):
    target_url = url.strip()
    if not target_url:
        raise HTTPException(status_code=400, detail="Vui lòng nhập link video hợp lệ!")

    # 1. Meta AI
    if "meta.ai" in target_url:
        res = fetch_meta_ai_share(target_url)
        if res:
            return res

    # 2. TikTok & Douyin
    if any(p in target_url for p in ["tiktok.com", "douyin.com", "iesdouyin.com"]):
        res = fetch_tiktok_douyin(target_url)
        if res:
            return res

    # 3. Instagram
    if "instagram.com" in target_url:
        res = fetch_instagram(target_url)
        if res:
            return res

    # 4. Twitter / X
    if "twitter.com" in target_url or "x.com" in target_url:
        res = fetch_twitter(target_url)
        if res:
            return res

    # 5. General yt-dlp (YouTube, Facebook, etc.)
    try:
        res = fetch_ytdlp(target_url)
        if res:
            return res
    except Exception as yt_err:
        print(f"yt-dlp general error: {yt_err}")

    # Fallback to specialized extractors
    res = fetch_tiktok_douyin(target_url)
    if res:
        return res
    res = fetch_instagram(target_url)
    if res:
        return res
    res = fetch_twitter(target_url)
    if res:
        return res
    res = fetch_meta_ai_share(target_url)
    if res:
        return res

    raise HTTPException(status_code=400, detail="Không thể trích xuất video từ liên kết này. Vui lòng thử lại với link khác hoặc kiểm tra tính công khai của video!")

# --- API DOWNLOAD ENDPOINT (DIRECT CHUNK STREAMING, ZERO DISK, 64KB RAM, FORCES DIRECT FILE DOWNLOAD) ---
@app.get("/api/download")
async def download_media(
    url: str = Query(...),
    direct_url: Optional[str] = Query(None),
    downloadUrl: Optional[str] = Query(None),
    type: str = Query("video"),
    quality: Optional[str] = Query(None),
    title: Optional[str] = Query(None),
    format: Optional[str] = Query(None),
    mode: Optional[str] = Query("auto")
):
    """
    Direct Chunk Streaming Download Endpoint:
    - Zero Disk Buffering (0 bytes written to disk).
    - Constant ~64KB RAM per stream (pipe chunks directly from CDN to browser).
    - NEVER opens in a new tab: Forces direct browser download via 'Content-Disposition: attachment' and 'application/octet-stream'.
    - If format='json' or mode='json': Returns direct CDN link and video metadata as JSON.
    """
    target_cdn = (direct_url or downloadUrl or "").strip()
    clean_title_str = clean_filename(title or "video")
    ext = "mp3" if type == "audio" else ("jpg" if type == "image" else "mp4")

    # 1. JSON mode (for programmatic callers)
    if format == "json" or mode == "json":
        if target_cdn:
            return {
                "status": "success",
                "downloadUrl": target_cdn,
                "direct_url": target_cdn,
                "title": clean_title_str,
                "quality": quality or "HD",
                "type": type,
                "filename": f"{clean_title_str}.{ext}"
            }
        info = await asyncio.to_thread(get_video_info, url=url)
        if info and info.get("formats"):
            selected_fmt = info["formats"][0]
            cdn_link = (selected_fmt.get("downloadUrl") or selected_fmt.get("url") or selected_fmt.get("direct_url") or "").strip()
            return {
                "status": "success",
                "downloadUrl": cdn_link,
                "direct_url": cdn_link,
                "title": clean_filename(info.get("title") or clean_title_str),
                "thumbnail": info.get("thumbnail") or "",
                "quality": selected_fmt.get("quality") or quality or "HD",
                "type": selected_fmt.get("type") or type,
                "size": selected_fmt.get("size") or "N/A",
                "filename": f"{clean_title_str}.{ext}"
            }

    # 2. Redirect mode (if explicitly requested)
    if mode == "redirect":
        if target_cdn:
            return RedirectResponse(url=target_cdn, status_code=307)
        info = await asyncio.to_thread(get_video_info, url=url)
        if info and info.get("formats"):
            for f in info["formats"]:
                cdn_link = (f.get("downloadUrl") or f.get("url") or f.get("direct_url") or "").strip()
                if cdn_link.startswith("http"):
                    return RedirectResponse(url=cdn_link, status_code=307)

    # 3. Direct Streaming Mode (Forces browser to download directly to computer, NO NEW TAB)
    if not target_cdn:
        try:
            info = await asyncio.to_thread(get_video_info, url=url)
            if info and info.get("formats"):
                selected_fmt = None
                if quality:
                    for f in info["formats"]:
                        if str(f.get("quality", "")).lower() == quality.lower() or str(f.get("format_id", "")).lower() == quality.lower():
                            selected_fmt = f
                            break
                if not selected_fmt and type == "audio":
                    for f in info["formats"]:
                        if "audio" in str(f.get("type", "")).lower() or "mp3" in str(f.get("format_id", "")).lower():
                            selected_fmt = f
                            break
                if not selected_fmt:
                    selected_fmt = info["formats"][0]

                target_cdn = (selected_fmt.get("downloadUrl") or selected_fmt.get("url") or selected_fmt.get("direct_url") or "").strip()
                if not title and info.get("title"):
                    clean_title_str = clean_filename(info["title"])
        except Exception as ex:
            print(f"[EXTRACT ERROR] {ex}")

    if not target_cdn or not target_cdn.startswith("http"):
        raise HTTPException(
            status_code=400,
            detail="Không thể lấy link tải trực tiếp! Vui lòng kiểm tra lại URL video."
        )

    # Prepare streaming request with anti-hotlinking headers
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }
    if "fbcdn" in target_cdn or "instagram" in target_cdn:
        headers["Referer"] = "https://www.instagram.com/"
    elif "tiktok" in target_cdn or "byteoversea" in target_cdn or "ibytedtos" in target_cdn:
        headers["Referer"] = "https://www.tiktok.com/"
    elif "douyin" in target_cdn or "zjcdn" in target_cdn or "douyinvod" in target_cdn or "douyinpic" in target_cdn:
        headers["Referer"] = "https://www.douyin.com/"
    elif "snapcdn" in target_cdn or "savetik" in target_cdn:
        headers["Referer"] = "https://savetik.co/"
    elif "twitter" in target_cdn or "twimg" in target_cdn:
        headers["Referer"] = "https://twitter.com/"
    elif "googlevideo" in target_cdn or "youtube" in target_cdn:
        headers["Referer"] = "https://www.youtube.com/"

    try:
        client = await get_http_client()
        req = client.build_request("GET", target_cdn, headers=headers)
        upstream_resp = await client.send(req, stream=True)

        # If CDN link expired, try refreshing once
        if upstream_resp.status_code >= 400:
            await upstream_resp.aclose()
            print(f"[STREAM REFRESH] Target CDN returned {upstream_resp.status_code}, re-extracting fresh link...")
            info = await asyncio.to_thread(get_video_info, url=url)
            if info and info.get("formats"):
                target_cdn = (info["formats"][0].get("downloadUrl") or info["formats"][0].get("url") or info["formats"][0].get("direct_url") or "").strip()
                req = client.build_request("GET", target_cdn, headers=headers)
                upstream_resp = await client.send(req, stream=True)

        if upstream_resp.status_code < 400:
            ascii_title = re.sub(r'[^a-zA-Z0-9_-]', '_', clean_title_str)
            if not ascii_title:
                ascii_title = "video"
            utf8_title_enc = urllib.parse.quote(f"{clean_title_str}.{ext}")
            cd_header = f'attachment; filename="{ascii_title}.{ext}"; filename*=UTF-8\'\'{utf8_title_enc}'

            resp_headers = {
                "Content-Disposition": cd_header,
                "Access-Control-Expose-Headers": "Content-Disposition, Content-Length",
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=3600"
            }
            content_len = upstream_resp.headers.get("Content-Length")
            if content_len:
                resp_headers["Content-Length"] = content_len

            async def iter_stream():
                try:
                    async for chunk in upstream_resp.aiter_bytes(chunk_size=65536):
                        yield chunk
                except (httpx.RequestError, asyncio.CancelledError, GeneratorExit):
                    pass
                finally:
                    await upstream_resp.aclose()

            return StreamingResponse(
                iter_stream(),
                media_type="application/octet-stream",
                headers=resp_headers
            )
        else:
            await upstream_resp.aclose()
            print(f"[STREAM FAILED] Status code: {upstream_resp.status_code}")
    except Exception as stream_err:
        print(f"[STREAM ERROR] {stream_err}")

    # Fallback to redirect if streaming encountered an unexpected error
    return RedirectResponse(url=target_cdn, status_code=307)

# Favicon and Static index.html fallback
@app.get("/favicon.ico", include_in_schema=False)
def get_favicon():
    fav_ico = os.path.join(BASE_DIR, "favicon.ico")
    if os.path.exists(fav_ico):
        return FileResponse(fav_ico, media_type="image/x-icon")
    fav_svg = os.path.join(BASE_DIR, "favicon.svg")
    if os.path.exists(fav_svg):
        return FileResponse(fav_svg, media_type="image/svg+xml")
    return Response(status_code=204)

@app.get("/")
def serve_root():
    index_file = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file, media_type="text/html")
    return Response(content="<h1>taivideopro.onrender.com</h1><p>Frontend index.html not found.</p>", media_type="text/html")

if os.path.exists(BASE_DIR):
    app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
