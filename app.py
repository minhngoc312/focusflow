import os
import sqlite3
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for, g, flash,
)
from werkzeug.security import generate_password_hash, check_password_hash
from openai import OpenAI

# ──────────────────────────────────────────────────────────────
#  APP INIT
# ──────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "focusflow-dev-secret-CHANGE-IN-PROD")
app.config["SESSION_COOKIE_HTTPONLY"]  = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# OpenAI — gracefully disabled when key is missing (e.g. during tests)
_api_key = os.environ.get("OPENAI_API_KEY", "")
client   = OpenAI(api_key=_api_key) if _api_key else None

# ──────────────────────────────────────────────────────────────
#  DATABASE  –  SQLite stored in /instance/ so Render's
#               persistent-disk mount covers it automatically
# ──────────────────────────────────────────────────────────────
DATABASE = os.path.join(app.instance_path, "focusflow.db")
os.makedirs(app.instance_path, exist_ok=True)

# Schema — add columns here as the app grows; never drop existing ones
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER   PRIMARY KEY AUTOINCREMENT,
    email         TEXT      UNIQUE NOT NULL,
    password_hash TEXT      NOT NULL,
    full_name     TEXT      NOT NULL DEFAULT '',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def get_db() -> sqlite3.Connection:
    """Return a per-request SQLite connection stored on Flask `g`."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    """Create tables on first launch.  Safe to call on every startup."""
    with sqlite3.connect(DATABASE) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


init_db()   # always runs at import / startup — idempotent


# ──────────────────────────────────────────────────────────────
#  AUTH HELPERS
# ──────────────────────────────────────────────────────────────
def login_required(f):
    """Decorator — redirect unauthenticated requests to /login."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Vui lòng đăng nhập để tiếp tục.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def current_user():
    """Return the logged-in user row (sqlite3.Row), or None."""
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute(
        "SELECT id, email, full_name, created_at FROM users WHERE id = ?", (uid,)
    ).fetchone()


# ──────────────────────────────────────────────────────────────
#  AUTH ROUTES
# ──────────────────────────────────────────────────────────────
@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:               # already logged in
        return redirect(url_for("index"))

    if request.method == "POST":
        email     = request.form.get("email",            "").strip().lower()
        password  = request.form.get("password",         "")
        confirm   = request.form.get("confirm_password", "")
        full_name = request.form.get("full_name",        "").strip()

        # ── validation ──────────────────────────────────
        error = None
        if not email or "@" not in email or "." not in email:
            error = "Email không hợp lệ."
        elif len(password) < 6:
            error = "Mật khẩu phải có ít nhất 6 ký tự."
        elif password != confirm:
            error = "Mật khẩu xác nhận không khớp."

        if not error:
            existing = get_db().execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
            if existing:
                error = "Email này đã được đăng ký."

        if error:
            flash(error, "error")
            return render_template("register.html", email=email, full_name=full_name)

        # ── persist ─────────────────────────────────────
        pw_hash = generate_password_hash(password)
        db = get_db()
        db.execute(
            "INSERT INTO users (email, password_hash, full_name) VALUES (?, ?, ?)",
            (email, pw_hash, full_name),
        )
        db.commit()

        flash("Đăng ký thành công! Hãy đăng nhập.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        email    = request.form.get("email",    "").strip().lower()
        password = request.form.get("password", "")

        user = get_db().execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Email hoặc mật khẩu không đúng.", "error")
            return render_template("login.html", email=email)

        # ── write session ────────────────────────────────
        session.clear()
        session["user_id"]    = user["id"]
        session["user_email"] = user["email"]
        session["user_name"]  = user["full_name"] or user["email"].split("@")[0]
        session.permanent     = True          # survives browser restart

        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("Đã đăng xuất. Hẹn gặp lại!", "info")
    return redirect(url_for("login"))


# ──────────────────────────────────────────────────────────────
#  DASHBOARD  (protected)
# ──────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    return render_template(
        "index.html",
        user_name=session.get("user_name",  ""),
        user_email=session.get("user_email", ""),
    )


# ──────────────────────────────────────────────────────────────
#  AI CHAT  (protected)
# ──────────────────────────────────────────────────────────────
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

BIORHYTHM_FIELDS  = {
    "wake_time":  "giờ thức dậy (6:00)",
    "sleep_time": "giờ đi ngủ (23:00)",
    "peak_time":  "giờ tập trung cao nhất (8:00–10:00)",
}
PLANNING_KEYWORDS = [
    "lập kế hoạch", "kế hoạch học", "thời khóa biểu",
    "lịch học", "plan", "schedule",
]


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
Ngủ:      {bio['sleep_time']}
Giờ vàng: {bio['peak_time']}

Ưu tiên Deep Focus vào giờ vàng.
"""

def is_planning_request(text: str) -> bool:
    return any(k in text.lower() for k in PLANNING_KEYWORDS)


@app.route("/chat", methods=["POST"])
@login_required
def chat():
    if not client:
        return jsonify({"error": "OPENAI_API_KEY chưa được cấu hình trên server."}), 503

    data         = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Vui lòng nhập nội dung."}), 400

    if is_planning_request(user_message) and not biorhythm_complete():
        missing = missing_fields()
        return jsonify({
            "reply":           "Để cá nhân hoá kế hoạch, mình cần thêm:\n"
                               + "\n".join(f"• {m}" for m in missing),
            "needs_biorhythm": True,
            "missing_fields":  missing,
        })

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": build_system_prompt()},
                {"role": "user",   "content": user_message},
            ],
            temperature=0.7,
        )
        reply = completion.choices[0].message.content.strip()
        if not reply:
            reply = "AI chưa tạo được phản hồi. Thử lại giúp mình nhé."
        return jsonify({
            "reply":          reply,
            "biorhythm_used": biorhythm_complete(),
            "biorhythm_data": get_biorhythm(),
        })
    except Exception as e:
        print("🔥 API ERROR:", e)
        return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────────────────────────
#  BIORHYTHM  (protected)
# ──────────────────────────────────────────────────────────────
@app.route("/biorhythm/status")
@login_required
def biorhythm_status():
    return jsonify({
        "complete": biorhythm_complete(),
        "data":     get_biorhythm(),
        "missing":  missing_fields(),
    })

@app.route("/biorhythm/save", methods=["POST"])
@login_required
def biorhythm_save():
    data = request.get_json(silent=True) or {}
    bio  = session.get("biorhythm", {})
    for k in BIORHYTHM_FIELDS:
        v = data.get(k, "").strip()
        if v:
            bio[k] = v
    session["biorhythm"] = bio
    session.modified     = True
    return jsonify({"ok": True, "complete": biorhythm_complete(), "data": bio})

@app.route("/biorhythm/reset", methods=["POST"])
@login_required
def biorhythm_reset():
    session.pop("biorhythm", None)
    return jsonify({"ok": True})


# ──────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)
