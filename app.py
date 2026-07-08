import sqlite3
import time
import random
import string
import base64
from datetime import datetime

from flask import Flask, request, jsonify, session, send_from_directory, Response
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = "change-this-to-a-random-secret-in-production"

USERS_DB = "users.db"
CHAT_DB = "chat_fixed.db"
VC_DB = "video_call.db"

ONLINE_TIMEOUT = 10     # seconds - matches the old Streamlit polling window
TYPING_TIMEOUT = 4      # seconds


# ================= DB HELPERS =================
def execute_write(db, query, params=(), retries=10, delay=0.2):
    while retries > 0:
        try:
            conn = sqlite3.connect(db, timeout=30, check_same_thread=False)
            cur = conn.cursor()
            cur.execute(query, params)
            conn.commit()
            last_id = cur.lastrowid
            cur.close()
            conn.close()
            return last_id
        except sqlite3.OperationalError:
            retries -= 1
            time.sleep(delay)
    return None


def execute_read(db, query, params=(), retries=10, delay=0.2):
    while retries > 0:
        try:
            conn = sqlite3.connect(db, timeout=30, check_same_thread=False)
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return rows
        except sqlite3.OperationalError:
            retries -= 1
            time.sleep(delay)
    return []


# ================= DB INIT =================
def init_users_db():
    execute_write(USERS_DB, """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT
        )
    """)


def init_chat_db():
    execute_write(CHAT_DB, """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            recipient TEXT,
            message TEXT,
            msg_type TEXT,
            file_name TEXT,
            file_data BLOB,
            timestamp TEXT
        )
    """)
    execute_write(CHAT_DB, """
        CREATE TABLE IF NOT EXISTS active_users (
            username TEXT PRIMARY KEY,
            last_seen INTEGER
        )
    """)
    execute_write(CHAT_DB, """
        CREATE TABLE IF NOT EXISTS typing_users (
            username TEXT PRIMARY KEY,
            last_typing INTEGER
        )
    """)


def init_video_db():
    execute_write(VC_DB, """
        CREATE TABLE IF NOT EXISTS video_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_name TEXT,
            started INTEGER,
            user1 TEXT,
            user2 TEXT,
            created_at TEXT
        )
    """)


init_users_db()
init_chat_db()
init_video_db()


# ================= AUTH HELPERS =================
def current_user():
    return session.get("username")


def login_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return jsonify({"error": "not authenticated"}), 401
        return fn(*args, **kwargs)

    return wrapper


# ================= PAGE ROUTE =================
@app.route("/")
def index():
    return send_from_directory("templates", "index.html")


# ================= AUTH ROUTES =================
@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"success": False, "message": "Username and password required"})

    existing = execute_read(USERS_DB, "SELECT username FROM users WHERE username=?", (username,))
    if existing:
        return jsonify({"success": False, "message": "Username already exists"})

    execute_write(USERS_DB, "INSERT INTO users VALUES (?,?)", (username, generate_password_hash(password)))
    return jsonify({"success": True, "message": "Registration successful!"})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    rows = execute_read(USERS_DB, "SELECT password_hash FROM users WHERE username=?", (username,))
    if rows and check_password_hash(rows[0][0], password):
        session["username"] = username
        return jsonify({"success": True, "username": username})
    return jsonify({"success": False, "message": "Invalid username or password"}), 401


@app.route("/api/logout", methods=["POST"])
def logout():
    username = current_user()
    if username:
        execute_write(CHAT_DB, "DELETE FROM active_users WHERE username=?", (username,))
        execute_write(CHAT_DB, "DELETE FROM typing_users WHERE username=?", (username,))
    session.clear()
    return jsonify({"success": True})


@app.route("/api/me")
def me():
    username = current_user()
    return jsonify({"logged_in": bool(username), "username": username})


# ================= USERS / PRESENCE =================
@app.route("/api/users")
@login_required
def list_users():
    rows = execute_read(USERS_DB, "SELECT username FROM users")
    users = [r[0] for r in rows if r[0] != current_user()]
    return jsonify({"users": users})


@app.route("/api/heartbeat", methods=["POST"])
@login_required
def heartbeat():
    username = current_user()
    execute_write(
        CHAT_DB,
        """
        INSERT INTO active_users VALUES (?,?)
        ON CONFLICT(username) DO UPDATE SET last_seen=excluded.last_seen
        """,
        (username, int(time.time())),
    )
    now = int(time.time())
    rows = execute_read(
        CHAT_DB,
        "SELECT username FROM active_users WHERE ? - last_seen <= ? ORDER BY username",
        (now, ONLINE_TIMEOUT),
    )
    online = [r[0] for r in rows]
    return jsonify({"online": online})


@app.route("/api/typing", methods=["POST", "GET"])
@login_required
def typing():
    username = current_user()
    if request.method == "POST":
        data = request.get_json(force=True)
        is_typing = data.get("typing", False)
        if is_typing:
            execute_write(
                CHAT_DB,
                """
                INSERT INTO typing_users VALUES (?,?)
                ON CONFLICT(username) DO UPDATE SET last_typing=excluded.last_typing
                """,
                (username, int(time.time())),
            )
        else:
            execute_write(CHAT_DB, "DELETE FROM typing_users WHERE username=?", (username,))
        return jsonify({"success": True})

    now = int(time.time())
    rows = execute_read(CHAT_DB, "SELECT username FROM typing_users WHERE ? - last_typing <= ?", (now, TYPING_TIMEOUT))
    typers = [r[0] for r in rows if r[0] != username]
    return jsonify({"typing": typers})


# ================= MESSAGES =================
@app.route("/api/messages")
@login_required
def get_messages():
    username = current_user()
    recipient = request.args.get("recipient", "")  # "" means public

    if recipient:
        query = """
            SELECT id, user, recipient, message, msg_type, file_name, timestamp
            FROM messages
            WHERE (user=? AND recipient=?) OR (user=? AND recipient=?)
            ORDER BY id
        """
        rows = execute_read(CHAT_DB, query, (username, recipient, recipient, username))
    else:
        query = """
            SELECT id, user, recipient, message, msg_type, file_name, timestamp
            FROM messages
            WHERE recipient IS NULL OR recipient=''
            ORDER BY id
        """
        rows = execute_read(CHAT_DB, query)

    messages = [
        {
            "id": r[0], "user": r[1], "recipient": r[2], "message": r[3],
            "msg_type": r[4], "file_name": r[5], "timestamp": r[6],
        }
        for r in rows
    ]
    return jsonify({"messages": messages})


@app.route("/api/messages", methods=["POST"])
@login_required
def send_message():
    username = current_user()
    data = request.get_json(force=True)
    message = (data.get("message") or "").strip()
    recipient = data.get("recipient") or None
    if not message:
        return jsonify({"success": False, "message": "Empty message"})

    execute_write(
        CHAT_DB,
        "INSERT INTO messages VALUES (NULL,?,?,?, 'text', NULL, NULL, ?)",
        (username, recipient, message, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    execute_write(CHAT_DB, "DELETE FROM typing_users WHERE username=?", (username,))
    return jsonify({"success": True})


@app.route("/api/upload", methods=["POST"])
@login_required
def upload_file():
    username = current_user()
    recipient = request.form.get("recipient") or None
    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "message": "No file provided"})

    execute_write(
        CHAT_DB,
        "INSERT INTO messages VALUES (NULL,?,?,NULL,'file',?,?,?)",
        (username, recipient, file.filename, file.read(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    return jsonify({"success": True})


@app.route("/api/download/<int:msg_id>")
@login_required
def download_file(msg_id):
    username = current_user()
    rows = execute_read(
        CHAT_DB,
        "SELECT user, recipient, file_name, file_data FROM messages WHERE id=? AND msg_type='file'",
        (msg_id,),
    )
    if not rows:
        return jsonify({"error": "not found"}), 404

    sender, recipient, file_name, file_data = rows[0]
    allowed = (
        recipient in (None, "")
        or recipient == username
        or sender == username
    )
    if not allowed:
        return jsonify({"error": "forbidden"}), 403

    return Response(
        file_data,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={file_name}"},
    )


@app.route("/api/clear", methods=["POST"])
@login_required
def clear_messages():
    username = current_user()
    data = request.get_json(force=True)
    recipient = data.get("recipient") or None

    if recipient is None:
        execute_write(CHAT_DB, "DELETE FROM messages WHERE recipient IS NULL OR recipient=''")
    else:
        execute_write(
            CHAT_DB,
            "DELETE FROM messages WHERE (user=? AND recipient=?) OR (user=? AND recipient=?)",
            (username, recipient, recipient, username),
        )
    return jsonify({"success": True})


# ================= VIDEO CALLS =================
@app.route("/api/video/status")
@login_required
def video_status():
    username = current_user()
    recipient = request.args.get("recipient", "")
    rows = execute_read(
        VC_DB,
        """
        SELECT room_name, started FROM video_calls
        WHERE (user1=? AND user2=?) OR (user1=? AND user2=?)
        ORDER BY id DESC LIMIT 1
        """,
        (username, recipient, recipient, username),
    )
    if rows:
        return jsonify({"room_name": rows[0][0], "started": rows[0][1]})
    return jsonify({"room_name": "", "started": 0})


@app.route("/api/video/start", methods=["POST"])
@login_required
def video_start():
    username = current_user()
    data = request.get_json(force=True)
    recipient = data.get("recipient")
    if not recipient:
        return jsonify({"success": False, "message": "recipient required"})

    room_name = f"PrivateCall_{username}_{recipient}_" + "".join(random.choices(string.ascii_letters + string.digits, k=4))
    execute_write(
        VC_DB,
        "INSERT INTO video_calls (room_name, started, user1, user2, created_at) VALUES (?,?,?,?,?)",
        (room_name, 1, username, recipient, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    return jsonify({"success": True, "room_name": room_name})


@app.route("/api/video/end", methods=["POST"])
@login_required
def video_end():
    data = request.get_json(force=True)
    room_name = data.get("room_name")
    execute_write(VC_DB, "UPDATE video_calls SET started=0 WHERE room_name=?", (room_name,))
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
