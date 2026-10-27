"""Local SQLite storage. Everything (tasks, logs, settings) lives in data/agentj.db."""

import json
import os
import sqlite3
import threading
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("AGENTJ_DATA_DIR", os.path.join(ROOT, "data"))
DB_PATH = os.path.join(DATA_DIR, "agentj.db")

_lock = threading.RLock()
_conn = None

STATUSES = ("queued", "running", "review", "done", "failed", "cancelled")
TYPES = ("auto", "brainstorm", "seo", "browser", "research", "write")

DEFAULT_SETTINGS = {
    "provider": "gemini",          # gemini | ollama
    "gemini_api_key": "",
    "gemini_model": "",            # empty = auto-pick the best available Flash model
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "qwen3:4b",
    "browser_provider": "gemini",  # browser tasks need a strong model; gemini recommended
    "chrome_mode": "cdp",          # cdp = Jarvis Chrome window (start-jarvis-chrome.bat); system = your main Chrome profile
    "chrome_cdp_url": "http://127.0.0.1:9222",
    "chrome_profile": "Default",
    "browser_max_steps": "25",
    "about_me": "",
    "worker_paused": "0",
}


def now():
    return datetime.now().isoformat(timespec="seconds")


def conn():
    global _conn
    with _lock:
        if _conn is None:
            os.makedirs(DATA_DIR, exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _init(_conn)
        return _conn


def _init(c):
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            details TEXT DEFAULT '',
            type TEXT DEFAULT 'auto',
            resolved_type TEXT DEFAULT '',
            status TEXT DEFAULT 'queued',
            priority INTEGER DEFAULT 2,
            repeat TEXT DEFAULT '',
            result TEXT DEFAULT '',
            feedback TEXT DEFAULT '',
            attempts INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            due_date TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            ts TEXT,
            level TEXT,
            message TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_logs_task ON logs(task_id);
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    c.commit()


def _row(r):
    return dict(r) if r is not None else None


# ---------- settings ----------

def get_settings():
    with _lock:
        rows = conn().execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in rows})
    # Environment variable wins for the API key if the dashboard field is empty
    if not s.get("gemini_api_key"):
        s["gemini_api_key"] = os.environ.get("GOOGLE_API_KEY", "")
    return s


def save_settings(values):
    with _lock:
        c = conn()
        for k, v in values.items():
            if k in DEFAULT_SETTINGS:
                c.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (k, str(v)),
                )
        c.commit()


# ---------- tasks ----------

def create_task(title, details="", type="auto", priority=2, repeat="", due_date=""):
    if type not in TYPES:
        type = "auto"
    ts = now()
    with _lock:
        c = conn()
        cur = c.execute(
            "INSERT INTO tasks(title, details, type, priority, repeat, due_date, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (title.strip(), details.strip(), type, int(priority), repeat, due_date, ts, ts),
        )
        c.commit()
        return get_task(cur.lastrowid)


def get_task(task_id):
    with _lock:
        return _row(conn().execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())


def list_tasks():
    with _lock:
        rows = conn().execute(
            "SELECT * FROM tasks ORDER BY "
            "CASE status WHEN 'running' THEN 0 WHEN 'review' THEN 1 WHEN 'queued' THEN 2 "
            "WHEN 'failed' THEN 3 ELSE 4 END, priority ASC, id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_task(task_id, **fields):
    if not fields:
        return get_task(task_id)
    fields["updated_at"] = now()
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock:
        c = conn()
        c.execute(f"UPDATE tasks SET {cols} WHERE id=?", (*fields.values(), task_id))
        c.commit()
    return get_task(task_id)


def delete_task(task_id):
    with _lock:
        c = conn()
        c.execute("DELETE FROM logs WHERE task_id=?", (task_id,))
        c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        c.commit()


def next_queued():
    with _lock:
        r = conn().execute(
            "SELECT * FROM tasks WHERE status='queued' AND (due_date='' OR due_date<=?) "
            "ORDER BY priority ASC, id ASC LIMIT 1",
            (now()[:10],),
        ).fetchone()
    return _row(r)


def reset_stuck_running():
    """Tasks left 'running' after a crash/restart go back to the queue."""
    with _lock:
        c = conn()
        c.execute("UPDATE tasks SET status='queued' WHERE status='running'")
        c.commit()


# ---------- logs ----------

def log(task_id, message, level="info"):
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO logs(task_id, ts, level, message) VALUES(?,?,?,?)",
            (task_id, now(), level, str(message)[:4000]),
        )
        c.commit()


def get_logs(task_id, limit=500):
    with _lock:
        rows = conn().execute(
            "SELECT ts, level, message FROM logs WHERE task_id=? ORDER BY id ASC LIMIT ?",
            (task_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def export_all():
    return json.dumps({"tasks": list_tasks()}, indent=2)
