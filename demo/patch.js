/* Demo-only tweaks applied after the dashboard script loads.
   Shared pages can't use the microphone, so the wake word is tried by typing "AgentJ, ..." instead. */
(function () {
  let demoWake = false;
  const WAKE = /^\s*(?:hey\s+)?agent\s*j(?:ay)?\b[\s,.!?:-]*/i;
  const hintOff = "Demo: turn on the wake word, then type “AgentJ, SEO audit of b2bprint.ca” below. On your PC you just say it.";
  const hintOn = "Demo: listening for “AgentJ”. Type it below, then what you need. On your PC this works with your voice, offline.";
  document.getElementById("heard").textContent = hintOff;
  document.getElementById("cmd").placeholder = "Type what you would say, e.g. AgentJ, brainstorm 5 blog ideas";
  document.getElementById("wakeToggle").onclick = () => {
    demoWake = !demoWake;
    const b = document.getElementById("wakeToggle");
    b.setAttribute("aria-pressed", demoWake ? "true" : "false");
    b.textContent = demoWake ? "listening for agentj" : "wake word off";
    document.getElementById("heard").textContent = demoWake ? hintOn : hintOff;
  };
  const talk = () => { const c = document.getElementById("cmd"); c.focus(); if (!c.value) c.value = "AgentJ, "; toast("In the demo, type what you would say."); };
  document.getElementById("btnTalk").onclick = talk;
  document.addEventListener("keydown", e => { if (e.altKey && (e.key === "j" || e.key === "J")) { e.stopImmediatePropagation(); e.preventDefault(); talk(); } }, true);
  const original = document.getElementById("compose").onsubmit;
  document.getElementById("compose").onsubmit = async e => {
    const c = document.getElementById("cmd"), text = c.value.trim();
    const m = text.match(WAKE);
    if (!m || text.includes("\n")) return original(e);
    e.preventDefault();
    const cmd = text.slice(m[0].length).trim();
    c.value = "";
    chime(true); setMode("awake", null, cmd || "…");
    await new Promise(r => setTimeout(r, 900));
    if (!cmd) { chime(false); setMode("idle", null, demoWake ? hintOn : hintOff); return; }
    setMode("thinking", null, "“" + cmd + "”");
    await sendCommand(cmd, true);
    document.getElementById("heard").textContent = demoWake ? hintOn : hintOff;
  };
  document.getElementById("pbDictate").onclick = () => { document.getElementById("pbExplain").focus(); toast("In the demo, type your explanation. On your PC, dictate uses your microphone."); };
  window.idleHint = () => (demoWake ? hintOn : hintOff);
})();
