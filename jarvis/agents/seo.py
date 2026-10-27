"""On-page SEO audit using only the standard library, plus an AI action plan.

Checks: status/speed, title, meta description, headings, canonical, robots meta,
Open Graph, viewport, lang, image alt text, links, structured data, robots.txt,
sitemap.xml, and (optionally) Google PageSpeed Insights.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from .. import db, llm

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 AgentJ-SEO"


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.meta = {}
        self.links = []
        self.canonical = ""
        self.lang = ""
        self.headings = {f"h{i}": [] for i in range(1, 7)}
        self._heading = None
        self._heading_text = ""
        self.images = 0
        self.images_no_alt = 0
        self.jsonld = 0
        self._skip = 0
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name:
                self.meta[name] = a.get("content", "")
        elif tag == "link" and "canonical" in a.get("rel", "").lower():
            self.canonical = a.get("href", "")
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "img":
            self.images += 1
            if not a.get("alt", "").strip():
                self.images_no_alt += 1
        elif tag in self.headings:
            self._heading, self._heading_text = tag, ""
        elif tag == "script" and "ld+json" in a.get("type", ""):
            self.jsonld += 1
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == self._heading:
            self.headings[tag].append(" ".join(self._heading_text.split())[:150])
            self._heading = None
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._heading:
            self._heading_text += data
        if not self._skip:
            self.text_parts.append(data)


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(3_000_000)
            charset = r.headers.get_content_charset() or "utf-8"
            return r.status, r.geturl(), body.decode(charset, "replace"), time.time() - t0, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, url, "", time.time() - t0, {}


def pagespeed(url):
    api = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?" + urllib.parse.urlencode(
        [("url", url), ("strategy", "mobile"), ("category", "performance"), ("category", "seo"),
         ("category", "accessibility"), ("category", "best-practices")]
    )
    try:
        with urllib.request.urlopen(urllib.request.Request(api, headers={"User-Agent": UA}), timeout=90) as r:
            data = json.loads(r.read().decode("utf-8"))
        cats = data.get("lighthouseResult", {}).get("categories", {})
        audits = data.get("lighthouseResult", {}).get("audits", {})
        scores = {k: round((v.get("score") or 0) * 100) for k, v in cats.items()}
        metrics = {}
        for key in ("largest-contentful-paint", "cumulative-layout-shift", "total-blocking-time", "speed-index"):
            if key in audits:
                metrics[audits[key].get("title", key)] = audits[key].get("displayValue", "")
        return {"scores": scores, "metrics": metrics}
    except Exception as e:  # PageSpeed is optional; never fail the audit because of it
        return {"error": str(e)[:200]}


def audit(url, task_id=None):
    def say(msg):
        if task_id:
            db.log(task_id, msg)

    say(f"Fetching {url}")
    status, final_url, html, secs, headers = fetch(url)
    p = PageParser()
    p.feed(html)
    words = len(" ".join(p.text_parts).split())
    host = urllib.parse.urlparse(final_url).netloc
    internal = sum(1 for l in p.links if l.startswith("/") or host in l)
    external = sum(1 for l in p.links if l.startswith("http") and host not in l)

    root = f"{urllib.parse.urlparse(final_url).scheme}://{host}"
    say("Checking robots.txt and sitemap")
    rstatus, _, robots, _, _ = fetch(root + "/robots.txt", 15)
    sitemap_in_robots = "sitemap:" in robots.lower()
    sstatus, _, _, _, _ = fetch(root + "/sitemap.xml", 15)

    title = " ".join(p.title.split())
    desc = p.meta.get("description", "")
    issues = []

    def chk(cond, ok_msg, bad_msg, sev="medium"):
        (issues.append(("ok", ok_msg)) if cond else issues.append((sev, bad_msg)))

    chk(status == 200, f"Page loads (HTTP {status})", f"Page returned HTTP {status}", "high")
    chk(final_url.startswith("https"), "Uses HTTPS", "Not served over HTTPS", "high")
    chk(secs < 2.5, f"Server response {secs:.1f}s", f"Slow server response ({secs:.1f}s)")
    chk(10 <= len(title) <= 65, f"Title length OK ({len(title)} chars)",
        f"Title is {len(title)} chars (aim for 30-60): '{title[:80]}'", "high" if not title else "medium")
    chk(70 <= len(desc) <= 160, f"Meta description length OK ({len(desc)} chars)",
        f"Meta description is {len(desc)} chars (aim for 120-155)", "high" if not desc else "medium")
    h1 = p.headings["h1"]
    chk(len(h1) == 1, "Exactly one H1", f"Found {len(h1)} H1 tags (should be exactly 1)", "high" if not h1 else "medium")
    chk(bool(p.canonical), "Canonical tag present", "Missing canonical tag")
    chk("noindex" not in p.meta.get("robots", "").lower(), "Page is indexable",
        "Robots meta has NOINDEX - Google won't index this page", "high")
    chk(bool(p.meta.get("viewport")), "Mobile viewport set", "Missing mobile viewport meta tag", "high")
    chk(bool(p.lang), f"HTML lang set ({p.lang})", "Missing <html lang> attribute", "low")
    chk(bool(p.meta.get("og:title") and p.meta.get("og:image")), "Open Graph tags present",
        "Missing Open Graph title/image (affects social shares)", "low")
    chk(p.images_no_alt == 0, "All images have alt text",
        f"{p.images_no_alt} of {p.images} images missing alt text")
    chk(words >= 300, f"Content length {words} words", f"Thin content: ~{words} words", "medium")
    chk(p.jsonld > 0, "Structured data (JSON-LD) found", "No structured data (schema.org JSON-LD)", "low")
    chk(rstatus == 200, "robots.txt found", "robots.txt missing", "low")
    chk(sstatus == 200 or sitemap_in_robots, "XML sitemap found", "No sitemap.xml found", "medium")

    say("Running Google PageSpeed (mobile) - can take up to a minute")
    ps = pagespeed(final_url)

    return {
        "url": final_url, "status": status, "response_s": round(secs, 2), "title": title,
        "description": desc, "h1": h1, "h2": p.headings["h2"][:15], "words": words,
        "images": p.images, "images_no_alt": p.images_no_alt, "internal_links": internal,
        "external_links": external, "canonical": p.canonical, "issues": issues, "pagespeed": ps,
    }


def report_md(a):
    icon = {"ok": "✅", "high": "🔴", "medium": "🟠", "low": "🟡"}
    order = {"high": 0, "medium": 1, "low": 2, "ok": 3}
    lines = [f"### Audit of {a['url']}", ""]
    ps = a["pagespeed"]
    if ps.get("scores"):
        lines.append("**PageSpeed (mobile):** " + " · ".join(f"{k}: **{v}**" for k, v in ps["scores"].items()))
        if ps.get("metrics"):
            lines.append("**Core metrics:** " + " · ".join(f"{k}: {v}" for k, v in ps["metrics"].items()))
        lines.append("")
    for sev, msg in sorted(a["issues"], key=lambda x: order[x[0]]):
        lines.append(f"- {icon[sev]} {msg}")
    lines += ["", f"**Title:** {a['title'] or '(none)'}", f"**Meta description:** {a['description'] or '(none)'}",
              f"**H1:** {', '.join(a['h1']) or '(none)'}",
              f"**Links:** {a['internal_links']} internal, {a['external_links']} external"]
    return "\n".join(lines)


def run(task, ctx):
    url = ctx.get("url")
    if not url:
        db.log(task["id"], "No URL found - giving SEO advice instead of an audit")
        return llm.generate(ctx["prompt"] + "\n\nGive practical, prioritized SEO advice for this.",
                            system=ctx["system"], web_search=True, temperature=0.4)
    a = audit(url, task["id"])
    findings = report_md(a)
    db.log(task["id"], "Writing the action plan")
    try:
        plan = llm.generate(
            ctx["prompt"] + "\n\nHere is a technical on-page SEO audit:\n" + findings +
            "\nH2s: " + "; ".join(a["h2"]) +
            "\n\nWrite a prioritized SEO action plan: 1) Top 5 fixes ranked by impact (each with exactly what to change, "
            "including a rewritten title tag and meta description), 2) content/keyword opportunities for this page, "
            "3) quick wins doable in under 30 minutes.",
            system=ctx["system"], temperature=0.4,
        )
    except llm.LLMError as e:
        plan = f"_AI action plan unavailable: {e}_"
    return f"## SEO action plan\n\n{plan}\n\n---\n\n## Raw audit\n\n{findings}"
