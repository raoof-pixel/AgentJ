"""Local voice for AgentJ - runs on your PC, no browser tab needed.

  wake word  : Vosk small English model (~40 MB, offline) listening only for "AgentJ"
  listening  : faster-whisper (the Whisper engine OmniVoice Studio/WhisperX use), CPU int8
  speaking   : Kokoro-82M via kokoro-onnx (one of OmniVoice Studio's TTS engines), offline

Flow: idle -> hears "AgentJ" -> chime -> records until you pause -> Whisper -> AgentJ acts -> speaks reply.
Everything heavy is loaded lazily, and if a package is missing the dashboard falls back to Chrome's speech.
"""

import collections
import json
import os
import queue
import re
import threading
import time
import traceback

from . import db

RATE = 16000
BLOCK = 1600                 # 100 ms of audio per block
PRE_ROLL_BLOCKS = 15         # keep 1.5 s before the wake word so "AgentJ, do X" in one breath works
SILENCE_END = 0.9            # seconds of quiet that end a command
MAX_COMMAND = 15             # seconds
NO_SPEECH_TIMEOUT = 7        # seconds after the chime with nothing said
VOICE_DIR = os.path.join(db.DATA_DIR, "voice")
KOKORO_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin",
}
WAKE_RE = re.compile(r"\b(?:hey\s+|ok(?:ay)?\s+)?a\s*gents?\s*(?:j|jay|jae|je)\b|\bagentj\b", re.I)


def missing_packages():
    missing = []
    for mod in ("numpy", "sounddevice", "vosk", "faster_whisper"):
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)
    return missing


def strip_wake(text):
    m = WAKE_RE.search(text or "")
    if not m:
        return (text or "").strip()
    return (text[m.end():] if m.start() < 12 else text).strip(" ,.!?:-")


class VoiceService:
    def __init__(self, handler):
        self.handler = handler          # text -> reply (AgentJ's voice_command)
        self.state = "off"              # off | loading | idle | awake | thinking | speaking | error
        self.heard = ""
        self.reply = ""
        self.error = ""
        self.level = 0.0
        self.tts_ready = False
        self._stop = threading.Event()
        self._force_wake = threading.Event()
        self._thread = None
        self._whisper = None
        self._kokoro = None
        self._q = queue.Queue()

    # ---------- public ----------
    def snapshot(self):
        return {"engine": "local", "state": self.state, "heard": self.heard, "reply": self.reply,
                "error": self.error, "level": round(self.level, 3), "tts": self.tts_ready,
                "missing": missing_packages() if self.state in ("off", "error") else []}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="agentj-voice", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.state = "off"

    def push_to_talk(self):
        if self.state in ("off", "error"):
            self.start()
        self._force_wake.set()

    def say(self, text):
        threading.Thread(target=self._speak, args=(text,), daemon=True).start()

    # ---------- internals ----------
    def _callback(self, indata, frames, t, status):
        self._q.put(bytes(indata))

    def _load(self):
        self.state = "loading"
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)
        self._vosk_model = Model(lang="en-us")       # downloads the small English model once (~40 MB)
        grammar = json.dumps(["agent jay", "agent j", "hey agent jay", "agent", "[unk]"])
        self._wake = KaldiRecognizer(self._vosk_model, RATE, grammar)
        threading.Thread(target=self._load_slow, daemon=True).start()

    def _load_slow(self):
        try:
            self._get_whisper()
        except Exception:
            traceback.print_exc()
        try:
            self._get_kokoro()
        except Exception:
            traceback.print_exc()

    def _get_whisper(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel
            size = db.get_settings().get("whisper_model") or "base"
            self._whisper = WhisperModel(size, device="cpu", compute_type="int8")
        return self._whisper

    def _get_kokoro(self):
        if self._kokoro is None:
            from kokoro_onnx import Kokoro
            model = os.path.join(VOICE_DIR, "kokoro-v1.0.onnx")
            voices = os.path.join(VOICE_DIR, "voices-v1.0.bin")
            if not (os.path.exists(model) and os.path.exists(voices)):
                return None
            self._kokoro = Kokoro(model, voices)
            self.tts_ready = True
        return self._kokoro

    def _run(self):
        import numpy as np
        import sounddevice as sd
        try:
            self._load()
        except Exception as e:
            self.state, self.error = "error", f"Voice couldn't start: {e}"
            traceback.print_exc()
            return
        self.error = ""
        self.state = "idle"
        pre = collections.deque(maxlen=PRE_ROLL_BLOCKS)
        try:
            with sd.RawInputStream(samplerate=RATE, blocksize=BLOCK, dtype="int16", channels=1, callback=self._callback):
                while not self._stop.is_set():
                    try:
                        data = self._q.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                    rms = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
                    self.level = min(1.0, rms * 8)
                    if self.state == "speaking":
                        continue                     # don't hear ourselves
                    pre.append(data)
                    woke = self._force_wake.is_set()
                    if not woke and self._wake.AcceptWaveform(data):
                        text = json.loads(self._wake.Result()).get("text", "")
                        woke = "agent jay" in text or "agent j" in text
                    elif not woke:
                        partial = json.loads(self._wake.PartialResult()).get("partial", "")
                        woke = "agent jay" in partial or "agent j" in partial
                    if woke:
                        self._force_wake.clear()
                        self._wake.Reset()
                        self._command(list(pre), np)
                        pre.clear()
                        while not self._q.empty():   # drop audio captured while we were busy
                            self._q.get_nowait()
        except Exception as e:
            self.state, self.error = "error", f"Microphone problem: {e}"
            traceback.print_exc()
            return
        self.state = "off"

    def _command(self, pre_blocks, np):
        self.state, self.heard, self.reply = "awake", "", ""
        self._chime(True)
        frames = list(pre_blocks)
        wall_start = time.time()
        started = 0.0          # timings below use seconds of audio heard, not the wall clock
        now = 0.0
        last_voice = None
        noise = 0.012
        while not self._stop.is_set():
            try:
                data = self._q.get(timeout=0.5)
            except queue.Empty:
                if time.time() - wall_start > MAX_COMMAND + 5:  # microphone stopped sending audio
                    break
                continue
            frames.append(data)
            s = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(s ** 2))) if s.size else 0.0
            self.level = min(1.0, rms * 8)
            now += len(data) / 2 / RATE
            if rms > max(noise * 2.5, 0.02):
                last_voice = now
            else:
                noise = 0.95 * noise + 0.05 * rms
            if last_voice and now - last_voice > SILENCE_END:
                break
            if not last_voice and now - started > NO_SPEECH_TIMEOUT:
                self.state = "idle"
                self._chime(False)
                return
            if now - started > MAX_COMMAND:
                break
        audio = np.frombuffer(b"".join(frames), dtype=np.int16).astype(np.float32) / 32768.0
        self.state = "thinking"
        self.level = 0.0
        try:
            lang = (db.get_settings().get("voice_lang") or "en")[:2]
            segments, _ = self._get_whisper().transcribe(audio, language=lang, vad_filter=True, beam_size=1)
            text = strip_wake(" ".join(seg.text for seg in segments).strip())
        except Exception as e:
            self.state, self.reply = "idle", f"I couldn't understand that ({e})."
            return
        self.heard = text
        if len(text) < 2 or re.match(r"^(never ?mind|cancel|nothing|stop)\b", text, re.I):
            self.state = "idle"
            self._chime(False)
            return
        try:
            reply = self.handler(text)
        except Exception as e:
            reply = f"Something went wrong: {e}"
        self.reply = reply
        self._speak(reply)

    def _speak(self, text):
        if not text or db.get_settings().get("speak_replies") != "1":
            self.state = "idle" if self.state != "off" else "off"
            return
        prev = self.state
        try:
            k = self._get_kokoro()
            if k is None:
                return
            import sounddevice as sd
            self.state = "speaking"
            voice = db.get_settings().get("tts_voice") or "af_heart"
            samples, sr = k.create(text[:600], voice=voice, speed=1.05, lang="en-us")
            sd.play(samples, sr)
            sd.wait()
        except Exception:
            traceback.print_exc()
        finally:
            self.state = "idle" if prev != "off" else "off"

    def _chime(self, up):
        try:
            import numpy as np
            import sounddevice as sd
            tones = [660, 880] if up else [740, 560]
            t = np.linspace(0, 0.12, int(RATE * 0.12), False)
            wave = np.concatenate([np.sin(2 * np.pi * f * t) * np.exp(-t * 18) * 0.25 for f in tones]).astype(np.float32)
            sd.play(wave, RATE)
        except Exception:
            pass


def download_tts_models(progress=print):
    """Fetch the Kokoro voice files once (~330 MB) into data/voice/."""
    import urllib.request
    os.makedirs(VOICE_DIR, exist_ok=True)
    for name, url in KOKORO_FILES.items():
        dest = os.path.join(VOICE_DIR, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
            progress(f"  {name} already downloaded")
            continue
        progress(f"  downloading {name} ...")
        tmp = dest + ".part"
        urllib.request.urlretrieve(url, tmp)
        os.replace(tmp, dest)
    progress("  voice files ready")


_service = None


def service(handler=None):
    global _service
    if _service is None and handler is not None:
        _service = VoiceService(handler)
    return _service


if __name__ == "__main__":  # python -m jarvis.voice  -> download voice models
    download_tts_models()
    try:
        from faster_whisper import WhisperModel
        print("  preparing Whisper (base) ...")
        WhisperModel("base", device="cpu", compute_type="int8")
        from vosk import Model
        print("  preparing wake word model ...")
        Model(lang="en-us")
        print("  done")
    except Exception as e:
        print("  voice packages not ready:", e)
