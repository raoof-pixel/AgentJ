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

### Talk to it

Click 🎙 (or press **Alt+J**), say what you want, then click **Done**. For example:

- "Do an SEO audit of b2bprint.ca and brainstorm five blog ideas" adds two tasks.
- "Run my YouTube comments playbook" starts that playbook.
- "What's left?", "Pause" and "Resume" control the queue.

AgentJ answers out loud. You can turn that off and choose your language in Settings → Voice. Voice uses Chrome's built-in speech recognition, so open the dashboard in Chrome or Edge and allow the microphone. Chrome processes the speech on Google's servers. Your tasks and results stay on your PC.

### Playbooks: teach it your repeated tasks

Open the **Playbooks** tab and click **New playbook**. Then press 🎙 and explain how you do the task, the way you'd explain it to a new assistant. Click **Turn into playbook** and AgentJ writes it up as:

- **Name and trigger phrases:** what you'll say to start it.
- **Agent:** Browser for anything done in Chrome.
- **Steps:** the agent follows these exactly. Edit them freely.
- **Schedule:** optional, for example weekdays at 09:30. It's added to Today's list automatically.

Any task, typed or spoken, that mentions a trigger phrase uses that playbook. You can also turn a good result into a playbook with **📘 Save as playbook**.

### Dashboard

- **Today** is your to-do list for the day, with a progress bar. Tasks show as ○ queued, ◐ running, ! needs your review and ✓ done.
- **Needs review** is where you approve a result or Redo it with feedback.
- Other features: priorities, repeating tasks, a live activity log, and Pause/Resume.

## Setup (Windows, about 5 minutes)

1. Install **Python 3.12** from https://www.python.org/downloads/ and tick **"Add python.exe to PATH"**.
2. Download this repo (Code → Download ZIP) and unzip it, or `git clone` it.
3. Double-click **`install.bat`**.
4. Double-click **`start.bat`**. The dashboard opens at http://127.0.0.1:8765.
5. Click **Settings**, paste a free Gemini key from https://aistudio.google.com/apikey, then click **Test connection**.
6. Fill in **About you** (your businesses, websites, channels, tone). Every agent reads it.

### Chrome tasks in your own Chrome

By default, AgentJ works in **your normal Chrome**, the one you're already using, with all your logins.

1. Update Chrome to version 144 or newer (Menu → Help → About Google Chrome).
2. In Chrome, open `chrome://inspect/#remote-debugging` and switch remote debugging **ON**. You only do this once.
3. When a Chrome task starts, Chrome asks whether to allow the connection. Click **Allow**. A banner shows while the agent is in control.

The agent works in a new tab and is told not to touch your other tabs. You can watch it work.

While remote debugging is on, programs on your PC can ask to control Chrome, and Chrome asks you each time. Only click **Allow** when an AgentJ task has just started, and switch it off when you don't need it.

Other options in **Settings → Chrome tasks use**:

- **A separate Jarvis Chrome window** (`start-jarvis-chrome.bat`): a separate profile. Log in once there and the logins are kept.
- **My main profile, launched by AgentJ:** Chrome must be fully closed first.

**Safety:** the browser agent is told it may browse, read and fill drafts, but it must **never** publish, post, send, delete, buy or change settings. When a task needs one of those actions, it stops and reports `NEEDS APPROVAL: …` so you can do the final click yourself. It also never types passwords.

## Security

- The dashboard only listens on your own PC (127.0.0.1). Requests from other websites, cross-site form posts and DNS-rebinding tricks are refused.
- Results and logs are escaped before they're shown, so content copied from web pages can't run code in the dashboard.
- The SEO auditor only fetches public websites. It refuses your PC, your router and Chrome's debug port.
- **Settings → Sites the Chrome agent may open** limits the browser agent to the sites you list. This is the best protection against a web page trying to lure it somewhere else. Use it.
- Your Gemini key is stored only in `data/agentj.db`, sent only to Google, and masked in the dashboard.

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
  worker.py                runs one task at a time, repeats + scheduled playbooks
  db.py                    SQLite storage (data/agentj.db)
  llm.py                   Gemini (REST) + Ollama, auto-picks newest Gemini Flash model
  agents/
    __init__.py            router (playbook match, keyword rules, then AI classification)
    brainstorm.py  seo.py  browser.py  research.py  write.py
  static/index.html        the dashboard (single file, no build step)
```

Open-source projects reviewed for this build:

- **[browser-use](https://github.com/browser-use/browser-use):** used for the Chrome agent. It's the most widely used open-source browser agent and supports Gemini and Ollama.
- **[OpenJarvis](https://github.com/open-jarvis/OpenJarvis)** (Stanford): good local-first agent ideas, but much heavier and built around local models that would be slow on a PC without a GPU.
- **LightClaw:** a self-hosted assistant whose chat integrations are aimed at Chinese platforms. Only its "skills + review" idea was borrowed here.

## Adding a new agent

Create `jarvis/agents/myagent.py` with a `run(task, ctx)` function that returns markdown. Then register it in `jarvis/agents/__init__.py` (in `AGENTS` and `KEYWORDS`) and add the type to `TYPES` in `db.py`.
