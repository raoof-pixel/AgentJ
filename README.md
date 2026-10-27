# AgentJ — your local Jarvis

A lightweight personal agent that runs on **your own PC**. You give it your to-do list, it works through the tasks one by one, and everything lands in **Needs review** so you can approve it or send it back with feedback.

- **Local-first:** tasks, results, logs and settings are stored in `data/agentj.db` on your computer. No account and no cloud database.
- **Light:** the dashboard and most agents use only Python's standard library, so there's no heavy framework and it uses very little memory.
- **Hybrid brain:** Gemini (free API key) does the thinking, which is fast and works well on PCs without a graphics card. Ollama is supported if you want fully offline text tasks.

## What it can do

| Agent | Use it for | How it works |
|---|---|---|
| **Brainstorm** | Video ideas, content angles, names, plans | Structured ideas, then top picks, then next steps |
| **SEO** | "SEO audit of canadiansme.ca" | Fetches the page, runs 16 on-page checks, robots.txt, sitemap and Google PageSpeed (mobile), then writes a prioritised fix list with a rewritten title and meta description |
| **Browser** | YouTube Studio, Search Console, any website | Uses [browser-use](https://github.com/browser-use/browser-use) (MIT) to operate a real Chrome window |
| **Research** | "Latest small-business grants in Ontario" | Gemini with Google Search grounding, with sources |
| **Write** | Emails, posts, captions, summaries | Finished drafts, ready to use |

You can pick the type yourself or leave it on **Auto**. You can also paste your whole day under **Paste to-do list** and AgentJ splits it into tasks.

Other features: priorities, repeating tasks (daily, weekdays or weekly; the next copy is queued when you approve one), a live activity log, Redo with feedback, and Pause/Resume.

## Setup (Windows, about 5 minutes)

1. Install **Python 3.12** from https://www.python.org/downloads/ and tick **"Add python.exe to PATH"**.
2. Download this repo (Code → Download ZIP) and unzip it, or `git clone` it.
3. Double-click **`install.bat`**.
4. Double-click **`start.bat`**. The dashboard opens at http://127.0.0.1:8765.
5. Click **Settings**, paste a free Gemini key from https://aistudio.google.com/apikey, then click **Test connection**.
6. Fill in **About you** (your businesses, websites, channels, tone). Every agent reads it.

### Chrome tasks

Double-click **`start-jarvis-chrome.bat`**. It opens a separate "Jarvis" Chrome window with its own profile:

- Log in to YouTube, Search Console and other sites **once** in that window. The logins are saved in `data/chrome-profile`.
- Your normal Chrome isn't touched and can stay open.
- Keep the Jarvis window open while Chrome tasks run. You can watch the agent work.

To use your **main** Chrome profile with all its existing logins, change **Settings → Chrome tasks use** to "My main Chrome profile". In that mode Chrome must be fully closed while a task runs.

**Safety:** the browser agent is told it may browse, read and fill drafts, but it must **never** publish, post, send, delete, buy or change settings. When a task needs one of those actions, it stops and reports `NEEDS APPROVAL: …` so you can do the final click yourself. It also never types passwords.

## Example tasks

- `SEO audit of https://canadiansme.ca`
- `Brainstorm 10 YouTube video ideas for small business owners in Canada`
- `Open YouTube Studio and summarise the last 7 days of analytics for my channel` (Browser)
- `Research what competitors of B2Bprint.ca charge for retractable banners`
- `Draft a LinkedIn post announcing the Small Business Summit 2026`

## Optional: fully offline text tasks

Install [Ollama](https://ollama.com) and run `ollama pull qwen3:4b`. Then set **Settings → Text tasks use → Ollama**. With 24 GB of RAM and no GPU this works, but expect a few words per second. Keep the browser agent on Gemini, because small local models often fail at multi-step website tasks.

## How it's built

```
run.py                     start server + open dashboard
jarvis/
  server.py                local web dashboard + JSON API (127.0.0.1 only)
  worker.py                runs one task at a time, handles repeats
  db.py                    SQLite storage (data/agentj.db)
  llm.py                   Gemini (REST) + Ollama, auto-picks newest Gemini Flash model
  agents/
    __init__.py            router (keyword rules, then AI classification)
    brainstorm.py  seo.py  browser.py  research.py  write.py
  static/index.html        the dashboard (single file, no build step)
```

Open-source projects reviewed for this build:

- **[browser-use](https://github.com/browser-use/browser-use):** used for the Chrome agent. It's the most widely used open-source browser agent and supports Gemini and Ollama.
- **[OpenJarvis](https://github.com/open-jarvis/OpenJarvis)** (Stanford): good local-first agent ideas, but much heavier and built around local models that would be slow on a PC without a GPU.
- **LightClaw:** a self-hosted assistant whose chat integrations are aimed at Chinese platforms. Only its "skills + review" idea was borrowed here.

## Adding a new agent

Create `jarvis/agents/myagent.py` with a `run(task, ctx)` function that returns markdown. Then register it in `jarvis/agents/__init__.py` (in `AGENTS` and `KEYWORDS`) and add the type to `TYPES` in `db.py`.
