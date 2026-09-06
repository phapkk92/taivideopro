# 🎬 taivideopro.onrender.com - Website Tải Video Đa Nền Tảng

Website tải video và âm thanh đa nền tảng chất lượng cao, không logo (watermark), tốc độ cao và hoàn toàn miễn phí. Hỗ trợ đầy đủ **TikTok, Douyin, YouTube, Facebook, Instagram Reels, Meta AI**.

![taivideopro.onrender.com](https://raw.githubusercontent.com/username/taivideopro/main/favicon.png)

---

## ✨ Tính Năng Nổi Bật

- 🚀 **Đa nền tảng:**
  - **TikTok:** Tải video HD không có watermark (logo) + tải file âm thanh MP3.
  - **Douyin (抖音):** Giải mã link chia sẻ ngắn (`v.douyin.com`), tải video HD sắc nét và nhạc chuông gốc.
  - **YouTube:** Tải định dạng 1080p, 720p, 480p, 360p kèm audio chất lượng cao (320kbps).
  - **Facebook & Instagram:** Tải video Reels, bài viết và Story nhanh chóng.
  - **Meta AI:** Tải video được tạo từ Meta AI.
- 🎨 **Giao diện Sky Cloud sang trọng & trực quan:**
  - **Nút "Dán" 3D nổi bật:** Tự động đọc clipboard và dán liên kết mượt mà chỉ với 1 click.
  - **Hiệu ứng chú tiểu mini gõ mõ:** Tinh tế, tạo cảm giác thư giãn bình an trong lúc tải.
  - **Thanh tiến trình thời gian thực (%):** Hiển thị chính xác tiến độ tải file về máy.
  - **Phát trực tiếp & Xem trước:** Xem trước hình thu nhỏ (thumbnail) và phát video trực tiếp trên web.

---

## 📁 Cấu Trúc Thư Mục Dự Án

```text
taivideopro/
├── index.html          # Giao diện Frontend hoàn chỉnh (React + Tailwind CSS + Lucide Icons)
├── main.py             # FastAPI Backend Server xử lý tải video & proxy stream
├── requirements.txt    # Danh sách thư viện Python cần thiết
├── Dockerfile          # Cấu hình Docker container sẵn sàng deploy Render / Railway / VPS
├── Procfile            # Cấu hình Web Process cho Render / Heroku
├── render.yaml         # Render Blueprint cho 1-click deploy
├── .gitignore          # File cấu hình bỏ qua file tạm, cache, ffmpeg.exe
├── run.bat             # File chạy 1-click trên Windows
├── run.sh              # File chạy trên Linux / macOS
├── favicon.ico         # Favicon chuẩn ICO cho trình duyệt
└── favicon.svg         # Favicon chuẩn Vector SVG
```

---

## 🚀 Hướng Dẫn Chạy Tại Máy (Local)

### Cách 1: Chạy trên Windows (Nhanh nhất)
1. Nhấp đúp chuột vào file **`run.bat`**.
2. Script sẽ tự động cài đặt thư viện cần thiết và mở trình duyệt tại địa chỉ `http://localhost:8000`.

### Cách 2: Chạy bằng dòng lệnh (Windows / macOS / Linux)
```bash
# 1. Cài đặt các thư viện phụ thuộc:
pip install -r requirements.txt

# 2. Khởi chạy máy chủ:
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Truy cập: **`http://localhost:8000`** trên trình duyệt của bạn.

---

## 🌐 Hướng Dẫn Đưa Lên GitHub và Deploy Lên Render.com (Miễn Phí 100%)

### Bước 1: Đưa Code Lên GitHub
1. Truy cập [GitHub](https://github.com) và tạo một Repository mới (ví dụ đặt tên: `taivideopro`).
2. Mở terminal hoặc PowerShell tại thư mục dự án và chạy:
```bash
git init
git add .
git commit -m "feat: Khoi tao du an taivideopro da nen tang"
git branch -M main
git remote add origin https://github.com/<TÊN_GITHUB_CỦA_BẠN>/taivideopro.git
git push -u origin main
```
*(Hoặc bạn có thể giải nén file `taivideopro-main.zip` và kéo thả trực tiếp lên giao diện web GitHub).*

---

### Bước 2: Deploy Miễn Phí Lên Render.com
1. Đăng ký/Đăng nhập tài khoản miễn phí tại **[Render.com](https://render.com)**.
2. Tại trang Dashboard, chọn **New +** ➡️ **Web Service**.
3. Chọn **Build and deploy from a Git repository** và liên kết với kho lưu trữ `taivideopro` trên GitHub của bạn.
4. Cấu hình các thông số như sau:
   - **Name:** `taivideopro` (hoặc tên bạn thích, web sẽ có dạng: `taivideopro.onrender.com`)
   - **Region:** `Singapore` (để có tốc độ nhanh nhất tại Việt Nam)
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type:** `Free`
5. Bấm **Create Web Service**.
6. Render sẽ tự động build và cung cấp cho bạn tên miền trực tuyến miễn phí:
   👉 **`https://taivideopro.onrender.com`**

*(Ghi chú: Nếu bạn muốn cài sẵn ffmpeg đầy đủ nhất trên Render, bạn cũng có thể chọn hình thức deploy bằng **Dockerfile** có sẵn trong thư mục).*

---

## 🛠️ Công Nghệ Sử Dụng

- **Backend:** Python 3.11+, FastAPI, Uvicorn, yt-dlp, imageio-ffmpeg.
- **Frontend:** React 18, Tailwind CSS, Lucide Icons, Canvas Confetti.
- **Deployment:** Render, Railway, Docker, Linux, Windows.

---

## 📄 Bản Quyền & Giấy Phép

Dự án phát triển phục vụ mục đích học tập và sử dụng cá nhân hợp pháp. Vui lòng tôn trọng quyền sở hữu trí tuệ của tác giả nội dung trên các nền tảng gốc.
