"""Start AgentJ:  python run.py  (then open http://127.0.0.1:8765)"""

import os
import sys
import threading
import webbrowser


def load_env(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    load_env(os.path.join(here, ".env"))
    sys.path.insert(0, here)
    from jarvis.server import serve

    port = int(os.environ.get("AGENTJ_PORT", "8765"))
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    serve(port)
