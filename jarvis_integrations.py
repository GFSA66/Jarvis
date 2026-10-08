"""Интеграции: Telegram, Discord, погода (Open-Meteo), чтение уведомлений.

Всё через urllib — новых обязательных зависимостей нет. keyring (если
установлен) для секретов, иначе config.json с предупреждением в настройках.
Windows-импорты — только внутри функций.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "Jarvis/1.0 (voice assistant)"


def _http(url: str, data: dict | None = None, timeout: float = 15.0) -> dict:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        url, data=body, method="POST" if body else "GET",
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else {}


def _http_get(url: str, timeout: float = 15.0) -> dict | str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except ValueError:
        return raw


# ============================================================================
#  Telegram (Bot API)
# ============================================================================

def telegram_send(token: str, chat_id: str, text: str,
                  timeout: float = 15.0) -> dict:
    """Отправить сообщение ботом. Ошибки — IntegrationError с текстом для голоса."""
    if not token or not chat_id:
        raise IntegrationError("не заданы токен бота или chat_id в настройках "
                               "(вкладка «Интеграции»)")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        data = _http(url, {"chat_id": chat_id, "text": text}, timeout)
    except urllib.error.HTTPError as e:
        raise IntegrationError(f"Telegram ответил ошибкой {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise IntegrationError(f"нет связи с Telegram: {e}") from e
    if not data.get("ok"):
        raise IntegrationError(f"Telegram: {data.get('description', 'отказ')}")
    return data


def telegram_updates(token: str, timeout: float = 15.0) -> list[dict]:
    """Последние входящие сообщения (getUpdates) — для «прочитай уведомления»."""
    if not token:
        raise IntegrationError("не задан токен Telegram-бота (вкладка «Интеграции»)")
    url = f"https://api.telegram.org/bot{token}/getUpdates?limit=10"
    try:
        data = _http_get(url, timeout)
    except urllib.error.HTTPError as e:
        raise IntegrationError(f"Telegram ответил ошибкой {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise IntegrationError(f"нет связи с Telegram: {e}") from e
    if isinstance(data, dict) and not data.get("ok"):
        raise IntegrationError(f"Telegram: {data.get('description', 'отказ')}")
    out = []
    for item in (data.get("result") if isinstance(data, dict) else []) or []:
        msg = item.get("message") or {}
        text = str(msg.get("text") or "").strip()
        if not text or text.startswith("/"):
            continue
        who = ((msg.get("from") or {}).get("first_name")
               or (msg.get("chat") or {}).get("title") or "?")
        out.append({"from": str(who), "text": text,
                    "time": int(msg.get("date") or 0)})
    return out


# ============================================================================
#  Discord (webhook)
# ============================================================================

def discord_send(webhook_url: str, text: str, timeout: float = 15.0) -> None:
    if not webhook_url or "discord.com/api/webhooks" not in webhook_url:
        raise IntegrationError("не задан webhook-адрес канала (вкладка «Интеграции»)")
    try:
        data = _http(webhook_url, {"content": text}, timeout)
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            raise IntegrationError("Discord webhook недействителен — обнови его "
                                   "в настройках") from e
        raise IntegrationError(f"Discord ответил ошибкой {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise IntegrationError(f"нет связи с Discord: {e}") from e
    if isinstance(data, dict) and data.get("message") and not data.get("id"):
        raise IntegrationError(f"Discord: {data['message']}")


# ============================================================================
#  Weather (Open-Meteo, no API key)
# ============================================================================

def weather_get(lat: float, lon: float, timezone: str = "auto",
                timeout: float = 15.0) -> dict:
    """Получить текущую погоду и прогноз на сегодня от Open-Meteo."""
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&current_weather=true"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode"
        f"&timezone={urllib.parse.quote(timezone)}"
    )
    try:
        data = _http_get(url, timeout)
    except urllib.error.HTTPError as e:
        raise IntegrationError(f"Open-Meteo ответил ошибкой {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise IntegrationError(f"нет связи с Open-Meteo: {e}") from e
    if isinstance(data, dict) and "current_weather" not in data:
        raise IntegrationError(f"Open-Meteo: неожиданный ответ")
    return data


def weather_format(data: dict, city_name: str = "вашем городе") -> str:
    """Краткое текстовое описание погоды для озвучки."""
    cw = data.get("current_weather") or {}
    temp = cw.get("temperature")
    wind = cw.get("windspeed")
    code = cw.get("weathercode")
    daily = data.get("daily") or {}
    tmax = (daily.get("temperature_2m_max") or [None])[0]
    tmin = (daily.get("temperature_2m_min") or [None])[0]
    pop = (daily.get("precipitation_probability_max") or [None])[0]

    desc = _weather_code_desc(code)
    parts = [f"В {city_name} сейчас {desc}."]
    if temp is not None:
        parts.append(f"Температура {temp:.0f}°C")
    if tmin is not None and tmax is not None:
        parts.append(f"от {tmin:.0f} до {tmax:.0f}°C")
    if pop is not None:
        parts.append(f"вероятность осадков {pop}%")
    if wind is not None:
        parts.append(f"ветер {wind:.0f} км/ч")
    return ". ".join(parts) + "."


_WEATHER_CODES = {
    0: "ясно", 1: "преимущественно ясно", 2: "частично облачно", 3: "пасмурно",
    45: "туман", 48: "изморозь",
    51: "морось", 53: "морось", 55: "морось", 56: "ледяная морось", 57: "ледяная морось",
    61: "дождь", 63: "дождь", 65: "сильный дождь", 66: "ледяной дождь", 67: "ледяной дождь",
    71: "снег", 73: "снег", 75: "сильный снег", 77: "снежные крупинки",
    80: "ливень", 81: "ливень", 82: "сильный ливень",
    85: "снегопад", 86: "сильный снегопад",
    95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}


def _weather_code_desc(code: int | None) -> str:
    if code is None:
        return "неизвестно"
    return _WEATHER_CODES.get(code, f"код {code}")


# ============================================================================
#  Clipboard (Windows)
# ============================================================================

def clip_read() -> str | None:
    """Прочитать текст из буфера обмена (Windows)."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        CF_UNICODETEXT = 13
        if not user32.OpenClipboard(None):
            return None
        try:
            if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None
            h = user32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return None
            p = kernel32.GlobalLock(h)
            if not p:
                return None
            try:
                return ctypes.string_at(p, kernel32.GlobalSize(h)).decode("utf-16-le").rstrip(chr(0))
            finally:
                kernel32.GlobalUnlock(h)
        finally:
            user32.CloseClipboard()
    except Exception:
        return None


def clip_write(text: str) -> bool:
    """Положить текст в буфер обмена (Windows)."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        data = text.encode("utf-16-le") + b"\0\0"
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h:
                return False
            p = kernel32.GlobalLock(h)
            if not p:
                kernel32.GlobalFree(h)
                return False
            ctypes.memmove(p, data, len(data))
            kernel32.GlobalUnlock(h)
            if not user32.SetClipboardData(CF_UNICODETEXT, h):
                kernel32.GlobalFree(h)
                return False
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


def clip_backup() -> bytes | None:
    """Сохранить текущее содержимое буфера (все форматы не получим, только текст)."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        CF_UNICODETEXT = 13
        if not user32.OpenClipboard(None):
            return None
        try:
            if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None
            h = user32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return None
            p = kernel32.GlobalLock(h)
            if not p:
                return None
            try:
                size = kernel32.GlobalSize(h)
                return ctypes.string_at(p, size)
            finally:
                kernel32.GlobalUnlock(h)
        finally:
            user32.CloseClipboard()
    except Exception:
        return None


def clip_restore(data: bytes) -> bool:
    """Восстановить буфер из сохранённых байтов."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h:
                return False
            p = kernel32.GlobalLock(h)
            if not p:
                kernel32.GlobalFree(h)
                return False
            ctypes.memmove(p, data, len(data))
            kernel32.GlobalUnlock(h)
            if not user32.SetClipboardData(CF_UNICODETEXT, h):
                kernel32.GlobalFree(h)
                return False
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


# ============================================================================
#  Windows Notifications (UserNotificationListener - experimental)
# ============================================================================

def win_notifications_read(limit: int = 10) -> list[dict]:
    """
    Прочитать последние уведомления Windows через winsdk/winrt (экспериментально).
    Возвращает список словарей: app, title, body, time.
    Если winsdk недоступен — поднимает IntegrationError.
    """
    try:
        import winrt.windows.ui.notifications.management as unm
        import winrt.windows.foundation as wf
    except ImportError as e:
        raise IntegrationError(
            "winsdk/winrt не установлен. Для чтения уведомлений Windows "
            "установите: pip install winsdk"
        ) from e

    async def _fetch():
        listener = unm.UserNotificationListener()
        access = await listener.get_access_status_async()
        if access != unm.UserNotificationListenerAccessStatus.allowed:
            raise IntegrationError(
                "доступ к уведомлениям Windows не разрешён. "
                "Настройки -> Конфиденциальность -> Уведомления -> разрешите для этого приложения."
            )
        notifs = await listener.get_notifications_async(limit)
        out = []
        for n in notifs:
            app = n.app_info.display_info.display_name if n.app_info and n.app_info.display_info else "?"
            binding = n.notification.visual.get_binding(unm.NotificationBinding.get_toast_generic())
            title = binding.get_text(0) if binding else ""
            body = binding.get_text(1) if binding else ""
            time = n.notification.creation_time
            out.append({"app": str(app), "title": str(title), "body": str(body), "time": int(time)})
        return out

    import asyncio
    return asyncio.run(_fetch())


# ============================================================================
#  AI Translation (through jarvis_ai)
# ============================================================================

def ai_translate(text: str, target_lang: str, api_key: str, model: str = "gpt-4o-mini") -> str:
    """Перевести текст через нейросеть (jarvis_ai)."""
    if not api_key:
        raise IntegrationError("не задан API-ключ для нейросети (вкладка «Нейросеть» / «Интеграции»)")
    try:
        import jarvis_ai
    except ImportError:
        raise IntegrationError("модуль jarvis_ai недоступен")
    assistant = jarvis_ai.AIAssistant(api_key=api_key, model=model)
    prompt = f"Переведи на {target_lang} (только перевод, без объяснений):\n\n{text}"
    return assistant.ask(prompt)


# ============================================================================
#  Keyring (optional)
# ============================================================================

def keyring_get(service: str, key: str) -> str | None:
    try:
        import keyring
        return keyring.get_password(service, key)
    except Exception:
        return None


def keyring_set(service: str, key: str, value: str) -> bool:
    try:
        import keyring
        keyring.set_password(service, key, value)
        return True
    except Exception:
        return False


def keyring_delete(service: str, key: str) -> bool:
    try:
        import keyring
        keyring.delete_password(service, key)
        return True
    except Exception:
        return False


class IntegrationError(Exception):
    pass
