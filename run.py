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


def open_app_window(url):
    """Open AgentJ in its own Chrome app window (no tabs/address bar) so it can keep listening
    for "AgentJ" while you work in your normal Chrome. Falls back to the default browser."""
    import subprocess
    candidates = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    else:
        candidates += ["/usr/bin/google-chrome", "/usr/bin/chromium"]
    for exe in candidates:
        if os.path.exists(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--window-size=1440,900"])
                return
            except OSError:
                pass
    webbrowser.open(url)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    load_env(os.path.join(here, ".env"))
    sys.path.insert(0, here)
    from jarvis.server import serve

    port = int(os.environ.get("AGENTJ_PORT", "8765"))
    url = f"http://127.0.0.1:{port}"
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: open_app_window(url)).start()
    serve(port)
