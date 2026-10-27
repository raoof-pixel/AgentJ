"""Background worker: runs one task at a time (kind to low-spec PCs)."""

import threading
import time
import traceback
from datetime import date, timedelta

from . import db
from .agents import run_task

_state = {"current": None, "thread": None}


def current_task_id():
    return _state["current"]


def schedule_repeat(task):
    """When a repeating task is approved, queue the next occurrence."""
    rep = task.get("repeat")
    if rep not in ("daily", "weekdays", "weekly"):
        return None
    d = date.today()
    step = 7 if rep == "weekly" else 1
    nxt = d + timedelta(days=step)
    if rep == "weekdays":
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
    return db.create_task(task["title"], task["details"], task["type"], task["priority"], rep, nxt.isoformat())


def _process(task):
    tid = task["id"]
    _state["current"] = tid
    db.update_task(tid, status="running", started_at=db.now(), attempts=task["attempts"] + 1)
    db.log(tid, f"▶ Started (attempt {task['attempts'] + 1})")
    try:
        result = run_task(db.get_task(tid))
        if db.get_task(tid)["status"] == "cancelled":
            db.log(tid, "Finished, but the task was cancelled - result discarded")
            return
        db.update_task(tid, status="review", result=result, finished_at=db.now())
        db.log(tid, "✔ Done - waiting for your review")
    except Exception as e:  # never let one task kill the worker
        db.log(tid, traceback.format_exc()[-2500:], "error")
        if db.get_task(tid)["status"] != "cancelled":
            db.update_task(tid, status="failed", result=f"**Failed:** {e}", finished_at=db.now())
    finally:
        _state["current"] = None


def _loop():
    db.reset_stuck_running()
    while True:
        try:
            if db.get_settings().get("worker_paused") != "1":
                task = db.next_queued()
                if task:
                    _process(task)
                    continue
        except Exception:
            traceback.print_exc()
        time.sleep(2)


def start():
    if _state["thread"] is None:
        t = threading.Thread(target=_loop, name="agentj-worker", daemon=True)
        t.start()
        _state["thread"] = t
