"""Thin LLM layer using only the Python standard library.

- Gemini (Google AI Studio API key) - default, fast, works well on low-spec PCs.
- Ollama (fully local) - optional, for offline/private text tasks.
"""

import json
import os
import re
import urllib.error
import urllib.request

from . import db

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_model_cache = {}


class LLMError(Exception):
    pass


def _post(url, payload, headers=None, timeout=180):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:600]
        raise LLMError(f"HTTP {e.code} from {url.split('?')[0]}: {body}")
    except urllib.error.URLError as e:
        raise LLMError(f"Could not reach {url.split('?')[0]}: {e.reason}")


def _get(url, headers=None, timeout=30):
    req = urllib.request.Request(url)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:600]
        raise LLMError(f"HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise LLMError(f"Could not reach {url.split('?')[0]}: {e.reason}")


# ---------------- Gemini ----------------

def _version_key(name):
    nums = [int(n) for n in re.findall(r"\d+", name)]
    return nums or [0]


def pick_gemini_model(api_key):
    """Choose the newest stable 'flash' model the key can use (cheap + fast)."""
    if api_key in _model_cache:
        return _model_cache[api_key]
    data = _get(f"{GEMINI_BASE}/models?pageSize=200", {"x-goog-api-key": api_key})
    models = [
        m for m in data.get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]
    bad = ("lite", "image", "tts", "audio", "live", "embedding", "vision", "thinking-exp", "learnlm", "gemma")

    def ok(name, allow_preview):
        n = name.lower()
        if "flash" not in n or any(b in n for b in bad):
            return False
        if not allow_preview and ("preview" in n or "exp" in n):
            return False
        return True

    for allow_preview in (False, True):
        names = [m["name"].replace("models/", "") for m in models if ok(m["name"], allow_preview)]
        if names:
            # prefer explicit versions over "-latest" aliases, newest first
            names.sort(key=lambda n: ("latest" in n, [-x for x in _version_key(n)]))
            _model_cache[api_key] = names[0]
            return names[0]
    if models:
        name = models[0]["name"].replace("models/", "")
        _model_cache[api_key] = name
        return name
    raise LLMError("No Gemini models available for this API key.")


def gemini_model(settings):
    key = settings.get("gemini_api_key")
    if not key:
        raise LLMError("No Gemini API key set. Add it in Settings (free key: https://aistudio.google.com/apikey).")
    return settings.get("gemini_model") or pick_gemini_model(key)


def gemini_generate(prompt, system="", settings=None, web_search=False, temperature=0.7, images=None, json_mode=False):
    settings = settings or db.get_settings()
    key = settings.get("gemini_api_key")
    model = gemini_model(settings)
    parts = [{"text": prompt}]
    for img in images or []:  # (mime_type, base64_data)
        parts.append({"inline_data": {"mime_type": img[0], "data": img[1]}})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": temperature},
    }
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if web_search:
        payload["tools"] = [{"google_search": {}}]
    url = f"{GEMINI_BASE}/models/{model}:generateContent"
    try:
        data = _post(url, payload, {"x-goog-api-key": key})
    except LLMError:
        if web_search:  # some models/keys don't allow search grounding - retry without it
            payload.pop("tools", None)
            data = _post(url, payload, {"x-goog-api-key": key})
        else:
            raise
    cands = data.get("candidates") or []
    if not cands:
        raise LLMError(f"Gemini returned no answer: {json.dumps(data)[:400]}")
    parts = cands[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    sources = []
    gm = cands[0].get("groundingMetadata") or {}
    for ch in gm.get("groundingChunks", []) or []:
        web = ch.get("web") or {}
        if web.get("uri"):
            sources.append((web.get("title") or web["uri"], web["uri"]))
    if sources:
        seen, lines = set(), []
        for title, uri in sources:
            if uri not in seen:
                seen.add(uri)
                lines.append(f"- [{title}]({uri})")
        text += "\n\n**Sources**\n" + "\n".join(lines[:10])
    return text


# ---------------- Ollama ----------------

def ollama_generate(prompt, system="", settings=None, temperature=0.7):
    settings = settings or db.get_settings()
    url = settings.get("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    data = _post(url, {
        "model": settings.get("ollama_model", "qwen3:4b"),
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": 8192},
    }, timeout=900)
    text = data.get("message", {}).get("content", "")
    # strip <think> blocks some local reasoning models emit
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


# ---------------- public ----------------

def generate(prompt, system="", web_search=False, temperature=0.7, settings=None):
    if os.environ.get("AGENTJ_FAKE_LLM") == "1":
        return f"[fake LLM answer]\n\nPrompt started with: {prompt[:120]}"
    settings = settings or db.get_settings()
    if settings.get("provider") == "ollama":
        return ollama_generate(prompt, system, settings, temperature)
    return gemini_generate(prompt, system, settings, web_search, temperature)


def test_connection(settings=None):
    settings = settings or db.get_settings()
    if settings.get("provider") == "ollama":
        reply = ollama_generate("Reply with just: OK", settings=settings)
        return f"Ollama ({settings.get('ollama_model')}) replied: {reply[:60]}"
    model = gemini_model(settings)
    reply = gemini_generate("Reply with just: OK", settings=settings)
    return f"Gemini ({model}) replied: {reply[:60]}"
