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
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--bg)}
header,main,.demo-strip{padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
main{padding-block:20px}
.demo-strip{background:#122b28;border-bottom:1px solid #2c6f69;color:#b2f5ea;font-size:13px;padding-block:8px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.demo-strip a{color:var(--accent)}
@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}
"""

strip = ('<div class="demo-strip"><b>Demo</b><span>Runs in this page with example data. Press <b>Resume</b> to let it work. '
         'AI answers come from Claude (allow it when asked); Chrome and SEO fetching are simulated.</span>'
         '<a href="https://github.com/raoof-pixel/AgentJ" target="_blank" rel="noopener noreferrer">Get the real app on GitHub</a></div>')

out = (
    '<title>AgentJ</title>\n'
    '<meta name="claude:viewport-fit-sides" content="cover">\n'
    f"<style>{style}</style>\n"
    f"{strip}\n{markup}\n"
    f"<script>{open(os.path.join(HERE, 'mock.js'), encoding='utf-8').read()}</script>\n"
    f"<script>{main_script}</script>\n"
    f"<script>{open(os.path.join(HERE, 'patch.js'), encoding='utf-8').read()}</script>\n"
)
dest = os.path.join(HERE, "agentj-demo.html")
open(dest, "w", encoding="utf-8").write(out)
print("wrote", dest, len(out), "bytes")
