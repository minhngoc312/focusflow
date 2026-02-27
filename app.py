from flask import Flask, request, jsonify, render_template, session
from openai import OpenAI
import os

# ──────────────────────────────────────────────
# INIT
# ──────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "focusflow-secret-2025")

api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    raise ValueError("❌ OPENAI_API_KEY chưa được set")

client = OpenAI(api_key=api_key)

# ──────────────────────────────────────────────
# SYSTEM PROMPT
# ──────────────────────────────────────────────
BASE_SYSTEM_PROMPT = """
Bạn là AI Mentor chuyên giúp học sinh vượt qua trì hoãn.
Trả lời rõ ràng, có cấu trúc, ngắn gọn nhưng đủ ý.

Nếu người dùng yêu cầu lập kế hoạch học 1–3 tiếng, áp dụng SMART BLOCK:

1️⃣ Block Kích Hoạt (10–15 phút đầu)
2️⃣ Block Deep Focus (25–40 phút)
3️⃣ Block Luyện Tập (25–35 phút)
4️⃣ Block Củng Cố (10–15 phút cuối)

BẮT BUỘC:
- Ghi rõ mốc thời gian (0:00–0:15)
- Không kết thúc khi chưa đủ block
"""

BIORHYTHM_FIELDS = {
    "wake_time": "giờ thức dậy (6:00)",
    "sleep_time": "giờ đi ngủ (23:00)",
    "peak_time": "giờ tập trung cao nhất (8:00–10:00)",
}

PLANNING_KEYWORDS = [
    "lập kế hoạch", "kế hoạch học", "thời khóa biểu",
    "lịch học", "plan", "schedule"
]

# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
def get_biorhythm():
    return session.get("biorhythm", {})

def biorhythm_complete():
    bio = get_biorhythm()
    return all(bio.get(k) for k in BIORHYTHM_FIELDS)

def missing_fields():
    bio = get_biorhythm()
    return [BIORHYTHM_FIELDS[k] for k in BIORHYTHM_FIELDS if not bio.get(k)]

def build_system_prompt():
    bio = get_biorhythm()
    if not biorhythm_complete():
        return BASE_SYSTEM_PROMPT

    return f"""
{BASE_SYSTEM_PROMPT}

── NHỊP SINH HỌC ──
Thức dậy: {bio['wake_time']}
Ngủ: {bio['sleep_time']}
Giờ vàng: {bio['peak_time']}

Ưu tiên Deep Focus vào giờ vàng.
"""

def is_planning_request(text):
    return any(k in text.lower() for k in PLANNING_KEYWORDS)

# ──────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Vui lòng nhập nội dung."}), 400

    if is_planning_request(user_message) and not biorhythm_complete():
        missing = missing_fields()
        return jsonify({
            "reply": "Để cá nhân hoá kế hoạch, mình cần thêm:\n" +
                     "\n".join(f"• {m}" for m in missing),
            "needs_biorhythm": True,
            "missing_fields": missing
        })

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",  # model ổn định
            messages=[
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7
        )

        reply = completion.choices[0].message.content.strip()

        if not reply:
            reply = "AI chưa tạo được phản hồi. Thử lại giúp mình nhé."

        return jsonify({
            "reply": reply,
            "biorhythm_used": biorhythm_complete(),
            "biorhythm_data": get_biorhythm(),
        })

    except Exception as e:
        print("🔥 API ERROR:", str(e))
        return jsonify({"error": str(e)}), 500

