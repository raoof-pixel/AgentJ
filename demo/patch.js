/* Demo-only tweaks applied after the dashboard script loads. */
(function () {
  // Microphones aren't available inside the shared demo page, so the 🎙 button opens a
  // "type what you'd say" box. On your PC the real app listens to your voice.
  const bar = document.getElementById("voicebar");
  bar.querySelector(".inner").innerHTML =
    '<span class="spinner" id="vSpin" hidden></span>' +
    '<input id="vType" placeholder="Type what you would say, e.g. “SEO audit of canadiansme.ca and brainstorm 5 blog ideas”" style="flex:1;min-width:0">' +
    '<button class="primary" id="vSend">Send</button><button class="ghost" id="vClose">✕</button>';
  const input = document.getElementById("vType");
  async function send() {
    const text = input.value.trim(); if (!text) return;
    const spin = document.getElementById("vSpin"); spin.hidden = false; input.disabled = true;
    const r = await post("/api/voice", { text });
    spin.hidden = true; input.disabled = false; input.value = "";
    toast("AgentJ: " + (r.reply || "Done.")); speak(r.reply);
    if (r.created && r.created.length) state.tab = "today";
    refresh();
  }
  document.getElementById("vSend").onclick = send;
  input.onkeydown = e => { if (e.key === "Enter") send(); };
  document.getElementById("vClose").onclick = () => { bar.style.display = "none"; };
  window.startListening = function (target) {
    if (target) { target.focus(); toast("In the demo, type your explanation. On your PC, 🎙 Dictate uses your microphone."); return; }
    bar.style.display = "block"; input.focus();
  };
  document.getElementById("btnMic").onclick = () => window.startListening(null);
  document.getElementById("pbDictate").onclick = () => window.startListening(document.getElementById("pbExplain"));
  const origCopy = window.copyResult;
  window.copyResult = function () { try { origCopy(); } catch (e) { toast("Select the text to copy it."); } };
})();
