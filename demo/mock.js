/* AgentJ demo: a fake local server that runs entirely in the browser.
   Real AI answers come from Claude via the artifact's `sample` capability when allowed;
   Chrome and SEO fetching are simulated (they need the real app on your PC). */
(function () {
  const pad = n => String(n).padStart(2, "0");
  const nowISO = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  const today = () => nowISO().slice(0, 10);
  const ago = mins => nowISO(new Date(Date.now() - mins * 60000));
  const TYPES = ["auto", "brainstorm", "seo", "browser", "research", "write"];
  const REPEATS = ["", "daily", "weekdays", "weekly"];

  let nextId = 1, nextPb = 1;
  const S = {
    tasks: [], logs: {}, playbooks: [], current: null,
    settings: {
      provider: "gemini", gemini_api_key: "demo…demo", gemini_model: "", ollama_url: "http://127.0.0.1:11434",
      ollama_model: "qwen3:4b", browser_provider: "gemini", chrome_mode: "own", chrome_cdp_url: "http://127.0.0.1:9222",
      chrome_profile: "Default", browser_max_steps: "25", browser_allowed_domains: "youtube.com, *.youtube.com, *.google.com",
      about_me: "Runs CanadianSME (canadiansme.ca), a small-business magazine, and is launching B2Bprint.ca (online print store).",
      worker_paused: "0", speak_replies: "1", voice_lang: "en-IN",
    },
  };

  function log(id, message, level = "info") { (S.logs[id] = S.logs[id] || []).push({ ts: nowISO(), level, message: String(message) }); }
  function getTask(id) { return S.tasks.find(t => t.id === id) || null; }
  function getPb(id) { return S.playbooks.find(p => p.id === id) || null; }
  function update(t, f) { Object.assign(t, f, { updated_at: nowISO() }); return t; }
  function createTask(title, details = "", type = "auto", priority = 2, repeat = "", due_date = "", playbook_id = null) {
    const ts = nowISO();
    const t = { id: nextId++, title: String(title).trim().slice(0, 500), details: String(details || "").trim(), type: TYPES.includes(type) ? type : "auto",
      resolved_type: "", status: "queued", priority: Math.min(3, Math.max(1, +priority || 2)), repeat: REPEATS.includes(repeat) ? repeat : "",
      result: "", feedback: "", attempts: 0, created_at: ts, updated_at: ts, started_at: null, finished_at: null, due_date: due_date || "", playbook_id };
    S.tasks.push(t); return t;
  }
  function createPb(f) {
    const p = { id: nextPb++, name: "", triggers: "", type: "auto", steps: "", schedule: "", run_time: "", enabled: 1, last_run_date: "",
      created_at: nowISO(), updated_at: nowISO() };
    return Object.assign(p, cleanPb(f));
  }
  function cleanPb(f) {
    const o = {};
    for (const k of ["name", "triggers", "type", "steps", "schedule", "run_time", "enabled"]) if (k in f) o[k] = f[k];
    if ("type" in o && !TYPES.includes(o.type)) o.type = "auto";
    if ("schedule" in o && !REPEATS.includes(o.schedule)) o.schedule = "";
    if ("enabled" in o) o.enabled = (o.enabled === 1 || o.enabled === "1" || o.enabled === true) ? 1 : 0;
    return o;
  }

  /* ---------- routing logic (same rules as the real app) ---------- */
  const KEYWORDS = [
    ["seo", /\bseo\b|site audit|meta (title|description)|page ?speed|backlink|keyword rank/],
    ["brainstorm", /brain ?storm|\bideas\b|name ideas|\bangles\b/],
    ["browser", /youtube|\bchrome\b|go to |open (the )?(site|website|page)|log ?in|upload|search console|analytics|click|subscribe|comment on|reply to|check my (channel|inbox|dashboard)/],
    ["research", /research|find out|compare|latest|news|competitor|look up|what is|who is/],
    ["write", /\bwrite\b|draft|email|caption|post|article|blog|script|copy\b|rewrite|summari[sz]e/],
  ];
  function classify(t) { const s = `${t.title} ${t.details}`.toLowerCase(); for (const [k, re] of KEYWORDS) if (re.test(s)) return k; return "write"; }
  function matchPb(text) {
    const s = (text || "").toLowerCase(); let best = null, len = 0;
    for (const p of S.playbooks) for (let ph of [p.name, ...String(p.triggers || "").split(/[,\n]/)]) {
      ph = ph.trim().toLowerCase(); if (ph.length >= 3 && s.includes(ph) && ph.length > len) { best = p; len = ph.length; }
    }
    return best;
  }
  const lines = text => String(text).split("\n").map(l => l.replace(/^\s*([-*•]|\d+[.)])\s*/, "").trim()).filter(Boolean);

  /* ---------- Claude (sample capability) ---------- */
  let samplePromise = null, sampleOff = false;
  function getSample() {
    if (sampleOff) return Promise.resolve(null);
    if (!samplePromise) samplePromise = (window.claude && window.claude.use) ? window.claude.use("sample").catch(() => null) : Promise.resolve(null);
    return samplePromise;
  }
  async function ask(prompt, opts = {}) {
    const sample = await getSample();
    if (!sample) return null;
    try { const r = await sample(prompt, opts); return r.text; }
    catch (e) { if (["not_granted", "sampling_disabled", "not_declared", "capability_disabled", "capability_removed"].includes(e.code)) sampleOff = true; return e.text || null; }
  }
  async function askJSON(prompt) {
    const sample = await getSample();
    if (!sample || !sample.json) return null;
    try { return await sample.json(prompt, { modelTier: "quick" }); }
    catch (e) { if (["not_granted", "sampling_disabled", "not_declared"].includes(e.code)) sampleOff = true; return null; }
  }
  const NO_AI = "\n\n> The demo couldn't reach an AI here (allow Claude when the page asks, or install AgentJ on your PC with a free Gemini key). This is a sample answer.";

  /* ---------- simulated agents ---------- */
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  function context(t) {
    let p = `TASK: ${t.title}`;
    if (t.details) p += `\n\nDETAILS:\n${t.details}`;
    const pb = t.playbook_id ? getPb(t.playbook_id) : null;
    if (pb && pb.steps) p += `\n\nPLAYBOOK '${pb.name}' - follow these steps:\n${pb.steps}`;
    if (t.feedback) p += `\n\nThis is a redo. Previous result:\n${t.result.slice(0, 4000)}\nUser feedback: ${t.feedback}`;
    return `You are AgentJ, a practical Jarvis-style assistant for a busy business owner. Today is ${today()}.\nAbout the user: ${S.settings.about_me}\nUse short markdown sections and bullets. No filler.\n\n` + p;
  }
  const GUIDES = {
    brainstorm: "Brainstorm: 1) Quick take (2 lines) 2) 8-10 distinct ideas, each with a bold name, what it is, why it could work 3) Top 3 picks 4) Next steps.",
    research: "Research from what you know (this demo has no live web search - the real app uses Google Search grounding and lists sources). Format: Answer, Key findings, What it means for me. Flag uncertainty.",
    write: "Do the task and deliver the finished output first, ready to use. Then at most 3 short notes.",
  };
  async function runAgent(t) {
    const pb = t.playbook_id ? getPb(t.playbook_id) : null;
    let kind = t.type !== "auto" ? t.type : (pb && pb.type !== "auto" ? pb.type : (t.resolved_type || classify(t)));
    update(t, { resolved_type: kind }); log(t.id, `Agent selected: ${kind}`);
    if (kind === "browser") return browserDemo(t, pb);
    if (kind === "seo") return seoDemo(t);
    log(t.id, kind === "research" ? "Researching…" : kind === "brainstorm" ? "Brainstorming…" : "Working on it…");
    const out = await ask(context(t) + "\n\n" + GUIDES[kind]);
    return out || canned(kind, t) + NO_AI;
  }
  async function browserDemo(t, pb) {
    const steps = [
      "Connecting to your Chrome - you'd click **Allow** on Chrome's prompt",
      "Opened a new tab (your other tabs are untouched)",
      `Allowed sites: ${S.settings.browser_allowed_domains || "any"}`,
      "📍 Step 1 - reading the page", "📍 Step 2 - navigating", "📍 Step 3 - collecting what you asked for",
    ];
    for (const s of steps) { log(t.id, s, "browser"); await sleep(900); if (t.status !== "running") return ""; }
    const plan = await ask(context(t) + "\n\nThis is a DEMO: you cannot browse. Write what the AgentJ Chrome agent would do for this task in the user's own Chrome: a numbered list of concrete browser steps (sites, pages, buttons), then a short example of the report it would hand back (clearly marked as an example). Remind that it stops with NEEDS APPROVAL before any post/send/publish.", { modelTier: "quick" });
    return `> **Demo:** in the real app this runs in your own Chrome and reports what it actually found.\n\n${plan || canned("browser", t) + NO_AI}`;
  }
  async function seoDemo(t) {
    const m = `${t.title} ${t.details}`.match(/(https?:\/\/[^\s]+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|ca|org|net|io|ai|co|in|store|dev)\b)/i);
    const url = m ? m[0] : "";
    for (const s of [`Fetching ${url || "the page"}`, "Checking title, meta description, headings, canonical, alt text…", "Checking robots.txt and sitemap", "Running Google PageSpeed (mobile)"]) { log(t.id, s); await sleep(800); }
    const plan = await ask(context(t) + `\n\nDEMO: you can't fetch ${url || "the site"}. Write the SEO action plan format AgentJ uses: Top 5 fixes ranked by impact (typical for a site like this), content/keyword opportunities, quick wins under 30 minutes. Say clearly that the real app bases these on the live page audit + PageSpeed scores.`);
    return `> **Demo:** the real app downloads the page and runs 16 checks plus Google PageSpeed before writing this.\n\n${plan || canned("seo", t) + NO_AI}`;
  }
  function canned(kind, t) {
    return {
      brainstorm: `## Ideas for: ${t.title}\n- **Founder in 60 seconds** - short videos of Canadian founders' one big lesson.\n- **Grant of the week** - one funding program explained simply.\n- **Shop-front makeovers** - before/after of a small business's signage (ties into B2Bprint).\n\n**Top pick:** Grant of the week - evergreen, searchable, easy to batch.`,
      write: `**Draft**\n\nHi there,\n\nFollowing up on our conversation - happy to share more details whenever suits you.\n\nBest,\nRaoof`,
      research: `**Answer:** a sample research answer would appear here with key findings and what it means for you.`,
      seo: `1. Rewrite the title tag to 50-60 characters with your main keyword.\n2. Add a 140-155 character meta description.\n3. Keep exactly one H1.\n4. Add alt text to images.\n5. Submit an XML sitemap in Search Console.`,
      browser: `1. Open a new tab → YouTube Studio\n2. Go to Comments → filter "Published, unanswered"\n3. Draft replies (does not post them)\n4. Report: 12 new comments, 3 questions drafted, 1 needs you.\n\nNEEDS APPROVAL: post the 3 drafted replies.`,
    }[kind] || "Done.";
  }

  /* ---------- worker ---------- */
  async function tick() {
    if (S.current || S.settings.worker_paused === "1") return;
    const q = S.tasks.filter(t => t.status === "queued" && (!t.due_date || t.due_date <= today()))
      .sort((a, b) => a.priority - b.priority || a.id - b.id)[0];
    if (!q) return;
    S.current = q.id; update(q, { status: "running", started_at: nowISO(), attempts: q.attempts + 1 });
    log(q.id, `▶ Started (attempt ${q.attempts})`);
    try {
      const result = await runAgent(q);
      if (q.status === "cancelled") log(q.id, "Finished, but the task was cancelled - result discarded");
      else { update(q, { status: "review", result, finished_at: nowISO() }); log(q.id, "✔ Done - waiting for your review"); }
    } catch (e) { update(q, { status: "failed", result: `**Failed:** ${e && e.message || e}`, finished_at: nowISO() }); log(q.id, String(e), "error"); }
    S.current = null;
  }
  setInterval(tick, 1500);

  /* ---------- voice / plan ---------- */
  function cleanItem(it) {
    let pb = it.playbook ? S.playbooks.find(p => p.name.toLowerCase() === String(it.playbook).toLowerCase()) : null;
    pb = pb || matchPb(`${it.title || ""} ${it.details || ""}`);
    return { title: String(it.title || "").slice(0, 300), details: String(it.details || ""), type: TYPES.includes(it.type) ? it.type : "auto",
      priority: [1, 2, 3].includes(+it.priority) ? +it.priority : 2, playbook_id: pb ? pb.id : null };
  }
  const pbList = () => S.playbooks.length ? S.playbooks.map(p => `- ${p.name} (triggers: ${p.triggers || "-"})`).join("\n") : "(none)";
  async function plan(text) {
    const data = await askJSON(`Split this to-do list into tasks. Reply with only a JSON array of {"title","details","type" (brainstorm|seo|browser|research|write),"priority" (1-3),"playbook" (exact saved playbook name or "")}.\nSaved playbooks:\n${pbList()}\n\nTO-DO LIST:\n${text}`);
    const items = Array.isArray(data) ? data.filter(i => i && i.title) : lines(text).map(l => ({ title: l }));
    return items.map(cleanItem).map(i => createTask(i.title, i.details, i.type, i.priority, "", "", i.playbook_id));
  }
  async function voice(text) {
    const low = text.toLowerCase().trim();
    if (!low) return { reply: "I didn't catch that.", created: [] };
    if (/\b(pause|stop working|hold on)\b/.test(low) && low.length < 40) { S.settings.worker_paused = "1"; return { reply: "Paused. Say resume when you want me to continue.", created: [] }; }
    if (/\b(resume|continue|start working|carry on)\b/.test(low) && low.length < 40) { S.settings.worker_paused = "0"; return { reply: "Resuming the queue.", created: [] }; }
    if (/\b(status|what(?:'s|s| is) (?:left|pending|remaining)|anything left|how many tasks|what are you (?:doing|working on))\b/.test(low) && low.length < 60) {
      const c = s => S.tasks.filter(t => t.status === s).length; const cur = S.current && getTask(S.current);
      return { reply: `${c("queued")} queued, ${c("review")} waiting for your review, ${c("failed")} failed.${cur ? " I'm working on: " + cur.title + "." : ""}`, created: [] };
    }
    const data = await askJSON(`You are AgentJ, a voice assistant. The user said: "${text}"\nSaved playbooks:\n${pbList()}\nReply with only JSON: {"reply": "one short spoken confirmation", "tasks": [{"title","details","type" (auto|brainstorm|seo|browser|research|write),"priority" (1-3),"playbook" (exact name or "")}]}. Keep their URLs and details.`);
    const items = data && Array.isArray(data.tasks) && data.tasks.length ? data.tasks.filter(i => i && i.title) : lines(text).map(l => ({ title: l }));
    const created = items.map(cleanItem).map(i => createTask(i.title, i.details, i.type, i.priority, "", "", i.playbook_id));
    return { reply: (data && data.reply) || `Added ${created.length} task${created.length === 1 ? "" : "s"}.`, created };
  }
  async function draftPb(text) {
    const d = await askJSON(`The user explains how they do a repeated task. Turn it into a playbook for an AI agent. Reply with only JSON: {"name","triggers" (comma separated phrases),"type" (browser if done in Chrome, else seo|brainstorm|research|write),"steps" (numbered, precise, keep every URL/name/number, final step says what to report),"schedule" (daily|weekdays|weekly|""),"run_time" ("HH:MM" or "")}.\n\nExplanation:\n${text}`);
    if (d && d.name) return d;
    return { name: lines(text)[0] ? lines(text)[0].slice(0, 60) : "New playbook", triggers: "", type: "auto", steps: text, schedule: "", run_time: "" };
  }

  /* ---------- API ---------- */
  function json(body, status = 200) { return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }); }
  async function handle(method, path, b) {
    let m;
    if (method === "GET") {
      if (path === "/api/tasks") {
        const order = { running: 0, review: 1, queued: 2, failed: 3 };
        return json([...S.tasks].sort((a, c) => (order[a.status] ?? 4) - (order[c.status] ?? 4) || a.priority - c.priority || c.id - a.id));
      }
      if ((m = path.match(/^\/api\/tasks\/(\d+)$/))) { const t = getTask(+m[1]); return t ? json({ ...t, logs: S.logs[t.id] || [] }) : json({ error: "not found" }, 404); }
      if (path === "/api/playbooks") return json([...S.playbooks].sort((a, c) => a.name.localeCompare(c.name)));
      if (path === "/api/settings") return json(S.settings);
      if (path === "/api/status") return json({ current: S.current, paused: S.settings.worker_paused === "1", provider: S.settings.provider, has_key: true,
        chrome: "your Chrome (demo)", chrome_mode: S.settings.chrome_mode, speak: S.settings.speak_replies === "1", voice_lang: S.settings.voice_lang });
      return json({ error: "not found" }, 404);
    }
    if (path === "/api/tasks") {
      if (!String(b.title || "").trim()) return json({ error: "title required" }, 400);
      const pb = b.playbook_id ? getPb(+b.playbook_id) : matchPb(`${b.title} ${b.details || ""}`);
      return json(createTask(b.title, b.details, b.type, b.priority, b.repeat, b.due_date, pb ? pb.id : null), 201);
    }
    if (path === "/api/plan") return json(await plan(String(b.text || "")), 201);
    if (path === "/api/voice") return json(await voice(String(b.text || "")));
    if (path === "/api/playbooks/draft") return json(await draftPb(String(b.text || "")));
    if (path === "/api/playbooks") { if (!String(b.name || "").trim()) return json({ error: "name required" }, 400); const p = createPb(b); S.playbooks.push(p); return json(p, 201); }
    if ((m = path.match(/^\/api\/playbooks\/(\d+)\/(update|run|delete)$/))) {
      const p = getPb(+m[1]); if (!p) return json({ error: "not found" }, 404);
      if (m[2] === "update") { Object.assign(p, cleanPb(b), { updated_at: nowISO() }); return json(p); }
      if (m[2] === "delete") { S.playbooks = S.playbooks.filter(x => x !== p); S.tasks.forEach(t => { if (t.playbook_id === p.id) t.playbook_id = null; }); return json({ ok: true }); }
      const t = createTask(p.name, b.details || "", p.type, 1, "", "", p.id); log(t.id, `Started from the '${p.name}' playbook`); return json(t, 201);
    }
    if (path === "/api/settings") { for (const k in b) if (k in S.settings && k !== "gemini_api_key") S.settings[k] = String(b[k]); return json({ ok: true }); }
    if (path === "/api/settings/test") { const s = await getSample(); return json({ ok: !!s, message: s ? "Demo: AI answers come from Claude in this page. On your PC this tests your Gemini key." : "Demo can't reach an AI here - the real app uses your Gemini key." }); }
    if (path === "/api/worker") { S.settings.worker_paused = b.paused ? "1" : "0"; return json({ ok: true }); }
    if ((m = path.match(/^\/api\/tasks\/(\d+)\/(approve|redo|cancel|update|requeue|delete)$/))) {
      const t = getTask(+m[1]); if (!t) return json({ error: "not found" }, 404);
      const a = m[2];
      if (a === "approve") {
        update(t, { status: "done" }); log(t.id, "Approved by you");
        let next = null;
        if (t.repeat) { const d = new Date(); d.setDate(d.getDate() + (t.repeat === "weekly" ? 7 : 1)); while (t.repeat === "weekdays" && (d.getDay() === 0 || d.getDay() === 6)) d.setDate(d.getDate() + 1);
          next = createTask(t.title, t.details, t.type, t.priority, t.repeat, nowISO(d).slice(0, 10), t.playbook_id); }
        return json({ ok: true, next });
      }
      if (a === "redo") { const fb = String(b.feedback || "").trim(); update(t, { status: "queued", feedback: fb }); log(t.id, `Sent back for redo. Feedback: ${fb || "(none)"}`); return json({ ok: true }); }
      if (a === "requeue") { update(t, { status: "queued" }); return json({ ok: true }); }
      if (a === "cancel") { update(t, { status: "cancelled" }); log(t.id, "Cancelled by you"); if (S.current === t.id) S.current = null; return json({ ok: true }); }
      if (a === "delete") { S.tasks = S.tasks.filter(x => x !== t); if (S.current === t.id) S.current = null; return json({ ok: true }); }
      if (a === "update") { const f = {}; for (const k of ["title", "details", "priority", "due_date"]) if (k in b) f[k] = b[k]; return json(update(t, f)); }
    }
    return json({ error: "not found" }, 404);
  }
  const realFetch = window.fetch.bind(window);
  window.fetch = async (url, opts = {}) => {
    const u = new URL(url, location.href);
    if (!u.pathname.startsWith("/api/")) return realFetch(url, opts);
    let body = {};
    try { body = opts.body ? JSON.parse(opts.body) : {}; } catch (e) { body = {}; }
    return handle((opts.method || "GET").toUpperCase(), u.pathname, body);
  };
  window.confirm = () => true; // the demo's deletes are harmless

  /* ---------- example data (clearly marked) ---------- */
  const yt = createPb({ name: "YouTube comments check", triggers: "youtube comments, reply to comments", type: "browser", schedule: "weekdays", run_time: "09:30",
    steps: "1. Open a new tab and go to studio.youtube.com\n2. Open Comments and filter to Published, newest first, unanswered\n3. For each question, draft a friendly reply in my tone (don't post)\n4. List comments that need me personally\n5. Report: count of new comments, drafted replies, and anything urgent" });
  S.playbooks.push(yt);
  const seoPb = createPb({ name: "Weekly SEO check", triggers: "seo check, weekly seo", type: "seo", schedule: "weekly", run_time: "10:00",
    steps: "1. Audit https://canadiansme.ca homepage\n2. Audit https://b2bprint.ca homepage\n3. Compare with last week and list the top 3 fixes" });
  S.playbooks.push(seoPb);

  const t1 = createTask("Brainstorm 10 YouTube video ideas for CanadianSME", "Audience: Canadian small-business owners. Short-form friendly.", "brainstorm", 2);
  update(t1, { status: "review", resolved_type: "brainstorm", attempts: 1, started_at: ago(40), finished_at: ago(38),
    result: "> Example result (sample data)\n\n## Quick take\nYou want videos that small-business owners search for *and* share. Lean on Canadian specifics: grants, taxes, local wins.\n\n## Ideas\n1. **Grant of the week** - one federal or provincial program in 60 seconds.\n2. **Founder in 60** - one Canadian founder, one hard lesson.\n3. **CRA deadlines decoded** - what's due this month and how to avoid penalties.\n4. **Storefront glow-ups** - signage before/after (pairs with B2Bprint).\n5. **Tool teardown** - one app every SME should try, tested honestly.\n\n## Top 3 picks\n- Grant of the week - evergreen and highly searchable.\n- CRA deadlines decoded - urgent, recurring demand.\n- Storefront glow-ups - visual and cross-promotes B2Bprint.\n\n## Next steps\n- Batch-record 4 Grant of the week episodes this Friday." });
  log(t1.id, "▶ Started (attempt 1)"); log(t1.id, "Agent selected: brainstorm"); log(t1.id, "✔ Done - waiting for your review");
  const t2 = createTask("Draft a LinkedIn post announcing the Small Business Summit 2026", "", "write", 1);
  update(t2, { status: "done", resolved_type: "write", attempts: 1, finished_at: ago(90), result: "> Example result (sample data)\n\nThe Small Business Summit 2026 is coming! Join founders and experts for a day of practical sessions…" });
  const t3 = createTask("YouTube comments check", "", "browser", 2, "", "", yt.id);
  log(t3.id, "Created automatically by the 'YouTube comments check' playbook schedule");
  createTask("SEO audit of b2bprint.ca homepage", "", "auto", 2);
  S.settings.worker_paused = "1"; // start paused so the visitor sees the queue; they press Resume
  window.__agentjDemo = { S };
})();
