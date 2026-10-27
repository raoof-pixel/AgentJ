"""Task router: decides which agent handles a task and runs it."""

import re

from .. import db, llm
from . import brainstorm, browser, research, seo, write

AGENTS = {
    "brainstorm": brainstorm.run,
    "seo": seo.run,
    "browser": browser.run,
    "research": research.run,
    "write": write.run,
}

URL_RE = re.compile(r"(https?://[^\s)>\]]+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|ca|org|net|io|ai|co|in|store|dev)\b[^\s]*)", re.I)

KEYWORDS = [
    ("seo", r"\bseo\b|site audit|meta (title|description)|page ?speed|backlink|keyword rank"),
    ("brainstorm", r"brain ?storm|\bideas\b|name ideas|\bangles\b"),
    ("browser", r"youtube|\bchrome\b|go to |open (the )?(site|website|page)|log ?in|upload|search console|analytics|click|subscribe|comment on|reply to|check my (channel|inbox|dashboard)"),
    ("research", r"research|find out|compare|latest|news|competitor|look up|what is|who is"),
    ("write", r"\bwrite\b|draft|email|caption|post|article|blog|script|copy\b|rewrite|summari[sz]e"),
]


def classify(task):
    text = f"{task['title']} {task.get('details', '')}".lower()
    for kind, pattern in KEYWORDS:
        if re.search(pattern, text):
            return kind
    try:
        answer = llm.generate(
            "Classify this to-do item into exactly one word from: brainstorm, seo, browser, research, write.\n"
            "browser = needs to operate a website in Chrome (click, log in, read a dashboard).\n"
            "research = needs current info from the web but no clicking.\n"
            f"Task: {task['title']}\n{task.get('details', '')}\nAnswer with one word only.",
            temperature=0,
        ).strip().lower()
        for kind in AGENTS:
            if kind in answer:
                return kind
    except llm.LLMError:
        pass
    return "write"


def find_url(task):
    m = URL_RE.search(f"{task['title']} {task.get('details', '')}")
    if not m:
        return ""
    url = m.group(0).rstrip(".,;")
    return url if url.startswith("http") else "https://" + url


def system_prompt(task):
    s = db.get_settings()
    about = s.get("about_me", "").strip()
    lines = [
        "You are AgentJ, a sharp, practical personal assistant (Jarvis-style) for a busy business owner.",
        f"Today is {db.now()[:10]}.",
        "Be concrete and actionable. Use short markdown sections and bullet points. No filler.",
    ]
    if about:
        lines.append(f"About the user and their businesses:\n{about}")
    return "\n".join(lines)


def task_prompt(task):
    p = f"TASK: {task['title']}"
    if task.get("details"):
        p += f"\n\nDETAILS:\n{task['details']}"
    if task.get("feedback"):
        p += (
            f"\n\nThis is a redo. Your previous result was:\n---\n{task.get('result', '')[:6000]}\n---\n"
            f"The user's feedback on it:\n{task['feedback']}\nFix exactly what they asked."
        )
    return p


def run_task(task):
    kind = task["type"] if task["type"] != "auto" else (task.get("resolved_type") or classify(task))
    db.update_task(task["id"], resolved_type=kind)
    db.log(task["id"], f"Agent selected: {kind}")
    return AGENTS[kind](task, ctx={"system": system_prompt(task), "prompt": task_prompt(task), "url": find_url(task)})
