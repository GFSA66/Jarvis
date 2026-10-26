"""Живой нейроголос через Microsoft Edge TTS (онлайн, бесплатно).

Использует нейросетевые голоса Microsoft (ru-RU-DmitryNeural и др.).
Требует интернет-соединение. Качество выше Piper, но нужен онлайн.

Установка:  pip install edge-tts
"""
from __future__ import annotations

import asyncio
import ctypes
import os
import re

import tempfile
from pathlib import Path

EDGE_VOICES = {
    "dmitri": "ru-RU-DmitryNeural",
    "svetlana": "ru-RU-SvetlanaNeural",
}
DEFAULT_EDGE_VOICE = "dmitri"


def _wpm_to_rate(wpm) -> str:
    """Темп WPM -> строка rate для edge-tts ('+0%', '-10%' и т.д.)."""
    try:
        wpm = int(wpm)
    except (TypeError, ValueError):
        return "+0%"
    # Базовый темп ~175 слов/мин = +0%
    pct = round((wpm - 175) / 175 * 100)
    pct = max(-50, min(100, pct))
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct}%"


def speak_edge(text: str, voice: str = DEFAULT_EDGE_VOICE,
               rate=None, volume: float = 1.0) -> None:
    """Озвучить текст голосом Edge TTS (блокирующий вызов).

    text: текст для озвучки
    voice: ключ голоса ('dmitri'/'svetlana') или полное имя ('ru-RU-DmitryNeural')
    rate: темп WPM (int) или строка rate для edge-tts; None = по умолчанию
    volume: громкость 0.0..1.0
    """
    # Очистка текста: убираем символы, которые иногда вызывают NoAudioReceived
    text = text.replace("TTS", "ТТС").replace("Edge", "Эдж")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return

    name = (voice or DEFAULT_EDGE_VOICE).lower()
    full_voice = EDGE_VOICES.get(name, name)
    if full_voice not in EDGE_VOICES.values():
        # Если передали произвольное имя — используем как есть
        if not full_voice.startswith("ru-"):
            full_voice = EDGE_VOICES[DEFAULT_EDGE_VOICE]

    rate_str = rate if isinstance(rate, str) else _wpm_to_rate(rate if rate is not None else 175)

    tmp = Path(tempfile.gettempdir()) / "jarvis_edge.mp3"
    try:
        tmp.unlink(missing_ok=True)
    except Exception:
        pass

    async def _gen():
        import edge_tts
        comm = edge_tts.Communicate(text, full_voice, rate=rate_str)
        await comm.save(str(tmp))

    asyncio.run(_gen())

    if not tmp.is_file() or tmp.stat().st_size < 100:
        raise RuntimeError("edge-tts не создал аудиофайл")

    # Воспроизведение через MCI (встроенный Windows, без зависимостей)
    winmm = ctypes.windll.winmm
    alias = "jarvis_edge"
    winmm.mciSendStringW(f'close {alias}', None, 0, None)
    r = winmm.mciSendStringW(f'open "{tmp}" type mpegvideo alias {alias}', None, 0, None)
    if r != 0:
        raise RuntimeError(f"MCI open failed: {r}")
    # Громкость: MCI шкала 0..1000
    vol = max(0, min(1000, int(volume * 1000)))
    winmm.mciSendStringW(f'setaudio {alias} volume to {vol}', None, 0, None)
    winmm.mciSendStringW(f'play {alias} wait', None, 0, None)
    winmm.mciSendStringW(f'close {alias}', None, 0, None)

    try:
        tmp.unlink(missing_ok=True)
    except Exception:
        pass
