# FocusFlow AI 🚀
AI Mentor giúp bạn vượt qua trì hoãn và tập trung học tập — powered by GPT-5 Mini.

---

## 📁 Cấu trúc thư mục

```
focusflow/
├── app.py
├── requirements.txt
├── .env.example
├── .env               ← tự tạo (KHÔNG commit)
└── templates/
    └── index.html
```

---

## ⚙️ Cài đặt

```bash
# 1. Tạo và kích hoạt virtual environment
python -m venv venv

# Windows
venv\Scripts\activate
# Mac / Linux
source venv/bin/activate

# 2. Cài dependencies
pip install -r requirements.txt
```

---

## 🔑 Thêm API Key

**Cách 1 — File `.env` (khuyên dùng)**
```bash
cp .env.example .env
# Mở .env, thay sk-your-api-key-here bằng key thật của bạn
```

**Cách 2 — Biến môi trường hệ thống**
```bash
# Mac / Linux
export OPENAI_API_KEY=sk-...

# Windows CMD
set OPENAI_API_KEY=sk-...

# Windows PowerShell
$env:OPENAI_API_KEY="sk-..."
```

> Lấy API key tại: https://platform.openai.com/api-keys

---

## ▶️ Chạy ứng dụng

```bash
python app.py
```

Mở trình duyệt: **http://localhost:5000**

---

## ⚠️ Lưu ý về model

Project sử dụng `gpt-5-mini`. Nếu OpenAI chưa phát hành model này trên tài khoản của bạn,
hãy đổi `model="gpt-5-mini"` thành `model="gpt-4o-mini"` trong `app.py`.
