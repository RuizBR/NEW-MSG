# Team Chatbox — Website Version

This is the plain-website version of your Streamlit chat app. It's a small Flask
backend (keeps the same SQLite databases and logic you had) plus a real
HTML/CSS/JS frontend, instead of a Streamlit script.

## Why not a single `.html` file?

A static HTML file can't run a database, check passwords, store files, or track
who's online — that all has to happen on a server. This project is the
minimal, "normal website" equivalent: one small Python server (`app.py`) plus
plain HTML/CSS/JS. There is no Streamlit involved anymore.

## Project structure

```
chatapp/
├── app.py              # Flask backend (all API routes + serves the page)
├── requirements.txt
├── templates/
│   └── index.html       # The single page (login/register + chat UI)
└── static/
    ├── style.css
    └── script.js         # Polls the server every 2s, handles all UI logic
```

## Running locally

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000 in your browser.

The same three SQLite files as before (`users.db`, `chat_fixed.db`,
`video_call.db`) are created automatically in the working directory the first
time you run it.

## Deploying

Since this is now a normal Flask app (not Streamlit), you can deploy it to any
standard Python host, e.g. Render, Railway, PythonAnywhere, Fly.io, or a VPS
with gunicorn:

```bash
gunicorn -w 2 -b 0.0.0.0:8000 app:app
```

Add `gunicorn` to `requirements.txt` if your host needs it explicitly.

## Notes / things you may want to change before going to production

- `app.secret_key` in `app.py` is a placeholder — set it to a long random
  string (e.g. via an environment variable) before deploying publicly.
- Passwords are hashed with Werkzeug's `generate_password_hash` (stronger than
  the raw SHA-256 the original script used).
- SQLite works fine for a small team but isn't ideal under heavy concurrent
  write load — if this grows, consider Postgres.
- File uploads/downloads are stored as BLOBs in SQLite, same as before; for
  large files or many users, consider storing them on disk or in object
  storage (S3, etc.) instead.
- The video call feature still uses the free public Jitsi Meet
  (`meet.jit.si`) rooms, same as your original script.
