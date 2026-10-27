"""Background worker: runs one task at a time (kind to low-spec PCs)."""

import threading
import time
import traceback
from datetime import date, datetime, timedelta

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
    return db.create_task(task["title"], task["details"], task["type"], task["priority"], rep, nxt.isoformat(),
                          task.get("playbook_id"))


def _playbook_due(pb, now_dt):
    sched = pb.get("schedule")
    if not pb.get("enabled") or sched not in ("daily", "weekdays", "weekly"):
        return False
    today = now_dt.date().isoformat()
    if pb.get("last_run_date") == today:
        return False
    if sched == "weekdays" and now_dt.weekday() >= 5:
        return False
    if sched == "weekly":
        created = (pb.get("created_at") or today)[:10]
        try:
            if date.fromisoformat(created).weekday() != now_dt.weekday():
                return False
        except ValueError:
            return False
    run_time = pb.get("run_time") or "00:00"
    return now_dt.strftime("%H:%M") >= run_time


def run_scheduled_playbooks(now_dt=None):
    """Queue today's run of every scheduled playbook whose time has come."""
    now_dt = now_dt or datetime.now()
    made = []
    for pb in db.list_playbooks():
        if _playbook_due(pb, now_dt):
            db.update_playbook(pb["id"], last_run_date=now_dt.date().isoformat())
            t = db.create_task(pb["name"], "", pb.get("type") or "auto", 2, "", "", pb["id"])
            db.log(t["id"], f"Created automatically by the '{pb['name']}' playbook schedule")
            made.append(t)
    return made


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
    last_sched = 0
    while True:
        try:
            if time.time() - last_sched > 30:
                last_sched = time.time()
                run_scheduled_playbooks()
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
