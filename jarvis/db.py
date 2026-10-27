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
TYPES = ("auto", "brainstorm", "seo", "browser", "desktop", "research", "write")

DEFAULT_SETTINGS = {
    "provider": "gemini",          # gemini | ollama
    "gemini_api_key": "",
    "gemini_model": "",            # empty = auto-pick the best available Flash model
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "qwen3:4b",
    "browser_provider": "gemini",  # browser tasks need a strong model; gemini recommended
    "chrome_mode": "own",          # own = your running Chrome; cdp = Jarvis Chrome window; system = main profile (Chrome closed)
    "chrome_cdp_url": "http://127.0.0.1:9222",
    "chrome_profile": "Default",
    "browser_max_steps": "25",
    # comma-separated sites the Chrome agent may open (empty = any). Wildcards like *.google.com work.
    "browser_allowed_domains": "",
    "desktop_max_steps": "20",
    "voice_engine": "local",       # local = offline wake word + Whisper + Kokoro on this PC; browser = Chrome speech
    "wake_on": "0",                # listen for the wake word
    "whisper_model": "base",       # tiny | base | small  (bigger = more accurate, slower)
    "tts_voice": "af_heart",       # Kokoro voice
    "about_me": "",
    "worker_paused": "0",
    "speak_replies": "1",          # AgentJ answers voice commands out loud
    "voice_lang": "en-IN",         # speech recognition language
    # what you say to wake it up; speech-to-text often hears "AgentJ" as "agent jay" etc.
    "wake_words": "agentj, agent j, agent jay, agent jae, hey agent, ajent j",
    "notify": "1",                 # desktop notification + chime when a task needs review
}

REPEATS = ("", "daily", "weekdays", "weekly")


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
        CREATE TABLE IF NOT EXISTS playbooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            triggers TEXT DEFAULT '',
            type TEXT DEFAULT 'auto',
            steps TEXT DEFAULT '',
            schedule TEXT DEFAULT '',
            run_time TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            last_run_date TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    cols = {r[1] for r in c.execute("PRAGMA table_info(tasks)").fetchall()}
    if "playbook_id" not in cols:
        c.execute("ALTER TABLE tasks ADD COLUMN playbook_id INTEGER DEFAULT NULL")
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

def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def create_task(title, details="", type="auto", priority=2, repeat="", due_date="", playbook_id=None):
    if type not in TYPES:
        type = "auto"
    if repeat not in REPEATS:
        repeat = ""
    priority = min(3, max(1, _int(priority, 2)))
    due_date = str(due_date or "")[:10]
    ts = now()
    with _lock:
        c = conn()
        cur = c.execute(
            "INSERT INTO tasks(title, details, type, priority, repeat, due_date, playbook_id, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (str(title).strip()[:500], str(details or "").strip()[:20000], type, priority, repeat, due_date,
             playbook_id, ts, ts),
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


TASK_COLUMNS = {"title", "details", "type", "resolved_type", "status", "priority", "repeat", "result",
                "feedback", "attempts", "started_at", "finished_at", "due_date", "playbook_id"}


def update_task(task_id, **fields):
    fields = {k: v for k, v in fields.items() if k in TASK_COLUMNS}  # column names are never user-controlled
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
    return json.dumps({"tasks": list_tasks(), "playbooks": list_playbooks()}, indent=2)


# ---------- playbooks (how to do repeated tasks) ----------

PLAYBOOK_COLUMNS = {"name", "triggers", "type", "steps", "schedule", "run_time", "enabled", "last_run_date"}


def _clean_playbook(f):
    out = {k: v for k, v in f.items() if k in PLAYBOOK_COLUMNS}
    if "type" in out and out["type"] not in TYPES:
        out["type"] = "auto"
    if "schedule" in out and out["schedule"] not in REPEATS:
        out["schedule"] = ""
    if "run_time" in out:
        rt = str(out["run_time"] or "")[:5]
        ok = len(rt) == 5 and rt[2] == ":" and rt.replace(":", "").isdigit() and int(rt[:2]) < 24 and int(rt[3:]) < 60
        out["run_time"] = rt if ok else ""
    if "enabled" in out:
        out["enabled"] = 1 if str(out["enabled"]) in ("1", "true", "True") else 0
    for k in ("name", "triggers", "steps"):
        if k in out:
            out[k] = str(out[k] or "")[:20000]
    return out


def create_playbook(**f):
    f = _clean_playbook(f)
    if not f.get("name", "").strip():
        raise ValueError("name required")
    f["created_at"] = f["updated_at"] = now()
    cols = ", ".join(f)
    with _lock:
        c = conn()
        cur = c.execute(f"INSERT INTO playbooks({cols}) VALUES({', '.join('?' * len(f))})", tuple(f.values()))
        c.commit()
        return get_playbook(cur.lastrowid)


def get_playbook(pid):
    with _lock:
        return _row(conn().execute("SELECT * FROM playbooks WHERE id=?", (pid,)).fetchone())


def list_playbooks():
    with _lock:
        return [dict(r) for r in conn().execute("SELECT * FROM playbooks ORDER BY name COLLATE NOCASE").fetchall()]


def update_playbook(pid, **f):
    f = _clean_playbook(f)
    if not f:
        return get_playbook(pid)
    f["updated_at"] = now()
    with _lock:
        c = conn()
        c.execute(f"UPDATE playbooks SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), pid))
        c.commit()
    return get_playbook(pid)


def delete_playbook(pid):
    with _lock:
        c = conn()
        c.execute("UPDATE tasks SET playbook_id=NULL WHERE playbook_id=?", (pid,))
        c.execute("DELETE FROM playbooks WHERE id=?", (pid,))
        c.commit()
