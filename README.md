
# SnapDownload Pro - Web tải video đa nền tảng 100% chạy thật

## Tính năng
- TikTok không logo, Facebook HD, Instagram Reels/Story, YouTube 1080p/MP3, Twitter, Threads
- Giao diện giống SnapTik, tự nhận diện nền tảng
- Backend dùng yt-dlp -> hỗ trợ 1000+ trang

## Cách chạy trên máy (chạy thật)

1. Cài Python 3.10+
2. Chạy:
```bash
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```
3. Mở http://localhost:8000 -> dán link là tải được thật.

## Cách đẩy lên GitHub

```bash
git init
git add .
git commit -m "snapdownload pro"
git branch -M main
git remote add origin https://github.com/USERNAME/video-downloader.git
git push -u origin main
```

## Deploy miễn phí 0đ lên Internet

**Frontend + Backend chung 1 chỗ (Render):**
- Vào render.com -> New Web Service -> Connect repo
- Build Command: `pip install -r backend/requirements.txt`
- Start Command: `uvicorn backend.main:app --host 0.0.0.0 --port 10000`
- Xong, Render sẽ cho link https://xxx.onrender.com

**Hoặc tách riêng:**
- Frontend: Vercel (chọn thư mục frontend)
- Backend: Render

## Lưu ý đa nền tảng
- Facebook/Instagram private cần file `backend/cookies.txt` (export bằng extension Get cookies.txt)
- YouTube đôi khi bị chặn IP free, thêm proxy nếu cần

## Kiếm tiền
Chèn mã Adsterra vào `frontend/index.html` ngay dưới nút tải.

Made by AI for you.
