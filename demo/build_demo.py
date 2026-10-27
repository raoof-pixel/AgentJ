"""Build demo/agentj-demo.html (a browser-only demo) from the real dashboard."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "..", "jarvis", "static", "index.html"), encoding="utf-8").read()

style = re.search(r"<style>(.*?)</style>", src, re.S).group(1)
body = re.search(r"<body>(.*)</body>", src, re.S).group(1)
main_script = re.search(r"<script>(.*?)</script>", body, re.S).group(1)
markup = re.sub(r"<script>.*?</script>", "", body, flags=re.S)

# viewer frame: dark single theme, safe-area aware header, side gutters
style = style.replace(":root{", ":root{color-scheme:dark;", 1)
style = style.replace("position:sticky;top:0;", "position:sticky;top:env(safe-area-inset-top,0px);", 1)
style += """
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10}
.top-in,.layout,.demo-strip{padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
.layout{padding-block:20px}
.demo-strip{background:var(--color-paper-2);border-bottom:var(--rule-hair) solid var(--color-rule);color:var(--color-ink-2);font-size:var(--text-sm);padding-block:8px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.demo-strip a{color:var(--color-ink)}
.top{top:env(safe-area-inset-top,0px)}
body::before{background:var(--color-paper)}
@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}
"""

strip = ('<div class="demo-strip"><strong>Demo</strong><span>Example data in your browser. Press resume queue to let it work. '
         'Answers come from Claude (allow it when asked). Voice is typed here, and Chrome, desktop and SEO fetching are simulated.</span>'
         '<a href="https://github.com/raoof-pixel/AgentJ" target="_blank" rel="noopener noreferrer">Get the real app on GitHub</a></div>')

out = (
    '<title>AgentJ</title>\n'
    '<meta name="claude:viewport-fit-sides" content="cover">\n'
    '<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=Geist:wght@400;500&family=Geist+Mono:wght@400&display=swap" rel="stylesheet">\n'
    f"<style>{style}</style>\n"
    f"{strip}\n{markup}\n"
    f"<script>{open(os.path.join(HERE, 'mock.js'), encoding='utf-8').read()}</script>\n"
    f"<script>{main_script}</script>\n"
    f"<script>{open(os.path.join(HERE, 'patch.js'), encoding='utf-8').read()}</script>\n"
)
dest = os.path.join(HERE, "agentj-demo.html")
open(dest, "w", encoding="utf-8").write(out)
print("wrote", dest, len(out), "bytes")
