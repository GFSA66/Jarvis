"""Слой распознавания речи (STT) с несколькими бэкендами.

Бэкенды выбираются в config.json → секция «stt» (engine):
  vosk   — офлайн, KaldiRecognizer + грамматика из слов команд (по умолчанию);
  whisper — офлайн, faster-whisper (маленькая модель, int8);
  google  — текущий recognize_google (запасной, требует сети);
  hybrid  — vosk с грамматикой, при низкой уверенности/пустом тексте —
            vosk без грамматики, затем google (если есть сеть).

Модели скачиваются при первом запуске в ~/.jarvis/models (не в репозиторий
и не в exe). Модуль чистый: Windows/PyAudio импортируются лениво, поэтому
логика VAD и фильтров тестируется в Linux CI.
"""
from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Детерминированные дефолты для старых config.json без секции «stt»
DEFAULTS = {
    "engine": "vosk",            # vosk | whisper | google | hybrid
    "model": "small",            # small (vosk-model-small-ru-0.22) | large (vosk-model-ru-0.42)
    "whisper_model": "small",
    "confidence_min": 0.35,      # ниже — фраза молча отбрасывается
    "models_dir": "",            # пусто → ~/.jarvis/models
    "prebuffer_ms": 400,         # предзапись до начала речи (не режет первое слово)
    "vad_energy_margin": 2.0,    # во сколько раз энергия речи выше тишины
    "echo_tail_ms": 400,         # пауза после речи Джарвиса (подавление эха)
}

VOSK_MODELS = {
    "small": ("vosk-model-small-ru-0.22",
              "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"),
    "large": ("vosk-model-ru-0.42",
              "https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip"),
}


class STTError(Exception):
    """Понятная ошибка STT: нет модели, нет сети, бэкенд не установлен."""


@dataclass
class STTResult:
    text: str
    confidence: float
    engine: str
    rejected: str = ""       # почему отброшено (пусто — не отброшено)


# ---------------------------------------------------------------------------
#  Модели
# ---------------------------------------------------------------------------

def models_dir(cfg: dict | None = None) -> Path:
    custom = str((cfg or {}).get("models_dir") or "").strip()
    p = Path(os.path.expanduser(custom)) if custom else Path.home() / ".jarvis" / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_vosk_model(kind: str, cfg: dict | None = None, log=None) -> Path:
    """Скачать и распаковать модель Vosk при первом запуске. Понятная ошибка без сети."""
    if kind not in VOSK_MODELS:
        kind = "small"
    name, url = VOSK_MODELS[kind]
    root = models_dir(cfg)
    path = root / name
    if (path / "am").exists():
        return path
    archive = root / f"{name}.zip"
    if not archive.exists():
        try:
            _download(url, archive, log=log)
        except OSError as e:
            archive.unlink(missing_ok=True)
            raise STTError(
                f"Не удалось скачать модель распознавания «{name}» (нужен интернет "
                f"при первом запуске): {e}") from None
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(root)
    except (zipfile.BadZipFile, OSError) as e:
        archive.unlink(missing_ok=True)
        raise STTError(f"Архив модели повреждён, удалён: {archive.name} ({e}). "
                       "Запусти ещё раз — скачается заново.") from None
    if not (path / "am").exists():
        archive.unlink(missing_ok=True)
        raise STTError(f"В архиве не оказалась папка {name}. Проверь models_dir.")
    archive.unlink(missing_ok=True)
    return path


def _download(url: str, dest: Path, log=None) -> None:
    """Скачивание с прогрессом в % (строка статуса через log)."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if log and total:
                    log(f"Скачиваю модель: {100 * done // total}%")


# ---------------------------------------------------------------------------
#  Бэкенды (все импорты ленивые)
# ---------------------------------------------------------------------------

class VoskBackend:
    """Офлайн Kaldi через vosk; с grammar — высокая точность на коротких командах."""

    name = "vosk"

    def __init__(self, cfg: dict, grammar: list[str] | None = None, use_grammar: bool = True):
        try:
            import vosk  # noqa: PLC0415
        except ImportError:
            raise STTError("Бэкенд vosk не установлен: pip install vosk") from None
        vosk.Set_log_level(-1)
        self._vosk = vosk
        self._grammar = list(grammar or [])
        self._use_grammar = use_grammar
        path = ensure_vosk_model(str(cfg.get("model") or "small"), cfg)
        self._model = vosk.Model(str(path))

    def transcribe(self, pcm: bytes, rate: int) -> tuple[str, float]:
        gram = ""
        if self._use_grammar and self._grammar:
            # грамматика: известные слова команд + [unk] для незнакомых (диктовка)
            gram = json.dumps(self._grammar + ["[unk]"], ensure_ascii=False)
        rec = self._vosk.KaldiRecognizer(self._model, rate, gram) if gram \
            else self._vosk.KaldiRecognizer(self._model, rate)
        rec.AcceptWaveform(bytes(pcm))
        try:
            data = json.loads(rec.FinalResult())
        except json.JSONDecodeError:
            return "", 0.0
        text = str(data.get("text") or "").strip()
        conf = float(data.get("confidence") or 0.0)
        return text, conf


class WhisperBackend:
    """Офлайн faster-whisper: для диктовки и длинных фраз (int8, VAD внутри)."""

    name = "whisper"

    def __init__(self, cfg: dict, command_prompt: str = ""):
        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415
        except ImportError:
            raise STTError("Бэкенд whisper не установлен: pip install faster-whisper") from None
        size = str(cfg.get("whisper_model") or "small")
        self._model = WhisperModel(size, device="cpu", compute_type="int8")
        self._prompt = command_prompt

    def transcribe(self, pcm: bytes, rate: int) -> tuple[str, float]:
        import numpy as np  # noqa: PLC0415
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            audio, language="ru", beam_size=1, vad_filter=True,
            initial_prompt=self._prompt or None)
        parts, logprobs = [], []
        for seg in segments:
            parts.append(seg.text.strip())
            logprobs.append(getattr(seg, "avg_logprob", -0.5) or -0.5)
        text = " ".join(p for p in parts if p).strip()
        if not logprobs:
            return "", 0.0
        avg = sum(logprobs) / len(logprobs)
        conf = max(0.0, min(1.0, 1.0 + avg / 2.0))  # avg_logprob [-2..0] → conf [0..1]
        return text, conf


class GoogleBackend:
    """Бесплатный онлайн Google (текущий движок) — запасной."""

    name = "google"

    def __init__(self, language: str = "ru-RU"):
        self._language = language

    def transcribe(self, pcm: bytes, rate: int) -> tuple[str, float]:
        try:
            import speech_recognition as sr  # noqa: PLC0415
        except ImportError:
            raise STTError("speech_recognition не установлен") from None
        rec = sr.Recognizer()
        audio = sr.AudioData(pcm, rate, 2)
        try:
            text = rec.recognize_google(audio, language=self._language)
        except sr.UnknownValueError:
            return "", 0.0
        except sr.RequestError as e:
            raise STTError(f"Нет связи с сервисом Google: {e}") from None
        return str(text).strip(), 0.7  # у Google нет уверенности — условная середина


# ---------------------------------------------------------------------------
#  Диспетчер бэкендов
# ---------------------------------------------------------------------------

class STTEngine:
    """transcribe(pcm, rate) → STTResult; фильтрация мусора до маршрутизации."""

    def __init__(self, cfg: dict, grammar: list[str] | None = None,
                 language: str = "ru-RU", command_prompt: str = ""):
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.language = language
        self.grammar = list(grammar or [])
        self.command_prompt = command_prompt
        self._backends: dict[str, object] = {}

    def confidence_min(self) -> float:
        try:
            return float(self.cfg.get("confidence_min", DEFAULTS["confidence_min"]))
        except (TypeError, ValueError):
            return DEFAULTS["confidence_min"]

    def _backend(self, name: str):
        if name not in self._backends:
            if name == "vosk":
                self._backends[name] = VoskBackend(self.cfg, self.grammar, use_grammar=True)
            elif name == "vosk_plain":
                self._backends[name] = VoskBackend(self.cfg, self.grammar, use_grammar=False)
            elif name == "whisper":
                self._backends[name] = WhisperBackend(self.cfg, self.command_prompt)
            elif name == "google":
                self._backends[name] = GoogleBackend(self.language)
            else:
                raise STTError(f"Неизвестный STT-движок: {name}")
        return self._backends[name]

    def transcribe(self, pcm: bytes, rate: int) -> STTResult:
        engine = str(self.cfg.get("engine") or "vosk")
        chain = {"vosk": ["vosk"], "whisper": ["whisper"], "google": ["google"],
                 "hybrid": ["vosk", "vosk_plain", "google"]}.get(engine, ["vosk"])
        text, conf, used, last_err = "", 0.0, chain[0], None
        for name in chain:
            try:
                text, conf = self._backend(name).transcribe(pcm, rate)
            except STTError as e:
                last_err = e
                continue
            used = name
            if text and conf >= self.confidence_min():
                break
        if not text and last_err:
            raise last_err
        t = text.strip()
        rejected = ""
        if not t:
            rejected = "тишина"
        elif conf < self.confidence_min():
            rejected = f"уверенность {conf:.2f} < {self.confidence_min():.2f}"
        return STTResult(t, conf, used, rejected)


# ---------------------------------------------------------------------------
#  Энергетический VAD с адаптивным порогом (чистый, без C-расширений)
# ---------------------------------------------------------------------------

class StreamVAD:
    """Детекция речи по энергии чанков с адаптивным порогом тишины.

    feed(rms) → «speech» | «silence» | None; порог = шум × margin,
    порог адаптируется к фоновому шуму во время пауз.
    """

    def __init__(self, margin: float = 2.0, min_rms: float = 300.0,
                 silence_frames: int = 12, min_speech_frames: int = 3):
        self.margin = margin
        self.min_rms = min_rms
        self.silence_frames = silence_frames
        self.min_speech_frames = min_speech_frames
        self._noise = min_rms          # адаптивная оценка тишины
        self._in_speech = False
        self._speech_frames = 0
        self._silence_after_speech = 0

    @property
    def threshold(self) -> float:
        return max(self.min_rms, self._noise * self.margin)

    def feed(self, rms: float) -> str | None:
        """rms чанка; «speech» — начало/продолжение речи, «silence» — тишина."""
        if rms < self.threshold:
            if self._in_speech:
                self._silence_after_speech += 1
                if self._silence_after_speech >= self.silence_frames:
                    self._in_speech = False
                    self._speech_frames = 0
                    self._silence_after_speech = 0
                    return "silence"       # конец фразы
                return None
            # тишина до речи — уточняем порог (адаптивный шум)
            self._noise = 0.95 * self._noise + 0.05 * rms
            return "silence"
        # энергия выше порога — возможная речь
        self._speech_frames += 1
        if not self._in_speech and self._speech_frames >= self.min_speech_frames:
            self._in_speech = True
            self._silence_after_speech = 0
            return "speech"
        return "speech" if self._in_speech else None

    def reset(self) -> None:
        self._in_speech = False
        self._speech_frames = 0
        self._silence_after_speech = 0


def build_grammar(words) -> list[str]:
    """Слова грамматики Vosk: осмысленные токены, дедуп, без мусора."""
    out: list[str] = []
    seen: set[str] = set()
    for w in words:
        w = str(w).lower().replace("ё", "е").strip()
        if not w or len(w) < 2 or not re.fullmatch(r"[a-zа-я0-9\-]+", w):
            continue
        if not re.search(r"[a-zа-я]", w):
            continue  # чисто цифры — не слова грамматики
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out
