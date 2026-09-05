import os
import sys
import re
import json
import shutil
import urllib.parse
import urllib.request
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
import yt_dlp

app = FastAPI(title="TaiVideoPro API", version="2.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Length"]
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp_downloads")
os.makedirs(TEMP_DIR, exist_ok=True)

FFMPEG_PATH = None
local_ffmpeg = os.path.join(BASE_DIR, "ffmpeg.exe")
if os.path.exists(local_ffmpeg):
    FFMPEG_PATH = local_ffmpeg
elif shutil.which("ffmpeg"):
    FFMPEG_PATH = shutil.which("ffmpeg")

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
                    "url": f"/api/download?url={urllib.parse.quote(target_url)}&direct_url={urllib.parse.quote(clean_href)}&type=video&title={urllib.parse.quote(clean_title)}"
                })
            elif "MP4" in clean_label:
                formats.append({
                    "quality": "Tiêu chuẩn (SD Không logo)",
                    "type": "MP4 Không logo",
                    "size": "SD",
                    "format_id": "douyin_sd",
                    "url": f"/api/download?url={urllib.parse.quote(target_url)}&direct_url={urllib.parse.quote(clean_href)}&type=video&title={urllib.parse.quote(clean_title)}"
                })
            elif "MP3" in clean_label or "Audio" in clean_label:
                formats.append({
                    "quality": "Âm thanh gốc (MP3)",
                    "type": "MP3 320kbps",
                    "size": "Audio",
                    "format_id": "douyin_audio",
                    "url": f"/api/download?url={urllib.parse.quote(target_url)}&direct_url={urllib.parse.quote(clean_href)}&type=audio&title={urllib.parse.quote(clean_title)}"
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
                "url": f"/api/download?url={urllib.parse.quote(target_url)}&direct_url={urllib.parse.quote(p_clean)}&type=image&title={urllib.parse.quote(clean_title + f' - Anh {idx+1}')}"
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
                    "url": f"/api/download?url={urllib.parse.quote(clean_target)}&direct_url={urllib.parse.quote(play_url)}&type=video&title={urllib.parse.quote(clean_title)}"
                })
            if play_sd and play_hd and play_sd != play_hd:
                formats.append({
                    "quality": "Tiêu chuẩn (SD Không logo)",
                    "type": "MP4 Không logo",
                    "size": "SD",
                    "format_id": "tiktok_sd",
                    "url": f"/api/download?url={urllib.parse.quote(clean_target)}&direct_url={urllib.parse.quote(play_sd)}&type=video&title={urllib.parse.quote(clean_title)}"
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
                        "url": f"/api/download?url={urllib.parse.quote(clean_target)}&direct_url={urllib.parse.quote(img_url)}&type=image&title={urllib.parse.quote(clean_title + f' - Anh {idx + 1}')}"
                    })

            if music_url:
                formats.append({
                    "quality": "Âm thanh gốc",
                    "type": "MP3 320kbps",
                    "size": f"{max(1, int(duration_sec * 0.04)):.1f} MB",
                    "format_id": "tiktok_audio",
                    "url": f"/api/download?url={urllib.parse.quote(clean_target)}&direct_url={urllib.parse.quote(music_url)}&type=audio&title={urllib.parse.quote(clean_title)}"
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
                "url": f"/api/download?url={urllib.parse.quote(url)}&direct_url={urllib.parse.quote(video_url)}&type=video&title={urllib.parse.quote(title)}"
            },
            {
                "quality": "Âm thanh gốc",
                "type": "MP3 320kbps",
                "size": "MP3",
                "format_id": "ig_audio",
                "url": f"/api/download?url={urllib.parse.quote(url)}&direct_url={urllib.parse.quote(video_url)}&type=audio&title={urllib.parse.quote(title)}"
            }
        ]
        return {
            "platform": "Instagram",
            "title": title,
            "author": author,
            "thumbnail": f"/api/proxy_image?url={urllib.parse.quote(thumb)}" if thumb else "",
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
                "url": f"/api/download?url={urllib.parse.quote(url)}&direct_url={urllib.parse.quote(video_url)}&type=video&title={urllib.parse.quote(title)}"
            },
            {
                "quality": "Âm thanh",
                "type": "MP3 320kbps",
                "size": "MP3",
                "format_id": "twitter_audio",
                "url": f"/api/download?url={urllib.parse.quote(url)}&direct_url={urllib.parse.quote(video_url)}&type=audio&title={urllib.parse.quote(title)}"
            }
        ]
        return {
            "platform": "Twitter",
            "title": title,
            "author": author,
            "thumbnail": f"/api/proxy_image?url={urllib.parse.quote(thumb)}" if thumb else "",
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
                "url": f"/api/download?url={urllib.parse.quote(clean_url)}&direct_url={urllib.parse.quote(v_url)}&type=video&title={urllib.parse.quote(title)}"
            })
            formats.append({
                "quality": "Âm thanh gốc",
                "type": "MP3",
                "size": "MP3",
                "format_id": "meta_audio",
                "url": f"/api/download?url={urllib.parse.quote(clean_url)}&direct_url={urllib.parse.quote(v_url)}&type=audio&title={urllib.parse.quote(title)}"
            })

        if thumb:
            formats.append({
                "quality": "Hình ảnh AI gốc (HD)",
                "type": "Hình ảnh HD",
                "size": "Gốc",
                "format_id": "meta_image",
                "url": f"/api/download?url={urllib.parse.quote(clean_url)}&direct_url={urllib.parse.quote(thumb)}&type=image&title={urllib.parse.quote(title)}"
            })

        if formats:
            return {
                "platform": "Meta AI",
                "title": title,
                "thumbnail": f"/api/proxy_image?url={urllib.parse.quote(thumb)}" if thumb else "",
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

        # Best video
        formats.append({
            "quality": "1080p / Tốt nhất (HD+)",
            "type": "MP4 Video + Audio",
            "size": format_size(info.get("filesize") or info.get("filesize_approx")) or "Gốc",
            "format_id": "best",
            "url": f"/api/download?url={urllib.parse.quote(url)}&type=video&quality=best&title={urllib.parse.quote(clean_title)}"
        })

        seen_heights = set()
        for f in reversed(raw_formats):
            h = f.get("height")
            vcodec = f.get("vcodec", "none")
            if h and h >= 360 and vcodec != "none" and h not in seen_heights:
                seen_heights.add(h)
                f_size = format_size(f.get("filesize") or f.get("filesize_approx"))
                formats.append({
                    "quality": f"{h}p HD",
                    "type": f"MP4 {f.get('ext', 'mp4').upper()}",
                    "size": f_size or "Chuẩn",
                    "format_id": f"h_{h}",
                    "url": f"/api/download?url={urllib.parse.quote(url)}&type=video&quality={h}p&title={urllib.parse.quote(clean_title)}"
                })
                if len(seen_heights) >= 3:
                    break

        # Best audio
        formats.append({
            "quality": "Âm thanh tốt nhất (MP3)",
            "type": "MP3 320kbps",
            "size": "Âm thanh",
            "format_id": "audio_mp3",
            "url": f"/api/download?url={urllib.parse.quote(url)}&type=audio&title={urllib.parse.quote(clean_title)}"
        })

        platform_name = "YouTube" if "youtube" in extractor_key else (info.get("extractor_key") or "Web")
        return {
            "platform": platform_name,
            "title": clean_title,
            "thumbnail": f"/api/proxy_image?url={urllib.parse.quote(thumbnail)}" if thumbnail else "",
            "duration": duration_str,
            "author": author,
            "formats": formats
        }

# --- PROXY IMAGE ENDPOINT (PRESERVES QUERY PARAMS & ADDS CORS) ---
@app.get("/api/proxy_image")
def proxy_image(url: str = Query(...)):
    # url is already unquoted by FastAPI query parser. DO NOT call unquote again!
    target_url = url.strip()
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
        req = urllib.request.Request(target_url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=12)
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        data = resp.read()
        return Response(
            content=data,
            media_type=content_type,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400"
            }
        )
    except Exception as e:
        print(f"Proxy image failed for {target_url[:80]}: {e}")
        # Return elegant SVG fallback
        svg = b'''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400">
            <rect width="100%" height="100%" fill="#e0f2fe"/>
            <text x="50%" y="45%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="32" font-weight="bold" fill="#0284c7">TaiVideoPro Media</text>
            <text x="50%" y="60%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="18" fill="#38bdf8">&#10004; Video Preview</text>
        </svg>'''
        return Response(content=svg, media_type="image/svg+xml", headers={"Access-Control-Allow-Origin": "*"})

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

# --- API DOWNLOAD ENDPOINT WITH REAL-TIME CONTENT-LENGTH ---
@app.get("/api/download")
def download_media(
    url: str = Query(...),
    direct_url: Optional[str] = Query(None),
    type: str = Query("video"),
    quality: Optional[str] = Query(None),
    title: Optional[str] = Query(None)
):
    clean_title_str = clean_filename(title or "video")
    
    # Direct stream if direct_url provided
    if direct_url:
        parsed_direct = direct_url.strip()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "*/*",
        }
        if "fbcdn" in parsed_direct or "instagram" in parsed_direct:
            headers["Referer"] = "https://www.instagram.com/"
        elif "tiktok" in parsed_direct or "byteoversea" in parsed_direct or "ibytedtos" in parsed_direct:
            headers["Referer"] = "https://www.tiktok.com/"
        elif "douyin" in parsed_direct or "zjcdn" in parsed_direct or "douyinvod" in parsed_direct or "douyinpic" in parsed_direct:
            headers["Referer"] = "https://www.douyin.com/"
        elif "snapcdn" in parsed_direct or "savetik" in parsed_direct:
            headers["Referer"] = "https://savetik.co/"
        elif "twitter" in parsed_direct or "twimg" in parsed_direct:
            headers["Referer"] = "https://twitter.com/"
        elif "googlevideo" in parsed_direct or "youtube" in parsed_direct:
            headers["Referer"] = "https://www.youtube.com/"

        req = urllib.request.Request(parsed_direct, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=25)
            ext = "mp3" if type == "audio" else ("jpg" if type == "image" else "mp4")
            content_type = "audio/mpeg" if type == "audio" else ("image/jpeg" if type == "image" else "video/mp4")
            
            ascii_title = re.sub(r'[^a-zA-Z0-9_-]', '_', clean_title_str)
            utf8_title_enc = urllib.parse.quote(f"{clean_title_str}.{ext}")
            cd_header = f'attachment; filename="{ascii_title}.{ext}"; filename*=UTF-8\'\'{utf8_title_enc}'

            resp_headers = {
                "Content-Disposition": cd_header,
                "Access-Control-Expose-Headers": "Content-Disposition, Content-Length"
            }
            content_len = resp.headers.get("Content-Length")
            if content_len:
                resp_headers["Content-Length"] = content_len

            def iter_stream():
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    yield chunk

            return StreamingResponse(
                iter_stream(),
                media_type=content_type,
                headers=resp_headers
            )
        except Exception as direct_err:
            print(f"Direct stream error: {direct_err}")

    # Fallback to yt-dlp local download
    ext = "mp3" if type == "audio" else "mp4"
    out_tmpl = os.path.join(TEMP_DIR, f"{clean_title_str}_%(id)s.%(ext)s")
    
    ydl_opts = {
        "outtmpl": out_tmpl,
        "quiet": True,
        "nocheckcertificate": True,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    if FFMPEG_PATH:
        ydl_opts["ffmpeg_location"] = FFMPEG_PATH

    cookies_path = os.path.join(BASE_DIR, "cookies.txt")
    if os.path.exists(cookies_path):
        ydl_opts["cookiefile"] = cookies_path

    if type == "audio":
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }] if FFMPEG_PATH else []
        })
    else:
        if quality and quality.endswith("p"):
            height_val = quality.replace("p", "")
            ydl_opts["format"] = f"bestvideo[height<={height_val}]+bestaudio/best[height<={height_val}]/best"
        else:
            ydl_opts["format"] = "bestvideo+bestaudio/best"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res_info = ydl.extract_info(url, download=True)
            saved_file = ydl.prepare_filename(res_info)
            if type == "audio":
                saved_file = os.path.splitext(saved_file)[0] + ".mp3"
            
            if os.path.exists(saved_file):
                ascii_name = re.sub(r'[^a-zA-Z0-9_-]', '_', clean_title_str) + f".{ext}"
                return FileResponse(
                    saved_file,
                    filename=ascii_name,
                    media_type="audio/mpeg" if type == "audio" else "video/mp4"
                )
    except Exception as ydl_err:
        print(f"yt-dlp download failed: {ydl_err}")

    raise HTTPException(status_code=500, detail="Không thể tải file media về máy!")

# Static index.html fallback
if os.path.exists(os.path.join(BASE_DIR, "index.html")):
    @app.get("/")
    def serve_root():
        return FileResponse(os.path.join(BASE_DIR, "index.html"))

    app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
