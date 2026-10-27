"""Local dashboard + JSON API (standard library only). Listens on 127.0.0.1 only."""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import db, llm, worker
from .agents import browser as browser_agent

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _mask(key):
    return (key[:4] + "…" + key[-4:]) if len(key) > 10 else ("set" if key else "")


def plan_from_text(text):
    """Turn a pasted to-do list into separate tasks."""
    lines = [re.sub(r"^\s*([-*•]|\d+[.)])\s*", "", l).strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    if os.environ.get("AGENTJ_FAKE_LLM") == "1":
        return [{"title": l, "type": "auto", "priority": 2} for l in lines]
    try:
        raw = llm.generate(
            "Split this to-do list into separate, clear tasks for an AI assistant. "
            "For each return title (short imperative), details (anything useful, may be empty), "
            "type (one of: brainstorm, seo, browser, research, write) and priority (1 high, 2 normal, 3 low). "
            "Return ONLY a JSON array.\n\nTO-DO LIST:\n" + text,
            temperature=0.2,
        )
        m = re.search(r"\[.*\]", raw, re.S)
        items = json.loads(m.group(0)) if m else []
        out = []
        for it in items:
            if isinstance(it, dict) and it.get("title"):
                out.append({
                    "title": str(it["title"])[:300],
                    "details": str(it.get("details", ""))[:4000],
                    "type": it.get("type") if it.get("type") in db.TYPES else "auto",
                    "priority": int(it.get("priority", 2)) if str(it.get("priority", 2)).isdigit() else 2,
                })
        if out:
            return out
    except Exception:
        pass
    return [{"title": l, "type": "auto", "priority": 2} for l in lines]


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
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _same_origin(self):
        # block other websites from poking the local API from your browser
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return origin.endswith("//" + host)

    # ---------- routes ----------
    def do_GET(self):
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
                "chrome": browser_agent._cdp_alive(s.get("chrome_cdp_url", "")) if s.get("chrome_mode") == "cdp" else "system profile",
            })
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._same_origin():
            return self._send(403, {"error": "forbidden"})
        path = self.path.split("?")[0]
        b = self._body()

        if path == "/api/tasks":
            if not str(b.get("title", "")).strip():
                return self._send(400, {"error": "title required"})
            t = db.create_task(b["title"], b.get("details", ""), b.get("type", "auto"),
                               b.get("priority", 2), b.get("repeat", ""), b.get("due_date", ""))
            return self._send(201, t)

        if path == "/api/plan":
            items = plan_from_text(str(b.get("text", "")))
            created = [db.create_task(i["title"], i.get("details", ""), i.get("type", "auto"), i.get("priority", 2))
                       for i in items]
            return self._send(201, created)

        if path == "/api/settings":
            vals = {k: v for k, v in b.items() if k in db.DEFAULT_SETTINGS}
            if "gemini_api_key" in vals and ("…" in vals["gemini_api_key"] or vals["gemini_api_key"] == "set"):
                vals.pop("gemini_api_key")  # unchanged masked value
            db.save_settings(vals)
            llm._model_cache.clear()
            return self._send(200, {"ok": True})

        if path == "/api/settings/test":
            try:
                return self._send(200, {"ok": True, "message": llm.test_connection()})
            except Exception as e:
                return self._send(200, {"ok": False, "message": str(e)})

        if path == "/api/worker":
            db.save_settings({"worker_paused": "1" if b.get("paused") else "0"})
            return self._send(200, {"ok": True})

        m = re.fullmatch(r"/api/tasks/(\d+)/(approve|redo|cancel|update|requeue)", path)
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
                fb = str(b.get("feedback", "")).strip()
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
            if action == "update":
                fields = {k: b[k] for k in ("title", "details", "type", "priority", "repeat", "due_date") if k in b}
                return self._send(200, db.update_task(tid, **fields))
        return self._send(404, {"error": "not found"})

    def do_DELETE(self):
        if not self._same_origin():
            return self._send(403, {"error": "forbidden"})
        m = re.fullmatch(r"/api/tasks/(\d+)", self.path.split("?")[0])
        if m:
            db.delete_task(int(m.group(1)))
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})


def serve(port=8765):
    worker.start()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"\n  AgentJ is running →  http://127.0.0.1:{port}\n  (Close this window to stop it.)\n")
    httpd.serve_forever()
