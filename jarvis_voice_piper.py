"""Живой офлайн-голос Джарвиса (Piper TTS, нейросеть).

Работает без интернета после первой загрузки модели (~63 МБ).
Модели лежат в %USERPROFILE%\\.jarvis\\voices, качаются с HuggingFace (rhasspy/piper-voices).

Русские голоса:
  dmitri — мужской, живой (по умолчанию)
  ruslan — мужской, спокойный
  irina  — женский
  denis  — мужской

Использование:
    from jarvis_voice_piper import speak_piper, ensure_voice, PIPER_VOICES
"""
from __future__ import annotations

import urllib.request
import wave
import winsound
from pathlib import Path

PIPER_VOICES = ("dmitri", "ruslan", "irina", "denis")
DEFAULT_PIPER_VOICE = "dmitri"

HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU"


def voices_dir() -> Path:
    d = Path.home() / ".jarvis" / "voices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def voice_files(name: str) -> tuple[Path, Path]:
    """Пути (model.onnx, model.onnx.json) для голоса."""
    d = voices_dir()
    stem = f"ru_RU-{name}-medium"
    return d / f"{stem}.onnx", d / f"{stem}.onnx.json"


def is_downloaded(name: str) -> bool:
    onnx, js = voice_files(name)
    return onnx.is_file() and onnx.stat().st_size > 1_000_000 and js.is_file()


def ensure_voice(name: str, progress=None) -> tuple[Path, Path]:
    """Скачать голос, если его нет. progress(url, done, total) — колбэк прогресса."""
    name = (name or DEFAULT_PIPER_VOICE).lower()
    if name not in PIPER_VOICES:
        name = DEFAULT_PIPER_VOICE
    onnx, js = voice_files(name)
    if is_downloaded(name):
        return onnx, js
    stem = f"ru_RU-{name}-medium"
    for fname, dest in ((f"{stem}.onnx", onnx), (f"{stem}.onnx.json", js)):
        url = f"{HF_BASE}/{name}/medium/{fname}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Jarvis/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    try:
                        progress(url, done, total)
                    except Exception:
                        pass
    return onnx, js


def list_status() -> list[tuple[str, bool, float]]:
    """[(голос, скачан, размер МБ)] для --list-voices."""
    out = []
    for name in PIPER_VOICES:
        onnx, _ = voice_files(name)
        out.append((name, is_downloaded(name),
                    round(onnx.stat().st_size / 1_048_576, 1) if onnx.is_file() else 0.0))
    return out


_cache: dict = {}


def _load(name: str):
    from piper import PiperVoice

    if name not in _cache:
        onnx, _ = ensure_voice(name)
        _cache[name] = PiperVoice.load(str(onnx))
    return _cache[name]


def speak_piper(text: str, voice: str = DEFAULT_PIPER_VOICE,
                length_scale: float | None = None) -> None:
    """Озвучить текст голосом Piper (блокирующий вызов, ~реалтайм на CPU).

    length_scale: темп (1.0 — норма, <1 — быстрее, >1 — медленнее).
    """
    from piper import SynthesisConfig

    text = (text or "").strip()
    if not text:
        return
    name = (voice or DEFAULT_PIPER_VOICE).lower()
    if name not in PIPER_VOICES:
        name = DEFAULT_PIPER_VOICE
    v = _load(name)
    cfg = SynthesisConfig(length_scale=length_scale) if length_scale else None
    tmp = voices_dir() / "_say.wav"
    with wave.open(str(tmp), "wb") as wav:
        if cfg is not None:
            v.synthesize_wav(text, wav, syn_config=cfg)
        else:
            v.synthesize_wav(text, wav)
    winsound.PlaySound(str(tmp), winsound.SND_FILENAME)
