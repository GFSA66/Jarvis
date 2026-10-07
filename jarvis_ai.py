"""Нейросеть для Джарвиса.

Работает с любым OpenAI-совместимым API (Google Gemini, Groq, OpenRouter и т.д.) через обычный urllib:
никаких новых библиотек для exe не нужно. Отвечает коротко, чтобы ответ можно было озвучить.

К вопросу добавляется контекст: железо ПК, установленные игры Steam, время, режим (игровой/учебный)
и, если спросили про погоду, прогноз Open-Meteo (бесплатно, без ключа).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path

PRESETS = {
    "gemini": {
        "label": "Google Gemini (бесплатно)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.5-flash-lite",
        "key_url": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "label": "Groq (бесплатно, очень быстро)",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_url": "https://console.groq.com/keys",
    },
    "openrouter": {
        "label": "OpenRouter (бесплатные модели)",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "key_url": "https://openrouter.ai/keys",
    },
    "custom": {"label": "Свой (OpenAI-совместимый)", "base_url": "", "model": "", "key_url": ""},
}

# Cloudflare у части провайдеров режет стандартный User-Agent Python — представляемся браузером.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Jarvis/1.0"

QUESTION_STARTS = {
    "какой", "какая", "какое", "какие", "какую", "какого", "каком", "каким", "какими",
    "что", "чем", "кто", "как", "почему", "зачем", "сколько", "когда", "где", "куда", "откуда",
    "можно", "стоит", "посоветуй", "посоветуешь", "подскажи", "расскажи", "скажи", "объясни",
    "придумай", "помоги", "порекомендуй", "сравни", "переведи", "посчитай", "сколько",
}
WEATHER_WORDS = ("погод", "дожд", "снег", "зонт", "температур", "градус", "холодно", "тепло",
                 "жарко", "ветер", "куртк", "прогноз", "на улице")
WMO = {
    0: "ясно", 1: "преимущественно ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "изморозь", 51: "слабая морось", 53: "морось", 55: "сильная морось",
    56: "ледяная морось", 57: "ледяная морось", 61: "небольшой дождь", 63: "дождь",
    65: "сильный дождь", 66: "ледяной дождь", 67: "ледяной дождь", 71: "небольшой снег",
    73: "снег", 75: "сильный снег", 77: "снежная крупа", 80: "ливень", 81: "ливень",
    82: "сильный ливень", 85: "снегопад", 86: "сильный снегопад", 95: "гроза",
    96: "гроза с градом", 99: "гроза с градом",
}


class AIError(Exception):
    """Понятная человеку ошибка (её можно озвучить)."""


def is_question(text: str) -> bool:
    words = text.strip().split()
    return bool(words) and (words[0] in QUESTION_STARTS or text.startswith(("есть ли", "а что", "а как")))


# ============================================================================
#  Запрос к API
# ============================================================================

def resolve(ai: dict) -> tuple[str, str, str]:
    """(адрес, модель, ключ): пустые поля берутся из пресета, ключ — ещё и из JARVIS_AI_KEY."""
    preset = PRESETS.get(ai.get("provider") or "gemini", PRESETS["custom"])
    base = (ai.get("base_url") or preset["base_url"]).strip()
    model = (ai.get("model") or preset["model"]).strip()
    key = (ai.get("api_key") or os.environ.get("JARVIS_AI_KEY") or "").strip()
    return base, model, key


def _http_message(e: urllib.error.HTTPError, model: str) -> str:
    detail = ""
    try:
        data = json.loads(e.read().decode("utf-8", "replace"))
        if isinstance(data, list) and data:
            data = data[0]
        err = data.get("error", data) if isinstance(data, dict) else {}
        detail = str(err.get("message") if isinstance(err, dict) else err)[:200]
    except Exception:
        pass
    if e.code in (401, 403):
        return "Нейросеть не приняла API-ключ. Проверь ключ в настройках." + (f" ({detail})" if detail else "")
    if e.code == 404:
        return f"Модель «{model}» не найдена. Поменяй модель в настройках." + (f" ({detail})" if detail else "")
    if e.code == 429:
        return "Превышен лимит бесплатных запросов. Подожди минуту."
    return f"Ошибка нейросети {e.code}." + (f" {detail}" if detail else "")


def chat(ai: dict, messages: list, timeout: float = 25.0) -> str:
    base, model, key = resolve(ai)
    if not key:
        raise AIError("Не указан API-ключ нейросети. Открой настройки, вкладка «Нейросеть».")
    if not base or not model:
        raise AIError("Не указаны адрес или модель нейросети.")
    body = {"model": model, "messages": messages,
            "max_tokens": int(ai.get("max_tokens") or 400), "temperature": 0.7}
    body.update(ai.get("extra") or {})
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise AIError(_http_message(e, model)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AIError("Нет связи с нейросетью.") from None
    except ValueError:
        raise AIError("Нейросеть вернула непонятный ответ.") from None
    try:
        choice = data["choices"][0]
        text = (choice["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        raise AIError("Нейросеть вернула непонятный ответ.") from None
    if not text:
        if choice.get("finish_reason") == "length":
            raise AIError("Ответ нейросети оборвался. Увеличь max_tokens в config.json (ai).")
        raise AIError("Нейросеть вернула пустой ответ.")
    return text


def clean_for_speech(text: str, max_chars: int = 420) -> str:
    """Убираем всё, что синтезатор прочитает вслух как мусор: markdown, ссылки, эмодзи."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#`>~|]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"[\U00010000-\U0010ffff☀-➿️]", "", text)  # эмодзи и символы
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        cut = text[:max_chars]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = cut[:end + 1] if end > 80 else cut.rstrip() + "…"
    return text


# ============================================================================
#  Контекст: ПК, Steam, погода
# ============================================================================

_PS_INFO = r"""[Console]::OutputEncoding = [Text.Encoding]::UTF8
$o = [ordered]@{
  os  = (Get-CimInstance Win32_OperatingSystem).Caption
  cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)
  gpu = @(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name)
  ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
}
$o | ConvertTo-Json -Compress"""

_SKIP_APPS = ("steamworks", "proton", "steam linux runtime", "steamvr", "redistributable")


def hardware_info() -> dict:
    if sys.platform != "win32":
        return {}
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", _PS_INFO], stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        return json.loads(r.stdout.decode("utf-8", "replace").strip() or "{}")
    except Exception:
        return {}


def steam_games(steam_exe) -> list:
    """[(название, когда запускал (unix-время, 0 — не запускал))] по манифестам установленных игр."""
    if not steam_exe:
        return []
    root = Path(steam_exe).parent / "steamapps"
    libs = {root}
    try:
        txt = (root / "libraryfolders.vdf").read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
            libs.add(Path(m.group(1).replace("\\\\", "\\")) / "steamapps")
    except OSError:
        pass
    games = {}
    for lib in libs:
        try:
            manifests = list(lib.glob("appmanifest_*.acf"))
        except OSError:
            continue
        for acf in manifests:
            try:
                txt = acf.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            name = re.search(r'"name"\s+"([^"]*)"', txt)
            if not name or any(s in name.group(1).lower() for s in _SKIP_APPS):
                continue
            last = re.search(r'"LastPlayed"\s+"(\d+)"', txt)
            games[name.group(1)] = int(last.group(1)) if last else 0
    return sorted(games.items(), key=lambda g: -g[1])


def _ago(ts: int) -> str:
    if not ts:
        return "ни разу не запускал"
    days = int((time.time() - ts) // 86400)
    return "запускал сегодня" if days <= 0 else f"запускал {days} дн. назад"


def _get_json(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ============================================================================
#  Помощник
# ============================================================================

class Assistant:
    """get_ai_cfg() -> dict настроек; get_context() -> {"mode", "steam_exe", "launchers", "known_games"}."""

    def __init__(self, get_ai_cfg, get_context):
        self.get_ai_cfg, self.get_context = get_ai_cfg, get_context
        self.history: deque = deque(maxlen=8)
        self.last_used = 0.0
        self._hw = None
        self._games = None
        self._geo: dict = {}
        self._weather = (0.0, "")
        self.lock = threading.Lock()  # один вопрос за раз

    # --- контекст ---------------------------------------------------------
    def _pc_text(self, ctx: dict, ai: dict) -> str:
        if not ai.get("pc_context", True):
            return ""
        if self._hw is None:
            self._hw = hardware_info()
        if self._games is None or time.time() - self._games[0] > 600:
            self._games = (time.time(), steam_games(ctx.get("steam_exe")))
        hw, lines = self._hw, []
        if hw:
            gpu = hw.get("gpu") or []
            gpu = ", ".join(gpu) if isinstance(gpu, list) else gpu
            lines.append(f"Компьютер: {hw.get('os', 'Windows')}, процессор {hw.get('cpu', '?')}, "
                         f"видеокарта {gpu or '?'}, оперативной памяти {hw.get('ram', '?')} ГБ.")
        games = self._games[1]
        if games:
            lines.append(f"Установленные игры Steam ({len(games)}): " +
                         "; ".join(f"{n} ({_ago(t)})" for n, t in games[:40]) + ".")
        if ctx.get("launchers"):
            lines.append("Также установлены: " + ", ".join(ctx["launchers"]) + ".")
        if ctx.get("known_games"):
            lines.append("Игры, которые Джарвис умеет запускать голосом: " + ", ".join(ctx["known_games"][:30]) + ".")
        return "\n".join(lines)

    def weather_text(self, city: str) -> str:
        if time.time() - self._weather[0] < 600 and self._weather[1]:
            return self._weather[1]
        try:
            if city not in self._geo:
                g = _get_json("https://geocoding-api.open-meteo.com/v1/search?count=1&language=ru&name="
                              + urllib.parse.quote(city))
                hit = g["results"][0]
                self._geo[city] = (hit["latitude"], hit["longitude"], hit.get("name", city))
            lat, lon, name = self._geo[city]
            w = _get_json(
                "https://api.open-meteo.com/v1/forecast?timezone=auto&forecast_days=2"
                f"&latitude={lat}&longitude={lon}"
                "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
                "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max")
            c, d = w["current"], w["daily"]
            text = (f"Погода в городе {name} сейчас: {WMO.get(c['weather_code'], 'без данных')}, "
                    f"{c['temperature_2m']:.0f}°C, ощущается как {c['apparent_temperature']:.0f}°C, "
                    f"ветер {c['wind_speed_10m']:.0f} км/ч. "
                    f"Сегодня от {d['temperature_2m_min'][0]:.0f} до {d['temperature_2m_max'][0]:.0f}°C, "
                    f"вероятность осадков {d['precipitation_probability_max'][0] or 0}%. "
                    f"Завтра: {WMO.get(d['weather_code'][1], 'без данных')}, "
                    f"от {d['temperature_2m_min'][1]:.0f} до {d['temperature_2m_max'][1]:.0f}°C, "
                    f"осадки {d['precipitation_probability_max'][1] or 0}%.")
        except Exception:
            return "Данные о погоде получить не удалось — так и скажи."
        self._weather = (time.time(), text)
        return text

    def system_prompt(self, question: str, ai: dict, ctx: dict) -> str:
        now = datetime.now()
        days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        parts = [
            "Ты — Джарвис, голосовой ассистент на компьютере пользователя (Windows). Твои ответы озвучивает синтезатор речи.",
            "Правила: отвечай на том языке, на котором задан вопрос (по умолчанию по-русски). Коротко: одно-два предложения, "
            "не больше тридцати слов. Без markdown, списков, эмодзи, ссылок и скобок. Не выдумывай: если данных не хватает, "
            "так и скажи. Если спрашивают, что поиграть или запустить, выбирай из данных о компьютере ниже и называй конкретную игру. "
            "Если нужно действие на компьютере (открыть сайт, запустить программу), подскажи, что для этого есть голосовые команды.",
            f"Сейчас: {days[now.weekday()]}, {now:%d.%m.%Y}, {now:%H:%M}. Режим Джарвиса: {ctx.get('mode', 'игровой')}.",
        ]
        pc = self._pc_text(ctx, ai)
        if pc:
            parts.append(pc)
        if any(w in question.lower() for w in WEATHER_WORDS):
            parts.append(self.weather_text(ai.get("city") or "Днепр"))
        return "\n".join(parts)

    # --- вопрос -----------------------------------------------------------
    def ask(self, question: str) -> str:
        ai = self.get_ai_cfg()
        ctx = self.get_context()
        if time.time() - self.last_used > 300:  # давно не говорили — забываем прошлый разговор
            self.history.clear()
        messages = ([{"role": "system", "content": self.system_prompt(question, ai, ctx)}]
                    + list(self.history) + [{"role": "user", "content": question}])
        text = clean_for_speech(chat(ai, messages))
        self.history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": text}])
        self.last_used = time.time()
        return text


def test_connection(ai: dict) -> tuple:
    """Проверка из окна настроек: (успех, текст ответа или ошибки)."""
    try:
        probe = dict(ai, max_tokens=max(int(ai.get("max_tokens") or 0), 200))
        return True, clean_for_speech(chat(probe, [{"role": "user", "content": "Ответь одним словом: работает."}], 20))
    except AIError as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, f"Ошибка: {e}"
