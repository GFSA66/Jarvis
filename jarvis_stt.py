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

import contextlib
import json
import os
import re
import sys
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
    "vad_silence_ms": 900,       # тишина для конца фразы (держит паузы внутри команды)
    "vad_min_rms": 120.0,        # пол порога VAD: тихая речь не теряется
    "echo_tail_ms": 400,         # пауза после речи Джарвиса (подавление эха)
    "grammar": False,            # жёсткая FST-грамматика Vosk. False = свободное
                                 # распознавание (многословные команды не режутся);
                                 # True — только для шумного фона/коротких команд.
    "debug_samples": False,      # сохранять последние WAV в ~/.jarvis/stt_samples/
    "debug_samples_max": 50,     # ротация сэмплов
    "barge_in": False,           # речь поверх TTS прерывает озвучку (по умолчанию
                                 # выкл: без эхоподавления даёт ложные срабатывания)
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


def resample_pcm(pcm: bytes, src_rate: int, dst_rate: int = 16000) -> bytes:
    """Передискретизация 16-бит моно PCM в dst_rate (чистый Python, без numpy).

    Линейная интерполяция — достаточно для речи/Vosk. Нужна, если микрофон
    отдал не 16 кГц: без неё слова той же длительности звучат «быстрее» и
    Vosk возвращает мусор (замер: 44.1 кГц как 16 кГц → «ваш что»).
    Одинаковые частоты — возврат как есть (без копии лишних данных).
    """
    if not pcm or int(src_rate) == int(dst_rate):
        return pcm
    import array
    src = array.array("h", bytes(pcm))
    n_src = len(src)
    if n_src < 2:
        return pcm
    n_dst = max(1, int(round(n_src * dst_rate / src_rate)))
    dst = array.array("h", [0]) * n_dst
    step = n_src / n_dst
    for i in range(n_dst):
        pos = i * step
        j = int(pos)
        frac = pos - j
        a = src[j]
        b = src[j + 1] if j + 1 < n_src else a
        dst[i] = int(a + (b - a) * frac)
    return dst.tobytes()


def save_debug_sample(pcm: bytes, rate: int, cfg: dict | None = None,
                      tag: str = "seg") -> str:
    """Сохранить WAV в ~/.jarvis/stt_samples/ с ротацией (по умолчанию выкл).

    Возвращает путь к файлу или «» (выключено/ошибка). Файлы нужны, чтобы
    владелец прислал запись, на которой распознавание ошиблось, и её можно
    было прогнать через tools/eval_stt.py как регрессионный тест.
    """
    try:
        cfg = cfg or {}
        if not cfg.get("debug_samples"):
            return ""
        root = Path.home() / ".jarvis" / "stt_samples"
        root.mkdir(parents=True, exist_ok=True)
        limit = max(1, int(cfg.get("debug_samples_max") or 50))
        import time as _t
        import wave as _w
        name = f"{_t.strftime('%Y%m%d-%H%M%S')}-{tag}-{int(_t.time() * 1000) % 100000}.wav"
        with _w.open(str(root / name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(rate))
            w.writeframes(bytes(pcm))
        files = sorted(root.glob("*.wav"), key=lambda p: p.stat().st_mtime)
        for old in files[:-limit]:
            try:
                old.unlink()
            except OSError:
                pass
        return str(root / name)
    except (OSError, ValueError):
        return ""


# ---------------------------------------------------------------------------
#  Бэкенды (все импорты ленивые)
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _quiet_vosk():
    """Подавить C++-предупреждения Vosk («missing in vocabulary») на Windows.

    ``vosk.SetLogLevel(-1)`` НЕ глушит эти строки: Kaldi пишет их напрямую
    в файловый дескриптор 2, минуя Python. Перенаправляем fd 2 в nul на время
    вызова и возвращаем обратно, чтобы остальные ошибки были видны.
    """
    if os.name != "nt":  # не Windows — дублировать нечего, Kaldi там тихий
        yield
        return
    try:
        sys.stderr.flush()
    except (ValueError, OSError):
        pass
    try:
        saved_fd = os.dup(2)
        nul = os.open(os.devnull, os.O_WRONLY)
        os.dup2(nul, 2)
    except OSError:  # не удалось перенаправить — просто работаем как обычно
        yield
        return
    try:
        yield
    finally:
        try:
            sys.stderr.flush()
        except (ValueError, OSError):
            pass
        os.dup2(saved_fd, 2)  # вернуть настоящий stderr
        os.close(saved_fd)
        os.close(nul)


class VoskBackend:
    """Офлайн Kaldi через vosk; с grammar — высокая точность на коротких командах."""

    name = "vosk"

    def __init__(self, cfg: dict, grammar: list[str] | None = None, use_grammar: bool = True):
        try:
            import vosk  # noqa: PLC0415
        except ImportError:
            raise STTError("Бэкенд vosk не установлен: pip install vosk") from None
        vosk.SetLogLevel(-1)
        self._vosk = vosk
        self._grammar = list(grammar or [])
        self._use_grammar = use_grammar
        path = ensure_vosk_model(str(cfg.get("model") or "small"), cfg)
        self._model = vosk.Model(str(path))
        self._recs: dict[int, object] = {}  # recognizer переиспользуется по частоте

    def _recognizer(self, rate: int):
        """Recognizer создаётся один раз на частоту и переиспользуется между фразами.

        Раньше он пересобирался каждую фразу: Kaldi заново строил грамматику и
        сыпал «Ignoring word missing in vocabulary» на каждое слово из списка.
        Между фразами делаем Reset(). Создание оборачиваем в _quiet_vosk —
        эти строки пишет C++ Kaldi напрямую в fd 2, минуя Python.
        """
        rec = self._recs.get(rate)
        if rec is None:
            gram = ""
            if self._use_grammar and self._grammar:
                # грамматика: известные слова команд + [unk] для незнакомых (диктовка)
                gram = json.dumps(self._grammar + ["[unk]"], ensure_ascii=False)
            with _quiet_vosk():
                rec = self._vosk.KaldiRecognizer(self._model, rate, gram) if gram \
                    else self._vosk.KaldiRecognizer(self._model, rate)
                rec.SetWords(True)  # без этого FinalResult не отдаёт conf по словам
            self._recs[rate] = rec
        rec.Reset()  # чистим состояние прошлой фразы перед новой
        return rec

    def transcribe(self, pcm: bytes, rate: int) -> tuple[str, float]:
        pcm16 = resample_pcm(bytes(pcm), rate, 16000)
        rec = self._recognizer(16000)
        with _quiet_vosk():  # AcceptWaveform/FinalResult тоже могут писать в C++-stderr
            rec.AcceptWaveform(pcm16)
            raw = rec.FinalResult()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return "", 0.0
        text = str(data.get("text") or "").strip()
        # Верхнеуровневого confidence в FinalResult нет — берём среднее conf слов.
        words = data.get("result") or []
        confs = [float(w.get("conf", 0.0)) for w in words
                 if isinstance(w, dict) and w.get("conf") is not None]
        if text and confs:
            conf = sum(confs) / len(confs)
        elif text:
            conf = 0.7  # текст есть, но conf недоступен — середина, как у Google
        else:
            conf = 0.0
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
        pcm16 = resample_pcm(bytes(pcm), rate, 16000)
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
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
            # grammar из настроек: по умолчанию свободное распознавание, чтобы
            # многословные команды не обрубались жёстким списком слов.
            use_grammar = bool(self.cfg.get("grammar", False))
            if name == "vosk":
                self._backends[name] = VoskBackend(self.cfg, self.grammar, use_grammar=use_grammar)
            elif name == "vosk_plain":
                self._backends[name] = VoskBackend(self.cfg, self.grammar, use_grammar=False)
            elif name == "whisper":
                self._backends[name] = WhisperBackend(self.cfg, self.command_prompt)
            elif name == "google":
                self._backends[name] = GoogleBackend(self.language)
            else:
                raise STTError(f"Неизвестный STT-движок: {name}")
        return self._backends[name]

    def _chain(self) -> list[str]:
        """Цепочка бэкендов. В конфиге оставлен неизвестный/битый движок —
        молча откатываемся на дефолт (vosk), чтобы не уронить распознавание."""
        engine = str(self.cfg.get("engine") or "vosk")
        known = {"vosk": ["vosk"], "whisper": ["whisper"], "google": ["google"],
                 "hybrid": ["vosk", "vosk_plain", "google"]}
        chain = known.get(engine)
        if chain is None:
            chain = known["vosk"]
        # страховка: выбранный движок недоступен (нет пакета/модели/сети) —
        # добавляем запасные, чтобы «недоступно» не превращалось в тишину.
        for fb in ("vosk", "google"):
            if fb not in chain:
                chain = chain + [fb]
        return chain

    def transcribe(self, pcm: bytes, rate: int) -> STTResult:
        engine = str(self.cfg.get("engine") or "vosk")
        chain = self._chain()
        text, conf, used, last_err = "", 0.0, chain[0], None
        for name in chain:
            try:
                text, conf = self._backend(name).transcribe(pcm, rate)
            except STTError as e:
                last_err = e
                continue  # движок недоступен (нет пакета/модели/сети) — пробуем следующий
            used = name
            # Уходим на запасной движок по причине «недоступен», но НЕ по низкой
            # уверенности: иначе офлайн-vosk тихо сливал бы звук в онлайн-Google.
            # Исключение — hybrid, где повторный проход по уверенности и задуман.
            if engine != "hybrid" or (text and conf >= self.confidence_min()):
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

    silence_frames можно задать напрямую (старые тесты) либо через
    silence_ms + frame_ms: конец фразы после silence_ms тишины. Дефолт
    900 мс — держит паузы 300–500 мс внутри многословных команд.
    """

    def __init__(self, margin: float = 2.0, min_rms: float = 120.0,
                 silence_frames: int | None = None, min_speech_frames: int = 3,
                 silence_ms: float = 900.0, frame_ms: float = 30.0):
        self.margin = margin
        self.min_rms = min_rms
        if silence_frames is None:
            silence_frames = max(1, int(round(silence_ms / max(1.0, frame_ms))))
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
        # смесь латиницы и кириллицы («bяркость» из \b в regex паттерна) — мусор
        if re.search(r"[a-z]", w) and re.search(r"[а-я]", w):
            continue
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out
