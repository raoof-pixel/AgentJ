"""Local dashboard + JSON API (standard library only). Listens on 127.0.0.1 only."""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import db, llm, voice, worker
from .agents import browser as browser_agent
from .agents import match_playbook

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY = 1_000_000
FAKE = os.environ.get("AGENTJ_FAKE_LLM") == "1"


def _mask(key):
    return (key[:4] + "…" + key[-4:]) if len(key) > 10 else ("set" if key else "")


def _json_from(raw, opener="["):
    closer = "]" if opener == "[" else "}"
    m = re.search(re.escape(opener) + r".*" + re.escape(closer), raw or "", re.S)
    return json.loads(m.group(0)) if m else None


def _lines(text):
    out = [re.sub(r"^\s*([-*•]|\d+[.)])\s*", "", l).strip() for l in str(text).splitlines()]
    return [l for l in out if l]


def _clean_item(it):
    pb = None
    if it.get("playbook"):
        pb = next((p for p in db.list_playbooks() if p["name"].lower() == str(it["playbook"]).lower()), None)
    pb = pb or match_playbook(f"{it.get('title', '')} {it.get('details', '')}")
    return {
        "title": str(it.get("title", ""))[:300],
        "details": str(it.get("details", "") or "")[:4000],
        "type": it.get("type") if it.get("type") in db.TYPES else "auto",
        "priority": it.get("priority", 2),
        "playbook_id": pb["id"] if pb else None,
    }


def _playbook_names():
    pbs = db.list_playbooks()
    if not pbs:
        return "(none yet)"
    return "\n".join(f"- {p['name']} (triggers: {p.get('triggers') or '-'})" for p in pbs)


def plan_from_text(text):
    """Turn a pasted/spoken to-do list into separate tasks."""
    lines = _lines(text)
    if FAKE:
        return [_clean_item({"title": l}) for l in lines]
    try:
        raw = llm.generate(
            "Split this to-do list into separate, clear tasks for an AI assistant. "
            "For each return: title (short imperative), details (anything useful, may be empty), "
            "type (one of: brainstorm, seo, browser, desktop, research, write), priority (1 high, 2 normal, 3 low), "
            "and playbook (exact name of a matching saved playbook, or empty).\n"
            f"Saved playbooks:\n{_playbook_names()}\n"
            "Return ONLY a JSON array.\n\nTO-DO LIST:\n" + text,
            temperature=0.2,
        )
        items = _json_from(raw, "[") or []
        out = [_clean_item(it) for it in items if isinstance(it, dict) and it.get("title")]
        if out:
            return out
    except Exception:
        pass
    return [_clean_item({"title": l}) for l in lines]


def briefing():
    """A short spoken summary of the day."""
    today = db.now()[:10]
    tasks = db.list_tasks()
    review = [t for t in tasks if t["status"] == "review"]
    queued = [t for t in tasks if t["status"] == "queued" and (not t["due_date"] or t["due_date"] <= today)]
    done = [t for t in tasks if t["status"] == "done" and (t.get("finished_at") or t["updated_at"] or "")[:10] == today]
    cur = worker.current_task_id()
    parts = []
    if review:
        parts.append(f"{len(review)} result{'s' if len(review) != 1 else ''} waiting for your review, "
                     f"starting with {review[0]['title']}")
    if cur and db.get_task(cur):
        parts.append(f"I'm working on {db.get_task(cur)['title']}")
    if queued:
        nxt = ", ".join(t["title"] for t in sorted(queued, key=lambda t: (t["priority"], t["id"]))[:3])
        parts.append(f"{len(queued)} queued. Next up: {nxt}")
    if done:
        parts.append(f"{len(done)} done today")
    sched = [p for p in db.list_playbooks() if p.get("enabled") and p.get("schedule")
             and p.get("last_run_date") != today and p.get("run_time")]
    if sched:
        parts.append("Scheduled later: " + ", ".join(f"{p['name']} at {p['run_time']}" for p in sched[:3]))
    return ("Here's your day. " + ". ".join(parts) + ".") if parts else "Your list is clear. Tell me what to do."


def voice_command(text):
    """Understand a spoken command and act on it. Returns {reply, created}."""
    text = str(text or "").strip()
    if not text:
        return {"reply": "I didn't catch that.", "created": []}
    low = text.lower()
    # fast, offline handling of simple commands
    if re.search(r"\b(pause|stop working|hold on)\b", low) and len(low) < 40:
        db.save_settings({"worker_paused": "1"})
        return {"reply": "Paused. Say resume when you want me to continue.", "created": []}
    if re.search(r"\b(resume|continue|start working|carry on)\b", low) and len(low) < 40:
        db.save_settings({"worker_paused": "0"})
        return {"reply": "Resuming the queue.", "created": []}
    if re.search(r"\b(status|what(?:'s|s| is) (?:left|pending|remaining)|anything left|how many tasks|"
                 r"what are you (?:doing|working on))\b", low) and len(low) < 60:
        tasks = db.list_tasks()
        c = lambda s: sum(1 for t in tasks if t["status"] == s)
        cur = worker.current_task_id()
        doing = f" I'm working on: {db.get_task(cur)['title']}." if cur and db.get_task(cur) else ""
        return {"reply": f"{c('queued')} queued, {c('review')} waiting for your review, "
                         f"{c('failed')} failed.{doing}", "created": []}

    if re.search(r"\b(brief me|briefing|plan (?:for )?my day|my day|good morning|what'?s (?:on )?today)\b", low) and len(low) < 60:
        return {"reply": briefing(), "created": []}
    if re.search(r"^(never ?mind|cancel|nothing|stop listening|go to sleep)\b", low):
        return {"reply": "Okay.", "created": []}

    items, reply = None, ""
    if not FAKE:
        try:
            raw = llm.generate(
                "You are AgentJ, a voice-controlled assistant. The user said (speech-to-text, may have errors):\n"
                f"\"{text}\"\n\nSaved playbooks (repeatable procedures the user taught you):\n{_playbook_names()}\n\n"
                "Turn it into tasks. Return ONLY JSON: {\"reply\": \"one short spoken confirmation\", "
                "\"tasks\": [{\"title\": \"...\", \"details\": \"...\", \"type\": \"auto|brainstorm|seo|browser|desktop|research|write\", "
                "\"priority\": 1-3, \"playbook\": \"exact playbook name or empty\"}]}. "
                "If they mention a playbook by name or meaning, set playbook. Keep their details (URLs, numbers, names).",
                temperature=0.2,
            )
            data = _json_from(raw, "{") or {}
            items = [it for it in data.get("tasks", []) if isinstance(it, dict) and it.get("title")]
            reply = str(data.get("reply", ""))[:300]
        except Exception:
            items = None
    if not items:
        items = [{"title": l} for l in _lines(text)]
    created = []
    for it in items:
        c = _clean_item(it)
        created.append(db.create_task(c["title"], c["details"], c["type"], c["priority"], "", "", c["playbook_id"]))
    if not reply:
        reply = f"Added {len(created)} task{'s' if len(created) != 1 else ''}."
    return {"reply": reply, "created": created}


def teach_playbook(text):
    """Turn a spoken/typed explanation of a repeated task into a playbook draft (not saved)."""
    if FAKE:
        first = _lines(text)[0] if _lines(text) else "New playbook"
        return {"name": first[:60], "triggers": "", "type": "auto", "steps": text, "schedule": "", "run_time": ""}
    raw = llm.generate(
        "The user is explaining how to do a task they repeat. Turn it into a reusable playbook for an AI agent.\n"
        "Return ONLY JSON with: name (short), triggers (comma-separated phrases they might say to start it), "
        "type (browser for websites in Chrome, desktop for apps or files on the PC, else seo/brainstorm/research/write), "
        "steps (numbered, precise, keep every URL/name/number they gave; add a final step saying what to report), "
        "schedule (daily/weekdays/weekly or empty), run_time (HH:MM 24h or empty).\n\n"
        f"Their explanation:\n{text}",
        temperature=0.2,
    )
    data = _json_from(raw, "{") or {}
    return {k: data.get(k, "") for k in ("name", "triggers", "type", "steps", "schedule", "run_time")}


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentJ"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    # ---------- helpers ----------
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if ctype.startswith("text/html"):
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'",
            )
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        if n > MAX_BODY:
            return None
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _host_ok(self):
        # protects against DNS-rebinding: only answer requests addressed to this machine
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in ("127.0.0.1", "localhost", "::1")

    def _write_allowed(self):
        """Block other websites open in your browser from changing anything here."""
        origin = self.headers.get("Origin")
        if origin and origin.rstrip("/") not in (f"http://{self.headers.get('Host', '')}",):
            return False
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            return False
        # forms from other sites can't send JSON without a CORS preflight (which we never approve)
        return (self.headers.get("Content-Type") or "").startswith("application/json")

    # ---------- routes ----------
    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            with open(os.path.join(STATIC, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if path == "/api/tasks":
            return self._send(200, db.list_tasks())
        m = re.fullmatch(r"/api/tasks/(\d+)", path)
        if m:
            t = db.get_task(int(m.group(1)))
            if not t:
                return self._send(404, {"error": "not found"})
            t["logs"] = db.get_logs(t["id"])
            return self._send(200, t)
        if path == "/api/playbooks":
            return self._send(200, db.list_playbooks())
        if path == "/api/settings":
            s = db.get_settings()
            s["gemini_api_key"] = _mask(s.get("gemini_api_key", ""))
            return self._send(200, s)
        if path == "/api/status":
            s = db.get_settings()
            return self._send(200, {
                "current": worker.current_task_id(),
                "paused": s.get("worker_paused") == "1",
                "provider": s.get("provider"),
                "has_key": bool(s.get("gemini_api_key")),
                "chrome": browser_agent.chrome_status(s),
                "chrome_mode": s.get("chrome_mode"),
                "speak": s.get("speak_replies") == "1",
                "voice_lang": s.get("voice_lang", "en-IN"),
                "wake_words": s.get("wake_words", ""),
                "notify": s.get("notify") == "1",
                "voice": voice_state(s),
            })
        if path == "/api/voice/state":
            return self._send(200, voice_state())
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok() or not self._write_allowed():
            return self._send(403, {"error": "forbidden"})
        path = self.path.split("?")[0]
        b = self._body()
        if b is None:
            return self._send(413, {"error": "too large"})

        if path == "/api/tasks":
            if not str(b.get("title", "")).strip():
                return self._send(400, {"error": "title required"})
            pb_id = b.get("playbook_id")
            pb = db.get_playbook(int(pb_id)) if str(pb_id or "").isdigit() else match_playbook(
                f"{b.get('title', '')} {b.get('details', '')}")
            t = db.create_task(b["title"], b.get("details", ""), b.get("type", "auto"),
                               b.get("priority", 2), b.get("repeat", ""), b.get("due_date", ""),
                               pb["id"] if pb else None)
            return self._send(201, t)

        if path == "/api/plan":
            items = plan_from_text(str(b.get("text", "")))
            created = [db.create_task(i["title"], i["details"], i["type"], i["priority"], "", "", i["playbook_id"])
                       for i in items]
            return self._send(201, created)

        if path == "/api/voice/wake":
            on = bool(b.get("on"))
            db.save_settings({"wake_on": "1" if on else "0"})
            vs = voice_state()
            if vs.get("engine") == "local":
                svc = voice.service(_voice_handler)
                svc.start() if on else svc.stop()
            return self._send(200, voice_state())

        if path == "/api/voice/ptt":
            vs = voice_state()
            if vs.get("engine") != "local":
                return self._send(200, {"engine": "browser"})
            voice.service(_voice_handler).push_to_talk()
            return self._send(200, voice_state())

        if path == "/api/voice":
            return self._send(200, voice_command(b.get("text", "")))

        if path == "/api/playbooks/draft":
            try:
                return self._send(200, teach_playbook(str(b.get("text", ""))))
            except Exception as e:
                return self._send(200, {"error": str(e)})

        if path == "/api/playbooks":
            try:
                return self._send(201, db.create_playbook(**b))
            except ValueError as e:
                return self._send(400, {"error": str(e)})

        m = re.fullmatch(r"/api/playbooks/(\d+)/(update|run|delete)", path)
        if m:
            pid, action = int(m.group(1)), m.group(2)
            pb = db.get_playbook(pid)
            if not pb:
                return self._send(404, {"error": "not found"})
            if action == "update":
                return self._send(200, db.update_playbook(pid, **b))
            if action == "delete":
                db.delete_playbook(pid)
                return self._send(200, {"ok": True})
            t = db.create_task(pb["name"], str(b.get("details", "")), pb.get("type") or "auto", 1, "", "", pid)
            db.log(t["id"], f"Started from the '{pb['name']}' playbook")
            return self._send(201, t)

        if path == "/api/settings":
            vals = {k: v for k, v in b.items() if k in db.DEFAULT_SETTINGS}
            if "gemini_api_key" in vals and ("…" in str(vals["gemini_api_key"]) or vals["gemini_api_key"] == "set"):
                vals.pop("gemini_api_key")  # unchanged masked value
            db.save_settings(vals)
            llm._model_cache.clear()
            svc = voice.service()
            if svc:
                if "whisper_model" in vals:
                    svc._whisper = None  # reload with the new size on next use
                if vals.get("voice_engine") == "browser":
                    svc.stop()
            browser_agent._status_cache["t"] = 0
            return self._send(200, {"ok": True})

        if path == "/api/settings/test":
            try:
                return self._send(200, {"ok": True, "message": llm.test_connection()})
            except Exception as e:
                return self._send(200, {"ok": False, "message": str(e)})

        if path == "/api/worker":
            db.save_settings({"worker_paused": "1" if b.get("paused") else "0"})
            return self._send(200, {"ok": True})

        m = re.fullmatch(r"/api/tasks/(\d+)/(approve|redo|cancel|update|requeue|delete)", path)
        if m:
            tid, action = int(m.group(1)), m.group(2)
            t = db.get_task(tid)
            if not t:
                return self._send(404, {"error": "not found"})
            if action == "approve":
                db.update_task(tid, status="done")
                db.log(tid, "Approved by you")
                nxt = worker.schedule_repeat(t)
                return self._send(200, {"ok": True, "next": nxt})
            if action == "redo":
                fb = str(b.get("feedback", "")).strip()[:4000]
                db.update_task(tid, status="queued", feedback=fb)
                db.log(tid, f"Sent back for redo. Feedback: {fb or '(none)'}")
                return self._send(200, {"ok": True})
            if action == "requeue":
                db.update_task(tid, status="queued")
                return self._send(200, {"ok": True})
            if action == "cancel":
                db.update_task(tid, status="cancelled")
                db.log(tid, "Cancelled by you")
                return self._send(200, {"ok": True})
            if action == "delete":
                db.delete_task(tid)
                return self._send(200, {"ok": True})
            if action == "update":
                fields = {k: b[k] for k in ("title", "details", "priority", "due_date") if k in b}
                if b.get("type") in db.TYPES:
                    fields["type"] = b["type"]
                if b.get("repeat") in db.REPEATS:
                    fields["repeat"] = b["repeat"]
                return self._send(200, db.update_task(tid, **fields))
        return self._send(404, {"error": "not found"})


def voice_state(s=None):
    s = s or db.get_settings()
    svc = voice.service()
    if s.get("voice_engine") != "local":
        return {"engine": "browser"}
    missing = voice.missing_packages()
    if missing:
        return {"engine": "browser", "missing": missing,
                "note": "Local voice isn't installed yet, so Chrome's speech is used. Run install.bat to add it."}
    snap = svc.snapshot() if svc else {"engine": "local", "state": "off", "heard": "", "reply": "", "error": "",
                                        "level": 0, "tts": False}
    snap["wake_on"] = s.get("wake_on") == "1"
    return snap


def _voice_handler(text):
    return voice_command(text).get("reply", "Done.")


def serve(port=8765):
    worker.start()
    voice.service(_voice_handler)
    s = db.get_settings()
    if s.get("voice_engine") == "local" and s.get("wake_on") == "1" and not voice.missing_packages():
        voice.service().start()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"\n  AgentJ is running →  http://127.0.0.1:{port}\n  (Close this window to stop it.)\n")
    httpd.serve_forever()
