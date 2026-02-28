import os
import sqlite3
from datetime import date, timedelta
from functools import wraps
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

from flask import (
    Flask, request, render_template,
    session, redirect, url_for, g, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)
app.secret_key = "focusflow-secret-key-dev"
DATABASE = "focusflow.db"


# ================= DATABASE =================
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    cursor = db.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT DEFAULT '',
        daily_goal INTEGER DEFAULT 120,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        duration INTEGER DEFAULT 25,
        completed INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    db.commit()
    db.close()


init_db()


# ================= AUTH =================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute(
        "SELECT * FROM users WHERE id=?",
        (uid,)
    ).fetchone()


# ================= ROUTES =================

@app.route("/")
@login_required
def dashboard():
    user = get_current_user()
    return render_template("index.html", user=user)


@app.route("/profile")
@login_required
def profile():
    user = get_current_user()
    uid = user["id"]
    db = get_db()

    done_blocks = db.execute("""
        SELECT COUNT(*) FROM blocks
        WHERE user_id=? AND completed=1
    """, (uid,)).fetchone()[0]

    total_mins = db.execute("""
        SELECT COALESCE(SUM(duration),0) FROM blocks
        WHERE user_id=? AND completed=1
    """, (uid,)).fetchone()[0]

    rows = db.execute("""
        SELECT DISTINCT DATE(created_at)
        FROM blocks
        WHERE user_id=? AND completed=1
        ORDER BY DATE(created_at) DESC
    """, (uid,)).fetchall()

    dates = [row[0] for row in rows]

    today = date.today()
    streak = 0

    for i, d in enumerate(dates):
        if d == (today - timedelta(days=i)).isoformat():
            streak += 1
        else:
            break

    stats = {
        "done_blocks": done_blocks,
        "total_mins": total_mins
    }

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        streak=streak
    )


@app.route("/analytics")
@login_required
def analytics():
    user = get_current_user()
    uid = user["id"]
    db = get_db()

    # ===== ALL-TIME =====
    total_mins = db.execute("""
        SELECT COALESCE(SUM(duration),0)
        FROM blocks
        WHERE user_id=? AND completed=1
    """, (uid,)).fetchone()[0]

    total_blocks = db.execute("""
        SELECT COUNT(*)
        FROM blocks
        WHERE user_id=? AND completed=1
    """, (uid,)).fetchone()[0]

    # ===== STREAK =====
    rows = db.execute("""
        SELECT DISTINCT DATE(created_at)
        FROM blocks
        WHERE user_id=? AND completed=1
        ORDER BY DATE(created_at) DESC
    """, (uid,)).fetchall()

    dates = [row[0] for row in rows]

    today = date.today()
    streak = 0

    for i, d in enumerate(dates):
        if d == (today - timedelta(days=i)).isoformat():
            streak += 1
        else:
            break

    # ===== HÔM NAY =====
    today_str = today.isoformat()

    today_mins = db.execute("""
        SELECT COALESCE(SUM(duration),0)
        FROM blocks
        WHERE user_id=? AND completed=1
        AND DATE(created_at)=?
    """, (uid, today_str)).fetchone()[0]

    efficiency = int((today_mins / user["daily_goal"]) * 100) if user["daily_goal"] else 0
    efficiency = min(efficiency, 100)

    stats = {
        "today_mins": today_mins,
        "efficiency": efficiency
    }

    # ===== CHART 7 NGÀY =====
    chart = []
    for i in range(6, -1, -1):
        day = (today - timedelta(days=i)).isoformat()

        mins = db.execute("""
            SELECT COALESCE(SUM(duration),0)
            FROM blocks
            WHERE user_id=? AND completed=1
            AND DATE(created_at)=?
        """, (uid, day)).fetchone()[0]

        chart.append({
            "date": day,
            "minutes": mins
        })

    return render_template(
        "analytics.html",
        user=user,
        streak=streak,
        total_mins=total_mins,
        total_blocks=total_blocks,
        stats=stats,
        chart=chart
    )


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = get_current_user()

    if request.method == "POST":
        daily_goal = int(request.form.get("daily_goal", 120))
        get_db().execute(
            "UPDATE users SET daily_goal=? WHERE id=?",
            (daily_goal, user["id"])
        )
        get_db().commit()
        flash("Đã lưu mục tiêu.", "success")
        return redirect(url_for("settings"))

    return render_template("settings.html", user=user)


@app.route("/help")
@login_required
def help_page():
    user = get_current_user()
    return render_template("help.html", user=user)


# ================= API =================

@app.route("/api/stats")
@login_required
def api_stats():
    uid = session["user_id"]
    user = get_current_user()
    db = get_db()

    today = date.today().isoformat()

    today_mins = db.execute("""
        SELECT COALESCE(SUM(duration),0)
        FROM blocks
        WHERE user_id=? AND completed=1
        AND DATE(created_at)=?
    """, (uid, today)).fetchone()[0]

    blocks_done = db.execute("""
        SELECT COUNT(*)
        FROM blocks
        WHERE user_id=? AND completed=1
        AND DATE(created_at)=?
    """, (uid, today)).fetchone()[0]

    efficiency = int((today_mins / user["daily_goal"]) * 100) if user["daily_goal"] else 0
    efficiency = min(efficiency, 100)

    return jsonify({
        "today_mins": today_mins,
        "today_goal": user["daily_goal"],
        "blocks_done": blocks_done,
        "efficiency": efficiency
    })


@app.route("/api/blocks", methods=["GET", "POST"])
@login_required
def api_blocks():
    uid = session["user_id"]
    db = get_db()

    if request.method == "POST":
        data = request.get_json()
        duration = int(data.get("duration", 25))

        db.execute("""
            INSERT INTO blocks (user_id, duration, completed)
            VALUES (?, ?, 0)
        """, (uid, duration))

        db.commit()
        return jsonify({"success": True})

    blocks = db.execute("""
        SELECT id, duration, completed, created_at
        FROM blocks
        WHERE user_id=?
        ORDER BY created_at DESC
    """, (uid,)).fetchall()

    return jsonify([dict(b) for b in blocks])


@app.route("/api/blocks/<int:block_id>/complete", methods=["POST"])
@login_required
def api_complete_block(block_id):
    uid = session["user_id"]

    get_db().execute("""
        UPDATE blocks
        SET completed=1
        WHERE id=? AND user_id=?
    """, (block_id, uid))

    get_db().commit()
    return jsonify({"success": True})


@app.route("/api/blocks/<int:block_id>", methods=["DELETE"])
@login_required
def api_delete_block(block_id):
    uid = session["user_id"]

    get_db().execute("""
        DELETE FROM blocks
        WHERE id=? AND user_id=?
    """, (block_id, uid))

    get_db().commit()
    return jsonify({"success": True})


@app.route("/api/analytics")
@login_required
def api_analytics():
    uid = session["user_id"]
    db = get_db()

    result = []
    for i in range(6, -1, -1):
        day = (date.today() - timedelta(days=i)).isoformat()

        mins = db.execute("""
            SELECT COALESCE(SUM(duration),0)
            FROM blocks
            WHERE user_id=? AND completed=1
            AND DATE(created_at)=?
        """, (uid, day)).fetchone()[0]

        result.append({
            "date": day,
            "minutes": mins
        })

    return jsonify(result)


# ================= AUTH PAGES =================

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = get_db().execute(
            "SELECT * FROM users WHERE email=?",
            (email,)
        ).fetchone()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Sai email hoặc mật khẩu.", "error")
            return render_template("login.html")

        session.clear()
        session["user_id"] = user["id"]
        return redirect(url_for("dashboard"))

    return render_template("login.html")

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        full_name = request.form.get("full_name", "").strip()

        if password != confirm:
            flash("Mật khẩu không khớp.", "error")
            return render_template("register.html")

        try:
            get_db().execute(
                "INSERT INTO users (email, password_hash, full_name) VALUES (?,?,?)",
                (email, generate_password_hash(password), full_name)
            )
            get_db().commit()
        except sqlite3.IntegrityError:
            flash("Email đã tồn tại.", "error")
            return render_template("register.html")

        flash("Đăng ký thành công!", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ================= CHAT (GPT-4o-mini) =================

@app.route("/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json()
    message = data.get("message", "")
    mode = data.get("mode", "motivate")

    if not message:
        return jsonify({"error": "Tin nhắn trống."}), 400

    try:
        system_prompt = """
Bạn là AI Mentor của FocusFlow.
Phong cách: ngắn gọn, rõ ràng, động viên, tập trung vào hành động.
Không lan man.
"""

        if mode == "plan":
            system_prompt += "Hãy giúp người dùng lập kế hoạch cụ thể từng bước."
        elif mode == "focus":
            system_prompt += "Hãy hướng dẫn người dùng bắt đầu deep focus ngay."
        else:
            system_prompt += "Hãy động viên và thúc đẩy người dùng hành động."

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            temperature=0.7
        )

        reply = response.choices[0].message.content

        return jsonify({"reply": reply})

    except Exception as e:
        print("GPT ERROR:", e)
        return jsonify({"error": "Không kết nối được AI."}), 500

if __name__ == "__main__":
    app.run(debug=True)
    
@app.route("/test")
def test():
    return "OK"