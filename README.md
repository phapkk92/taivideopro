# SnapDownload Pro V3 - Tải video đa nền tảng 100% chạy thật

## ✨ Tính năng nổi bật
- **🌐 Ô chọn Tất cả (Auto-detect):** Dán link từ bất kỳ nền tảng nào, hệ thống tự động nhận diện và trích xuất video!
- **Hỗ trợ đa nền tảng:** TikTok không logo/watermark, YouTube 1080p Full HD / MP3, Facebook HD, Instagram Reels/Post, Twitter/X, Threads, Douyin, Pinterest, Reddit...
- **Chỉ cần dán link:** Bấm nút "Dán" hoặc Ctrl+V, hệ thống tự động nhận diện và tải video về máy ngay!
- **Tải file thật về máy:** Không lo bị chặn 403 Forbidden hay mất tiếng, tải trực tiếp file MP4 / MP3 về máy tính hoặc điện thoại.

## 🚀 Cách chạy trên máy (Chạy thật 100%)

### Cách 1: Click đúp chạy ngay (Khuyên dùng trên Windows)
- Click đúp vào file `run.bat`
- Trình duyệt sẽ tự động mở trang web tại `http://localhost:8000`

### Cách 2: Chạy bằng lệnh Terminal
1. Cài đặt thư viện:
```bash
pip install -r requirements.txt
```
2. Khởi động server:
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
3. Mở trình duyệt truy cập `http://localhost:8000`
