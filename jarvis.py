#!/usr/bin/env python3
"""Джарвис — голосовой ассистент для Windows.

Запуск:   start.bat   (или:  python jarvis.py)
Проверка: python jarvis.py --check        — что найдено на этом ПК
          python jarvis.py --list-voices  — доступные голоса TTS

Все пути к программам определяются автоматически (реестр, переменные окружения,
типовые папки, все диски). Личные настройки лежат в config.json
(см. config.example.json) и в git не попадают.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
import glob
import json
import os
import queue
import re
import shutil
import string
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from collections import namedtuple
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

if sys.platform != "win32":
    sys.exit("Джарвис работает только на Windows.")

import tkinter as tk
import winreg

try:
    import pyaudiowpatch as _pyaudio_fork
    sys.modules["pyaudio"] = _pyaudio_fork
except ImportError:
    pass

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    import gettext as _gettext

    _orig_translation = _gettext.translation

    def _translation_with_fallback(*args, **kwargs):
        # ytmusicapi грузит .mo-файлы локализации; в .exe (PyInstaller) их нет
        # и gettext падает. fallback=True возвращает исходные строки.
        kwargs.setdefault("fallback", True)
        return _orig_translation(*args, **kwargs)

    _gettext.translation = _translation_with_fallback
except ImportError:
    pass

try:
    from ytmusicapi import YTMusic
except ImportError:
    YTMusic = None

try:
    import speech_recognition as sr
    import pyautogui
    import win32con
    import win32gui
except ImportError as _e:
    sys.exit(f"Не хватает библиотеки: {_e.name}\n"
             f"Установи зависимости:  pip install -r requirements.txt")

try:
    import customtkinter as ctk
    import jarvis_settings
except ImportError:  # без customtkinter всё работает, кроме окна настроек
    ctk = None
    jarvis_settings = None

try:
    import jarvis_ai
except ImportError:
    jarvis_ai = None

pyautogui.FAILSAFE = False

# ============================================================================
#  Конфиг
# ============================================================================

# В собранном exe (PyInstaller) __file__ указывает во временную папку —
# конфиг ищем рядом с самим exe.
FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("JARVIS_HOME") or (Path.home() / ".jarvis"))
NOTES_PATH = DATA_DIR / "notes.txt"
ERROR_LOG = DATA_DIR / "errors.log"
HISTORY_PATH = DATA_DIR / "history.jsonl"  # история запросов к Джарвису

YT_MUSIC_URL = "https://music.youtube.com"
YT_MUSIC_WINDOW_TITLE = "YouTube Music"

DEFAULT_CONFIG = {
    "language": "ru-RU",
    "wake_word": {"enabled": False, "word": "джарвис"},
    "voice": {"enabled": True, "engine": "piper", "piper_voice": "dmitri",
              "id": None, "rate": 175},
    "dictation": {"delay_sec": 3, "paste_delay": 0.6, "restore_clipboard": True},
    "shutdown_delay_sec": 15,
    "chrome": {"main_profile": "Default", "study_profile": None},
    "autostart_exe": "",  # путь к собранному Jarvis.exe: если задан и существует — автозапуск ведёт на него
    "ytmusic": {"app_id": "cinhimbnkkaeohfgghhklpknlkffjgod", "press_space_on_track": True},
    "phrases": {
        "pause": "огуречный салат",
        "resume": "банановые кокосы",
        "study_mode": "скоро урок",
        "play_mode": "время игр",
    },
    # Ручные пути, если автопоиск не справился:
    # chrome, steam, discord, telegram, genshin, minecraft, prism
    "paths": {},
    # Имя задачи планировщика (если Genshin нужно запускать от админа через schtasks)
    "genshin_task": None,
    "sites": {
        "браузер": "https://www.google.com",
        "гугл": "https://www.google.com",
        "google": "https://www.google.com",
        "ютуб": "https://www.youtube.com",
        "youtube": "https://www.youtube.com",
        "клод": "https://claude.ai",
        "claude": "https://claude.ai",
    },
    "urls": {
        "films": "https://rezka.ag/films/best/",
        "anime": "https://old.yummyani.me/",
        "github": "https://github.com",
        "parts": "https://ek.ua/ua/",
        "roblox": "https://www.roblox.com/home",
        "classroom": None,
        "logika": None,
    },
    # Steam-игры: фраза -> appid (число из URL store.steampowered.com/app/<appid>/)
    "games": {
        "кс2": 730, "cs2": 730, "кс 2": 730, "cs 2": 730,
        "ведьмак": 292030, "witcher": 292030,
        "киберпанк": 1091500, "cyberpunk": 1091500,
        "гта": 3240220, "gta": 3240220,
        "найн солс": 1809540, "nine sols": 1809540,
        "таунскейпер": 1291340, "townscaper": 1291340,
        "блэк дезерт": 582660, "black desert": 582660, "черная пустыня": 582660,
        "ассасин": 289650, "assassin": 289650,
        "неон вайт": 1533420, "neon white": 1533420,
        "резидент эвил вилладж": 1196590, "resident evil village": 1196590,
        "дайинг лайт": 3008130, "dying light": 3008130,
        "меча хамелеон": 4704690, "chameleon": 4704690,
        "синкинг сити": 750130, "sinking city": 750130,
        "вольюм": 4245250, "vholume": 4245250,
    },
    # Свои команды (редактируются в окне «открой настройки»):
    # [{"phrase": "блокнот", "target": "notepad.exe"}, {"phrase": "мой сайт", "target": "https://..."}]
    "commands": [],
    # Нейросеть: «Джарвис, какую игру мне поиграть?». Ключ и провайдера задают в окне настроек (вкладка «Нейросеть»).
    # provider: gemini | groq | openrouter | custom; пустые base_url/model берутся из пресета провайдера.
    "ai": {
        "enabled": False,
        "provider": "gemini",
        "api_key": "",
        "base_url": "",
        "model": "",
        "names": ["джарвис", "jarvis"],  # обращение; без слова-активатора нейросеть отвечает только на фразы с именем
        "city": "Днепр",                 # для вопросов про погоду
        "user_name": "сэр",              # как Джарвис обращается к пользователю голосом
        "style": "film",                 # характер ответов: film — как в кино, dry — сухо, brief — кратко
        "max_tokens": 400,
        "pc_context": True,              # рассказывать нейросети про железо и игры Steam
        "files": True,                   # доступ к файлам ПК: чтение, создание, редактирование
        "self_edit": True,               # нейросеть может редактировать файлы самого Джарвиса
        "chat": {"attention_sec": 25, "history_turns": 6},  # диалог: сколько секунд помнить обращение без имени
    },
    # История запросов к Джарвису: %USERPROFILE%\.jarvis\history.jsonl
    # (команды «история запросов» и «очисти историю»)
    "history": {"enabled": True, "max": 300},
}

# Эти разделы при загрузке ЗАМЕНЯЮТСЯ целиком (а не дополняются значениями по умолчанию) —
# иначе удалённую в настройках запись вернул бы дефолт.
REPLACE_KEYS = ("games", "sites", "commands")


def _norm(s: str) -> str:
    return s.lower().replace("ё", "е")


def _deep_merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _apply(cfg: dict, over: dict) -> None:
    for k, v in over.items():
        if k in REPLACE_KEYS:
            cfg[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(cfg.get(k), dict):
            _deep_merge(cfg[k], v)
        else:
            cfg[k] = v


def config_files() -> list:
    """Порядок важен: следующий файл перекрывает предыдущий.
    Рядом с программой -> ~/.jarvis/config.json (сюда пишет окно настроек) -> JARVIS_CONFIG."""
    files = [APP_DIR / "config.json", DATA_DIR / "config.json"]
    if os.environ.get("JARVIS_CONFIG"):
        files.append(Path(os.environ["JARVIS_CONFIG"]))
    return files


def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for p in config_files():
        if p.is_file():
            try:
                with open(p, encoding="utf-8") as f:
                    _apply(cfg, json.load(f))
                print(f"[config] загружен {p}")
            except Exception as e:
                print(f"[config] ошибка в {p}: {e} — файл пропущен")
    # старый формат: "apps": {"фраза": "команда"} -> commands
    legacy = cfg.pop("apps", None) or {}
    known = {_norm(str(c.get("phrase", ""))) for c in cfg["commands"]}
    for ph, target in legacy.items():
        if _norm(ph) not in known:
            cfg["commands"].append({"phrase": ph, "target": target})
    cfg["commands"] = [
        {"phrase": _norm(str(c["phrase"])), "target": str(c["target"]).strip()}
        for c in cfg["commands"] if c.get("phrase") and c.get("target")
    ]
    for section in ("sites", "games"):
        cfg[section] = {_norm(k): v for k, v in cfg[section].items()}
    cfg["phrases"] = {k: _norm(v) for k, v in cfg["phrases"].items()}
    cfg["wake_word"]["word"] = _norm(cfg["wake_word"]["word"])
    cfg["ai"]["names"] = [_norm(n) for n in cfg["ai"]["names"] if str(n).strip()]
    cfg["ai"]["user_name"] = str(cfg["ai"].get("user_name") or "сэр").strip()
    if cfg["ai"].get("style") not in ("film", "dry", "brief"):
        cfg["ai"]["style"] = "film"
    chat = cfg["ai"].get("chat") or {}
    try:
        attention = float(chat.get("attention_sec", 25))
    except (TypeError, ValueError):
        attention = 25.0
    try:
        turns = int(chat.get("history_turns", 6))
    except (TypeError, ValueError):
        turns = 6
    cfg["ai"]["chat"] = {"attention_sec": max(0.0, attention),
                         "history_turns": min(12, max(1, turns))}
    return cfg


CFG = load_config()


def user_config_path() -> Path:
    env = os.environ.get("JARVIS_CONFIG")
    return Path(env) if env else DATA_DIR / "config.json"


def reload_config() -> None:
    """Перечитать конфиг «на лету» (CFG меняется на месте — все ссылки остаются валидны)."""
    new = load_config()
    CFG.clear()
    CFG.update(new)
    for f in (find_chrome, discord_command, find_telegram, find_steam,
              find_genshin, find_minecraft, find_prism):
        f.cache_clear()
    STATE.voice_enabled = bool(CFG["voice"]["enabled"])


_MERGE_KEYS = ("voice", "wake_word", "chrome", "ai")


def save_user_config(patch: dict) -> None:
    """Записать изменения из окна настроек в ~/.jarvis/config.json и применить."""
    path = user_config_path()
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            shutil.copy2(path, path.with_suffix(".json.bak"))  # битый файл не теряем
            data = {}
    for k, v in patch.items():
        if k in _MERGE_KEYS and isinstance(data.get(k), dict):
            data[k].update(v)
        else:
            data[k] = v
    data.pop("apps", None)  # уехали в commands
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    reload_config()
    notify("Настройки сохранены.")


def log_error(context: str, exc: BaseException) -> None:
    """Пишет traceback в лог (полезно, когда нет консоли)."""
    print(f"[{context}] {exc}")
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {context}\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            f.write("\n")
    except Exception:
        pass


# ============================================================================
#  Автопоиск программ
# ============================================================================

def _env(name: str) -> str:
    return os.environ.get(name) or ""


def _join(base: str, *parts: str):
    return os.path.join(base, *parts) if base else None


def _first_file(paths):
    for p in paths:
        if p and os.path.isfile(p):
            return os.path.normpath(p)
    return None


def _reg(hive, key: str, value: str = ""):
    try:
        with winreg.OpenKey(hive, key) as k:
            return winreg.QueryValueEx(k, value)[0]
    except OSError:
        return None


def _drives():
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.isdir(f"{d}:\\")]


def _override(key: str):
    """Ручной путь из config.json -> paths.<key>, если файл существует."""
    p = CFG["paths"].get(key)
    if not p:
        return None
    p = os.path.expandvars(os.path.expanduser(p))
    if os.path.isfile(p):
        return p
    print(f"[config] paths.{key} = «{p}» не существует — ищу автоматически")
    return None


@lru_cache(None)
def find_chrome():
    ap = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
    return _override("chrome") or _first_file([
        _reg(winreg.HKEY_LOCAL_MACHINE, ap),
        _reg(winreg.HKEY_CURRENT_USER, ap),
        _join(_env("PROGRAMFILES"), "Google", "Chrome", "Application", "chrome.exe"),
        _join(_env("PROGRAMFILES(X86)"), "Google", "Chrome", "Application", "chrome.exe"),
        _join(_env("LOCALAPPDATA"), "Google", "Chrome", "Application", "chrome.exe"),
        shutil.which("chrome"),
    ])


def chrome_user_data():
    return _join(_env("LOCALAPPDATA"), "Google", "Chrome", "User Data")


def chrome_profile(kind: str) -> str:
    """kind: 'main' | 'study'. Если профиля нет на этом ПК — берём Default."""
    name = CFG["chrome"].get(f"{kind}_profile") or CFG["chrome"]["main_profile"]
    ud = chrome_user_data()
    if ud and os.path.isdir(ud) and not os.path.isdir(os.path.join(ud, name)):
        print(f"[chrome] профиль «{name}» не найден на этом ПК — использую Default")
        name = "Default"
    return name


@lru_cache(None)
def discord_command():
    ov = _override("discord")
    if ov:
        return [ov]
    root = _join(_env("LOCALAPPDATA"), "Discord")
    # Update.exe --processStart всегда запускает актуальную версию (app-X.Y.Z меняется)
    upd = _first_file([_join(root, "Update.exe")]) if root else None
    if upd:
        return [upd, "--processStart", "Discord.exe"]
    if root:
        exes = glob.glob(os.path.join(root, "app-*", "Discord.exe"))
        exes.sort(key=lambda p: [int(x) for x in re.findall(r"\d+", os.path.basename(os.path.dirname(p)))],
                  reverse=True)
        if exes:
            return [exes[0]]
    return None


@lru_cache(None)
def find_telegram():
    return _override("telegram") or _first_file([
        _join(_env("APPDATA"), "Telegram Desktop", "Telegram.exe"),
        _join(_env("LOCALAPPDATA"), "Telegram Desktop", "Telegram.exe"),
        _join(_env("PROGRAMFILES"), "Telegram Desktop", "Telegram.exe"),
        _join(_env("PROGRAMFILES(X86)"), "Telegram Desktop", "Telegram.exe"),
        shutil.which("Telegram"),
    ])


@lru_cache(None)
def find_steam():
    return _override("steam") or _first_file([
        _reg(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamExe"),
        _join(_reg(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath") or "", "steam.exe"),
        _join(_env("PROGRAMFILES(X86)"), "Steam", "steam.exe"),
        _join(_env("PROGRAMFILES"), "Steam", "steam.exe"),
    ])


@lru_cache(None)
def find_genshin():
    ov = _override("genshin")
    if ov:
        return ov
    tails = [
        r"Program Files\HoYoPlay\games\Genshin Impact game\GenshinImpact.exe",
        r"HoYoPlay\games\Genshin Impact game\GenshinImpact.exe",
        r"Epic Games\GenshinImpact\games\Genshin Impact game\GenshinImpact.exe",
        r"Genshin Impact\Genshin Impact game\GenshinImpact.exe",
        r"Program Files\Genshin Impact\Genshin Impact game\GenshinImpact.exe",
    ]
    return _first_file(d + t for d in _drives() for t in tails)


@lru_cache(None)
def find_minecraft():
    tails = [r"XboxGames\Minecraft Launcher\Content\Minecraft.exe"]
    return _override("minecraft") or _first_file(
        [_join(_env("PROGRAMFILES(X86)"), "Minecraft Launcher", "MinecraftLauncher.exe"),
         _join(_env("PROGRAMFILES"), "Minecraft Launcher", "MinecraftLauncher.exe"),
         shutil.which("MinecraftLauncher")]
        + [d + t for d in _drives() for t in tails])


@lru_cache(None)
def find_prism():
    return _override("prism") or _first_file(
        [_join(_env("LOCALAPPDATA"), "Programs", "PrismLauncher", "prismlauncher.exe"),
         _join(_env("PROGRAMFILES"), "PrismLauncher", "prismlauncher.exe"),
         shutil.which("prismlauncher")]
        + [d + r"PrismLauncher\prismlauncher.exe" for d in _drives()])


def find_ytmusic_shortcut():
    """Chrome кладёт ярлыки установленных PWA в меню «Пуск»."""
    ap = _env("APPDATA")
    if not ap:
        return None
    base = os.path.join(ap, "Microsoft", "Windows", "Start Menu", "Programs")
    for pat in (os.path.join(base, "Chrome Apps", "YouTube Music*.lnk"),
                os.path.join(base, "YouTube Music*.lnk")):
        hits = glob.glob(pat)
        if hits:
            return hits[0]
    return None


def pwa_installed(profile: str, app_id: str) -> bool:
    ud = chrome_user_data()
    return bool(ud) and os.path.isdir(os.path.join(ud, profile, "Web Applications", "Manifest Resources", app_id))


# ============================================================================
#  Запуск / закрытие процессов
# ============================================================================

def shell_open(target: str, params: str | None = None, cwd: str | None = None) -> bool:
    """ShellExecute: сам запросит UAC, если exe требует прав администратора."""
    r = ctypes.windll.shell32.ShellExecuteW(None, "open", target, params, cwd, 1)
    return r > 32


def popen(cmd, **kw):
    """Popen, безопасный для exe без консоли (все стандартные потоки -> DEVNULL)."""
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **kw)


def run_quiet(cmd: list[str]) -> int:
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW).returncode


def launch_app(path, name: str, cfg_key: str = "") -> None:
    if not path:
        hint = f" Укажи путь в config.json → paths.{cfg_key}." if cfg_key else ""
        notify(f"Не нашёл {name} на этом компьютере.{hint}", ok=False)
    elif shell_open(path, cwd=os.path.dirname(path)):
        notify(f"Запускаю {name}.")
    else:
        notify(f"Не удалось запустить {name}.", ok=False)


def close_app(process: str, display: str) -> None:
    rc = run_quiet(["taskkill", "/IM", process, "/F", "/T"])
    if rc == 0:
        notify(f"Закрываю {display}.")
    elif rc == 128:
        notify(f"{display} и так не запущен.", ok=False)
    else:
        notify(f"Не удалось закрыть {display} (код {rc}).", ok=False)


def open_url(url, label: str, study: bool = False) -> None:
    if not url:
        notify(f"Ссылка «{label}» не настроена — добавь её в config.json → urls.", ok=False)
        return
    chrome = find_chrome()
    if chrome:
        prof = chrome_profile("study" if study else "main")
        popen([chrome, f"--profile-directory={prof}", url])
    else:
        webbrowser.open(url)  # Chrome не найден — открываем в браузере по умолчанию
    notify(f"Открываю {label}.")


# ============================================================================
#  Уведомления и озвучка (по одному потоку на каждое — без гонок)
# ============================================================================

class Notifier:
    """Один поток с одним Tk — все всплывашки показываются из него."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def show(self, message: str, ok: bool = True, duration_ms: int = 2000) -> None:
        self.q.put(("popup", message, ok, duration_ms))

    def call(self, fn) -> None:
        """Выполнить fn(root) в Tk-потоке (так открывается окно настроек)."""
        self.q.put(("call", fn))

    def close(self) -> None:
        self.q.put(None)
        self.thread.join(timeout=6)

    def _run(self) -> None:
        try:
            root = (ctk.CTk if ctk else tk.Tk)()
            root.withdraw()
            k = max(1.0, root.winfo_fpixels("1i") / 96)  # масштаб экрана (CTk включает DPI-режим)
        except Exception as e:
            log_error("Tk", e)
            return
        active: list = []
        closing = {"flag": False}

        def layout():
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            y = sh - int(60 * k)
            for w in reversed(active):  # новейшее — снизу
                w.update_idletasks()
                y -= w.winfo_reqheight()
                w.geometry(f"+{sw - w.winfo_reqwidth() - int(20 * k)}+{y}")
                y -= int(8 * k)

        def remove(w):
            if w in active:
                active.remove(w)
                w.destroy()
                layout()

        def poll():
            try:
                while True:
                    item = self.q.get_nowait()
                    if item is None:
                        closing["flag"] = True
                        continue
                    if item[0] == "call":
                        try:
                            item[1](root)
                        except Exception as e:
                            log_error("Окно настроек", e)
                        continue
                    _, msg, ok, dur = item
                    bg = "#1f3d2b" if ok else "#3d1f1f"
                    w = tk.Toplevel(root)
                    w.overrideredirect(True)
                    w.attributes("-topmost", True)
                    w.configure(bg=bg)
                    tk.Label(w, text=msg, bg=bg, fg="#ffffff", font=("Segoe UI", 11),
                             padx=int(16 * k), pady=int(10 * k), wraplength=int(320 * k), justify="left").pack()
                    active.append(w)
                    layout()
                    w.after(dur, lambda w=w: remove(w))
            except queue.Empty:
                pass
            if closing["flag"] and not active:
                root.quit()
                return
            root.after(80, poll)

        root.after(80, poll)
        root.mainloop()
        try:
            root.destroy()
        except Exception:
            pass


def _pick_voice(engine):
    voices = engine.getProperty("voices") or []
    want = (CFG["voice"]["id"] or "").lower()
    if want:
        for v in voices:
            if want in (v.id or "").lower() or want in (v.name or "").lower():
                return v.id
        print(f"[voice] голос «{want}» не найден — подбираю автоматически (см. --list-voices)")
    lang = CFG["language"].lower()
    tokens = [lang, lang.replace("-", "_")]
    if lang.startswith("ru"):
        tokens += ["russian", "irina", "pavel"]
    for v in voices:
        blob = f"{v.id} {v.name} {getattr(v, 'languages', '')}".lower()
        if any(t in blob for t in tokens):
            return v.id
    return None  # системный голос по умолчанию


def _sapi_rate(wpm) -> int:
    """Слов в минуту (как в pyttsx3, 175 — обычный темп) -> шкала SAPI от -10 до 10."""
    try:
        return max(-10, min(10, round((int(wpm) - 175) / 25)))
    except (TypeError, ValueError):
        return 0


def sapi_voices():
    import win32com.client
    sp = win32com.client.Dispatch("SAPI.SpVoice")
    toks = sp.GetVoices()
    return sp, [toks.Item(i) for i in range(toks.Count)]


def _token_info(tok):
    desc = tok.GetDescription()
    try:
        langs = [x.strip().lower() for x in str(tok.GetAttribute("Language")).split(";")]
    except Exception:
        langs = []
    return desc, langs


def pick_sapi_voice(tokens):
    want = (CFG["voice"]["id"] or "").lower()
    if want:
        for t in tokens:
            if want in f"{t.Id} {t.GetDescription()}".lower():
                return t
        print(f"[voice] голос «{want}» не найден — подбираю автоматически (см. --list-voices)")
    lang = {"ru": "419", "uk": "422", "en": "409"}.get(CFG["language"][:2].lower(), "")
    for t in tokens:
        if lang and lang in _token_info(t)[1]:
            return t
    if CFG["language"].lower().startswith("ru"):
        for t in tokens:
            if any(n in _token_info(t)[0].lower() for n in ("irina", "pavel", "russian")):
                return t
    return None  # системный голос по умолчанию


def make_sapi():
    sp, tokens = sapi_voices()
    tok = pick_sapi_voice(tokens)
    if tok is not None:
        sp.Voice = tok
    sp.Rate = _sapi_rate(CFG["voice"]["rate"])
    sp.Volume = 100
    return sp


def _piper_rate_to_scale(wpm) -> float | None:
    """Темп pyttsx3 (слов/мин) -> length_scale Piper (1.0 — норма).

    Piper темп = длина фонем: больше значение — медленнее.
    Возвращает None при обычном темпе (175), чтобы не трогать модель.
    """
    try:
        wpm = int(wpm)
    except (TypeError, ValueError):
        return None
    if wpm <= 0 or abs(wpm - 175) < 5:
        return None
    return max(0.5, min(2.0, round(175 / wpm, 2)))


def _piper_available() -> bool:
    try:
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def _piper_say(text: str) -> None:
    import jarvis_voice_piper as p

    scale = _piper_rate_to_scale(CFG["voice"].get("rate", 175))
    p.speak_piper(text, voice=CFG["voice"].get("piper_voice", "dmitri"),
                  length_scale=scale)


def _sapi_name():
    try:
        _sp, tokens = sapi_voices()
    except Exception:
        return None
    tok = pick_sapi_voice(tokens)
    if tok is not None:
        return _token_info(tok)[0]
    return None


def current_voice_name():
    engine = (CFG["voice"].get("engine") or "piper").lower()
    if engine == "piper":
        import jarvis_voice_piper as p

        name = (CFG["voice"].get("piper_voice") or "dmitri").lower()
        if not _piper_available():
            return f"Piper «{name}» (нужен pip install piper-tts, пока SAPI)"
        if p.is_downloaded(name):
            return f"Piper «{name}» (живой нейроголос, офлайн)"
        return f"Piper «{name}» (скачается ~63 МБ при первой реплике)"
    try:
        _sp, tokens = sapi_voices()
    except Exception:
        return None
    tok = pick_sapi_voice(tokens)
    if tok is not None:
        return _token_info(tok)[0]
    return "русский голос не найден, будет системный (Параметры → Время и язык → Речь)"


class Speaker:
    """Очередь реплик + один воркер. busy выставляется сразу при постановке в очередь
    и снимается только когда очередь пуста — Джарвис не слышит сам себя.

    Основной голос — Piper (живой нейроголос, офлайн).
    Запасные: Windows SAPI напрямую (pywin32), затем pyttsx3."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.busy = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self.busy.set()
            self.q.put(text)

    def _speak_sapi(self, text: str, sapi_state: list) -> None:
        """Озвучка через SAPI. sapi_state=[sapi, sig] — кэш голоса между репликами."""
        cur = (CFG["voice"]["id"], CFG["voice"]["rate"])
        sapi, sig = sapi_state
        if sapi is None or cur != sig:  # голос или скорость поменяли в настройках
            sapi, sig = make_sapi(), cur
            sapi_state[:] = [sapi, sig]
        sapi.Speak(text, 0)  # 0 = дождаться конца фразы

    @staticmethod
    def _speak_pyttsx3(text: str) -> None:
        if pyttsx3 is None:
            raise RuntimeError("pyttsx3 не установлен")
        engine = pyttsx3.init()  # каждый раз новый движок: переиспользованный молчит
        vid = _pick_voice(engine)
        if vid:
            engine.setProperty("voice", vid)
        engine.setProperty("rate", CFG["voice"]["rate"])
        engine.say(text)
        engine.runAndWait()
        engine.stop()

    def _run(self) -> None:
        try:
            import pythoncom
            pythoncom.CoInitialize()  # COM нужно инициализировать в том потоке, где говорим
        except Exception as e:
            log_error("COM", e)
        sapi_state: list = [None, None]
        fails = 0
        while True:
            text = self.q.get()
            try:
                engine = (CFG["voice"].get("engine") or "piper").lower()
                if engine == "piper" and _piper_available():
                    try:
                        _piper_say(text)
                    except Exception as e:
                        log_error("Озвучка (Piper)", e)
                        self._speak_sapi(text, sapi_state)  # нет модели/интернета — SAPI
                else:
                    self._speak_sapi(text, sapi_state)
                fails = 0
            except Exception as e:
                log_error("Озвучка (SAPI)", e)
                sapi_state[:] = [None, None]
                fails += 1
                try:
                    self._speak_pyttsx3(text)
                except Exception as e2:
                    log_error("Озвучка (pyttsx3)", e2)
                    if fails == 3 and notifier:
                        notifier.show("Голос не работает. Подробности в errors.log", False, 5000)
            if self.q.empty():
                time.sleep(0.4)  # даём эху затихнуть
                if self.q.empty():
                    self.busy.clear()


class State:
    def __init__(self):
        self.listening = True
        self.playing = True  # игровой режим (False — учебный)
        self.voice_enabled = bool(CFG["voice"]["enabled"])
        self.stop = threading.Event()
        self.attention_until = 0.0  # до этого момента Джарвис «держит внимание» — имя можно не называть


STATE = State()
notifier: Notifier | None = None
speaker: Speaker | None = None


def speakable(message: str) -> str:
    """Текст для голоса: без полных путей и адресов — их неинтересно слушать."""
    text = re.sub(r"https?://\S+", "", message)
    text = re.sub(r"[A-Za-z]:[\\/]\S+|\\\\\S+", "", message)
    return re.sub(r"\s{2,}", " ", text).strip(" \n\t:-,.")


def notify(message: str, ok: bool = True, force_speak: bool = False) -> None:
    print((("[ok] " if ok else "[!!] ") + message))
    if notifier:
        notifier.show(message, ok, max(2000, min(15000, 60 * len(message))))  # длинные ответы показываем дольше
    if speaker and (STATE.voice_enabled or force_speak):
        speaker.say(speakable(message))


# ============================================================================
#  Автозапуск через Планировщик заданий и защита от двойного запуска
# ============================================================================

def _ps_q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


class Autostart:
    """Задача планировщика «JarvisAutostart»: запуск Джарвиса при входе в Windows.

    С правами администратора задача запускается без окна UAC — ради этого планировщик
    и используют. Создание такой задачи требует подтверждения UAC один раз, при сохранении."""

    TASK_NAME = "JarvisAutostart"

    @staticmethod
    def target() -> tuple[str, str, str]:
        """(программа, аргументы, рабочая папка)."""
        if FROZEN:
            return sys.executable, "", str(APP_DIR)
        py = Path(sys.executable)
        pyw = py.with_name("pythonw.exe")  # без чёрного окна консоли
        return str(pyw if pyw.is_file() else py), f'"{Path(__file__).resolve()}"', str(APP_DIR)

    def target_text(self) -> str:
        exe, args, _ = self.target()
        return f"{exe} {args}".strip()

    def same_target(self, command: str) -> bool:
        return os.path.normcase(command.strip().strip('"')) == os.path.normcase(self.target()[0])

    def status(self):
        """None — задачи нет; иначе {"admin": bool, "command": str}."""
        try:
            r = subprocess.run(["schtasks", "/query", "/tn", self.TASK_NAME, "/xml"],
                               stdin=subprocess.DEVNULL, capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        except Exception as e:  # noqa: BLE001
            log_error("schtasks /query", e)
            return None
        if r.returncode != 0:
            return None
        try:
            xml = r.stdout.decode("oem", "replace")
        except LookupError:
            xml = r.stdout.decode("utf-8", "replace")
        m = re.search(r"<Command>(.*?)</Command>", xml, re.S)
        cmd = (m.group(1) if m else "").replace("&amp;", "&").replace("&quot;", '"').strip()
        return {"admin": "HighestAvailable" in xml, "command": cmd}

    def _script(self, enabled: bool, admin: bool) -> str:
        if not enabled:
            return ("$ErrorActionPreference = 'Stop'\n"
                    f"Unregister-ScheduledTask -TaskName {_ps_q(self.TASK_NAME)} -Confirm:$false\n")
        exe, args, wd = self.target()
        user = "\\".join(x for x in (os.environ.get("USERDOMAIN"), os.environ.get("USERNAME")) if x)
        action = f"New-ScheduledTaskAction -Execute {_ps_q(exe)} -WorkingDirectory {_ps_q(wd)}"
        if args:
            action += f" -Argument {_ps_q(args)}"
        return (
            "$ErrorActionPreference = 'Stop'\n"
            f"$a = {action}\n"
            f"$t = New-ScheduledTaskTrigger -AtLogOn -User {_ps_q(user)}\n"
            "$t.Delay = 'PT10S'\n"  # даём системе 10 секунд: звук и микрофон успевают подняться
            "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
            "-ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -MultipleInstances IgnoreNew\n"
            f"$p = New-ScheduledTaskPrincipal -UserId {_ps_q(user)} -LogonType Interactive "
            f"-RunLevel {'Highest' if admin else 'Limited'}\n"
            f"Register-ScheduledTask -TaskName {_ps_q(self.TASK_NAME)} -Action $a -Trigger $t "
            "-Settings $s -Principal $p -Force | Out-Null\n")

    def _matches(self, enabled: bool, admin: bool) -> bool:
        st = self.status()
        return st is None if not enabled else bool(st and st["admin"] == admin)

    def apply(self, enabled: bool, admin: bool = False):
        """Создать / обновить / удалить задачу. Возвращает (успех, сообщение)."""
        if not enabled and self.status() is None:
            return True, "Автозапуск выключен."
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ps1 = DATA_DIR / "autostart.ps1"
        ps1.write_text(self._script(enabled, admin), encoding="utf-8-sig")  # BOM: PowerShell 5 читает кириллицу
        ok = False
        if not (enabled and admin):  # обычную задачу обычно можно создать и без UAC
            try:
                r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
                                   stdin=subprocess.DEVNULL, capture_output=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=60)
                ok = r.returncode == 0 and self._matches(enabled, admin)
            except Exception as e:  # noqa: BLE001
                log_error("Автозапуск (без UAC)", e)
        if not ok:  # нужны права администратора — просим UAC
            params = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{ps1}"'
            if ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", params, None, 0) <= 32:
                return False, "запрос прав администратора отклонён."
            for _ in range(60):  # ждём до 30 с, пока пользователь ответит на UAC
                time.sleep(0.5)
                if self._matches(enabled, admin):
                    ok = True
                    break
        if not ok:
            return False, "задачу создать не удалось (подробности — в Планировщике заданий)."
        if not enabled:
            return True, "Автозапуск выключен."
        return True, "Джарвис запустится при входе в Windows" + (" с правами администратора." if admin else ".")


AUTOSTART = Autostart()


def single_instance() -> bool:
    """False, если Джарвис уже запущен (например, и вручную, и из планировщика)."""
    global _instance_mutex
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, "Local\\JarvisVoiceAssistant")
    err = ctypes.get_last_error()
    _instance_mutex = handle  # держим до конца процесса
    return err not in (183, 5)  # ALREADY_EXISTS / ACCESS_DENIED (первый экземпляр был от админа)


_instance_mutex = None


# ============================================================================
#  Окна и музыка
# ============================================================================

def _find_windows(substring: str) -> list:
    sub = substring.lower()
    found: list = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and sub in win32gui.GetWindowText(hwnd).lower():
            found.append(hwnd)
        return True

    win32gui.EnumWindows(cb, None)
    return found


def _wait_for_window(substring: str, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        hits = _find_windows(substring)
        if hits:
            return hits[0]
        time.sleep(0.5)
    return None


def _focus_window(hwnd) -> bool:
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        pyautogui.press("alt")  # Windows разрешает смену фокуса после «недавнего ввода»
        win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        print(f"[music] SetForegroundWindow: {e}")
    time.sleep(0.3)
    return win32gui.GetForegroundWindow() == hwnd


def _resume_last_track() -> None:
    hwnd = _wait_for_window(YT_MUSIC_WINDOW_TITLE)
    if not hwnd:
        print("[music] окно YouTube Music не появилось за 10 секунд")
        return
    if _focus_window(hwnd):
        pyautogui.press("space")
    else:
        print("[music] фокус не получен — шлю глобальную медиаклавишу play/pause")
        pyautogui.press("playpause")


def open_music() -> None:
    lnk = find_ytmusic_shortcut()
    if lnk:
        shell_open(lnk)
    else:
        chrome = find_chrome()
        if not chrome:
            webbrowser.open(YT_MUSIC_URL)
        else:
            prof = chrome_profile("main")
            app_id = CFG["ytmusic"]["app_id"]
            proxy = os.path.join(os.path.dirname(chrome), "chrome_proxy.exe")
            if app_id and os.path.isfile(proxy) and pwa_installed(prof, app_id):
                popen([proxy, f"--profile-directory={prof}", f"--app-id={app_id}"])
            else:
                popen([chrome, f"--profile-directory={prof}", f"--app={YT_MUSIC_URL}"])
    notify("Открываю YouTube Music.")


_ytmusic_client = None


def _get_ytmusic():
    global _ytmusic_client
    if YTMusic is None:
        return None
    if _ytmusic_client is None:
        try:
            _ytmusic_client = YTMusic()
        except Exception as e:
            log_error("Инициализация YTMusic()", e)
    return _ytmusic_client


def _find_video_id(query: str):
    yt = _get_ytmusic()
    if yt is None:
        return None
    try:
        results = yt.search(query, filter="songs", limit=5) or yt.search(query, filter="videos", limit=5)
        return results[0]["videoId"] if results else None
    except Exception as e:
        log_error("Поиск трека", e)
        return None


def play_track(query: str) -> None:
    def worker():
        if YTMusic is None:
            notify("Поиск треков недоступен: установи ytmusicapi (pip install ytmusicapi).", ok=False)
            return
        notify(f"Ищу трек «{query}»…")
        vid = _find_video_id(query)
        if not vid:
            notify(f"Не нашёл трек «{query}».", ok=False)
            return
        url = f"{YT_MUSIC_URL}/watch?v={vid}"
        chrome = find_chrome()
        if chrome:
            popen([chrome, f"--profile-directory={chrome_profile('main')}", f"--app={url}"])
        else:
            webbrowser.open(url)
        notify(f"Включаю «{query}».")
        if CFG["ytmusic"]["press_space_on_track"] and chrome:
            threading.Thread(target=_resume_last_track, daemon=True).start()

    threading.Thread(target=worker, daemon=True).start()


def close_music_windows() -> None:
    windows = _find_windows(YT_MUSIC_WINDOW_TITLE)
    if not windows:
        notify("Окна YouTube Music не найдены.", ok=False)
        return
    closed = 0
    for hwnd in windows:  # WM_CLOSE, а не taskkill — обычные окна Chrome не трогаем
        try:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            closed += 1
        except Exception as e:
            print(f"[music] не закрылось окно {hwnd}: {e}")
    notify(f"Закрываю окон музыки: {closed}." if closed else "Не удалось закрыть окна YouTube Music.",
           ok=bool(closed))


# ============================================================================
#  Команды
# ============================================================================

def has(text: str, *stems: str) -> bool:
    """Слово начинается с основы (стим -> «стим», «стима»; но не «ойстим»)."""
    return any(re.search(r"\b" + re.escape(s), text) for s in stems)


def is_word(text: str, *words: str) -> bool:
    """Слово целиком («выход», но не «выходной»)."""
    return any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in words)


def is_help(t: str) -> bool:
    return "что ты умеешь" in t or "список команд" in t or t.strip() == "помощь"


def is_pc(text: str) -> bool:
    return is_word(text, "пк", "комп", "компьютер", "компьютера", "ноутбук")


# Разделители цепочки команд: «открой стим и заметки», «запусти майнкрафт, потом музыку»
CHAIN_SPLIT_RE = re.compile(r"\s*(?:,|\bи\b|\bа\s+также\b|\bпотом\b|\bзатем\b|\bпосле\s+этого\b|\s*\+\s*)\s*")


def split_chain(text: str) -> list:
    """Фразу «открой стим и заметки» -> [«открой стим», «заметки»].
    Пустые куски выбрасываем. Делим осторожно: «создай …» / «удали …» / «надиктуй …»
    с « и » внутри не трогаем, чтобы не развалить «создай папку моды и в ней файл список»."""
    stripped = text.strip()
    if parse_create(stripped) is not None:
        return [stripped]
    if re.search(r"\b(?:удали|удалить|убери|сотри|стереть)\b", stripped):
        return [stripped]
    if re.search(r"\b(?:надиктуй|диктуй|диктовка|напечатай|набери|вставь)\b", stripped):
        return [stripped]
    parts = [p.strip(" ,.!?-—") for p in CHAIN_SPLIT_RE.split(stripped)]
    return [p for p in parts if p]


TRACK_RE = re.compile(r"\b(?:включи|поставь|найди)\s+(?:трек|песню|песня)\s+(.+)")
# «загугли X», «найди X», «найди в интернете X» (но «найди трек X» — это музыка, см. TRACK_RE)
SEARCH_RE = re.compile(
    r"\b(?:загугл\w*|погугл\w*|найди(?:те)?)\b\s*(?:в\s+(?:интернете|гугле|google|сети)\s+)?(.*)")
Cmd = namedtuple("Cmd", "match run play_only")


def commands_text() -> str:
    return f"""Список команд Джарвиса:
— выход — завершить программу
— музыка — открыть YouTube Music; закрой музыку — закрыть все окна YouTube Music
— песня — нажать play/pause в YouTube Music
— включи/поставь/найди трек <название> — найти и включить трек
— загугли <запрос> / найди <запрос> — поиск в Google (в Chrome)
— «Джарвис, <вопрос>» — ответ нейросети голосом (нужен ключ: настройки → Нейросеть);
  нейросеть умеет читать, создавать и редактировать файлы на ПК и саму себя
— говорить можно подряд: после обращения Джарвис держит внимание 25 с (настройки → Нейросеть);
  помнит последние реплики («это норма?» понимает по прошлому ответу);
  несколько команд сразу: «открой стим и заметки», «запусти майнкрафт, потом музыку»;
  «забудь разговор» / «новый разговор» — начать заново
— история запросов — последние запросы к Джарвису; очисти историю — удалить их ({HISTORY_PATH})
— геншин; майнкрафт; призм; роблокс — запуск игр и лаунчеров
— игры Steam: {", ".join(sorted(CFG["games"]))}
— стим / дискорд / телеграм (+ «закрой …») — запуск и закрытие
— учёба — Chrome с учебным профилем; пара / урок / занятие — Google Classroom
— логика — backoffice Logika; фильм / кино; аниме; гитхаб; комплектующие
— закрой браузер — закрыть все окна Chrome
— открой <сайт> — сайт из списка: {", ".join(sorted(CFG["sites"]))}
— запиши <текст> / заметка <текст> — сохранить заметку; открой заметки — показать; очисти заметки — удалить все ({NOTES_PATH})
— создай файл <имя> / создай папку <имя> / создай папку <имя> и в ней файл <имя> — по умолчанию на рабочем столе
— удали файл <имя> / удали папку <имя> — удаление (в корзину, можно восстановить)
— удали команду <фраза> / удали игру <фраза> / удали сайт <фраза> — убрать свою команду
— надиктуй <текст точка запятая вопрос> — умная диктовка: чистит речь, ставит знаки,
  вставляет в активное окно (скажи «точка», «запятая», «новая строка» голосом)
— напомни <что> через 10 минут / в 20:00 / каждый день в 9:00 — голосовое напоминание;
  напоминания — показать список, очисти напоминания — удалить все
— «Джарвис, какая температура процессора?» — датчики ПК; «это норма?» — оценка по предыдущему ответу
— «Джарвис, где файлы из колледжа» — поиск по всему ПК; «открой папку с фотографиями» — откроется Проводник
— «Джарвис, установи wukong» — установка игры из Steam; после этого «запусти вуконг» работает голосом
— «напечатай …» — набор текста в активном окне
— выключи / перезагрузи пк — через {CFG["shutdown_delay_sec"]} с; «отмена» — отменить
— голос — вкл/выкл голосовые ответы
— открой настройки — окно настроек (свои команды, игры, ссылки, пути, автозапуск)
— «{CFG["phrases"]["study_mode"]}» / «{CFG["phrases"]["play_mode"]}» — учебный / игровой режим
— «{CFG["phrases"]["pause"]}» — пауза, «{CFG["phrases"]["resume"]}» — продолжить

Мои команды:
{chr(10).join("— " + c["phrase"] + " → " + c["target"] for c in CFG["commands"]) or "— пока нет (добавь в настройках)"}"""


def hard_exit(delay: float = 12.0) -> None:
    """Страховка: если что-то (микрофон, озвучка, окно) зависло при выходе — убиваем процесс."""
    timer = threading.Timer(delay, lambda: os._exit(0))
    timer.daemon = True
    timer.start()


def cmd_exit(t):
    notify("Выход из программы.")
    STATE.stop.set()
    hard_exit()


def cmd_shutdown(t):
    d = CFG["shutdown_delay_sec"]
    if run_quiet(["shutdown", "/s", "/t", str(d)]) == 0:
        notify(f"Выключаю компьютер через {d} секунд. Скажи «отмена», чтобы остановить.")
    else:
        notify("Не удалось запустить выключение.", ok=False)


def cmd_restart(t):
    d = CFG["shutdown_delay_sec"]
    if run_quiet(["shutdown", "/r", "/t", str(d)]) == 0:
        notify(f"Перезагружаю компьютер через {d} секунд. Скажи «отмена», чтобы остановить.")
    else:
        notify("Не удалось запустить перезагрузку.", ok=False)


def cmd_cancel_shutdown(t):
    if run_quiet(["shutdown", "/a"]) == 0:
        notify("Отменил выключение.")
    else:
        notify("Нечего отменять.", ok=False)


def cmd_notes(t):
    """«открой/покажи заметки», «очисти/удали заметки»."""
    if has(t, "очист", "удали", "удалит", "сотр", "стереть", "стер", "сброс", "удалить"):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if NOTES_PATH.exists():
                NOTES_PATH.unlink()
        except OSError as e:
            notify(f"Не смог очистить заметки: {e}", ok=False)
            return
        notify("Все заметки удалены.")
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not NOTES_PATH.exists():
            NOTES_PATH.write_text("", encoding="utf-8")
        os.startfile(str(NOTES_PATH))
    except OSError as e:
        notify(f"Не смог открыть заметки: {e}", ok=False)
        return
    notify("Открыл заметки.")


def cmd_note(t):
    m = re.search(r"\b(?:запиш\w*|заметк\w*)\s*(.*)", t)
    note = (m.group(1) if m else "").strip()
    if not note:
        notify("Не расслышал, что записать.", ok=False)
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(NOTES_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M}] {note}\n")
    notify(f"Записал: {note}")


# ----- знакомые папки и создание файлов/папок -------------------------------

@lru_cache(None)
def user_folders() -> dict:
    """«рабочий стол» -> реальный путь. Берём из реестра (учитывает OneDrive и перенос папок)."""
    key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    want = {"рабочий стол": "Desktop", "документы": "Personal", "изображения": "My Pictures",
            "музыка": "My Music", "видео": "My Video",
            "загрузки": "{374DE290-123F-4565-9164-39C4925E467B}"}
    out: dict = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            for ru, val in want.items():
                raw, _ = winreg.QueryValueEx(k, val)
                out[ru] = str(Path(os.path.expandvars(str(raw))))
    except OSError:
        pass
    for ru, sub in (("рабочий стол", "Desktop"), ("документы", "Documents"), ("загрузки", "Downloads"),
                    ("изображения", "Pictures"), ("музыка", "Music"), ("видео", "Videos")):
        out.setdefault(ru, str(Path.home() / sub))
    return out


_FOLDER_STEMS = (("стол", "рабочий стол"), ("загруз", "загрузки"), ("документ", "документы"),
                 ("фото", "изображения"), ("изображен", "изображения"), ("картин", "изображения"),
                 ("музык", "музыка"), ("видео", "видео"))


def _create_dest(t: str) -> Path:
    """Куда создавать: место из фразы («на рабочем столе», «в загрузках»), иначе рабочий стол."""
    folders = user_folders()
    for stem, key in _FOLDER_STEMS:
        if stem in t:
            return Path(folders.get(key) or (Path.home() / "Desktop"))
    return Path(folders.get("рабочий стол") or (Path.home() / "Desktop"))


def parse_create(t: str):
    """«создай файл отчёт», «создай папку игры», «создай папку моды и вней файл список»
    -> (список папок, файл|None, путь назначения) или None, если фраза не про создание."""
    if not re.search(r"\b(?:файл|папк\w*|директори\w*|каталог\w*)", t):
        return None
    if not (re.search(r"\b(?:созда\w+|сдела\w+|заведи|нов\w*)\b", t)):
        return None
    stop = r"(?=\s+(?:и|в|на|внутри|для|пожалуйста|с\s+текстом|там)\b|$|[.,!?])"
    m_dir = re.search(r"\b(?:папку|папка|папке|папки|директорию|каталог)\s+(?:с\s+именем\s+)?(.+?)"
                      + stop, t)
    m_file = re.search(r"\bфайл\w*\s+(?:с\s+именем\s+|под\s+названием\s+)?(.+?)" + stop, t)
    if not m_dir and not m_file:
        return None
    dirs = [m_dir.group(1).strip().strip("\"'«»") ] if m_dir else []
    fname = m_file.group(1).strip().strip("\"'«»") if m_file else None
    # имя файла из мусора речи («файл список для меня») и расширение по умолчанию
    if fname:
        fname = re.sub(r"\b(пожалуйста|для меня|у меня|новый|новая)\b", "", fname).strip()
        if fname and "." not in fname:
            fname += ".txt"
        if not fname:
            fname = None
    dirs = [c for d in dirs for c in [re.sub(r"\b(пожалуйста|для меня|с именем)\b", "", d).strip()] if c]

    def _is_place(s: str) -> bool:
        # «в загрузках», «на рабочем столе» — это место, а не имя
        return bool(s) and bool(re.match(r"^(?:в|на)\s", s)) and any(st in s for st, _ in _FOLDER_STEMS)

    if dirs and _is_place(dirs[0]):
        dirs = []
    if fname and _is_place(fname):
        fname = None
    if not dirs and not fname:
        return None
    return dirs, fname, _create_dest(t)


# ----- открытие файлов и папок ----------------------------------------------

_OPEN_ITEM = re.compile(r"\b(?:файл\w*|папк\w*|документ\w*|директори\w*|каталог\w*|изображени\w*|"
                        r"картин\w*|фото|текст\w*)\b")
_OPEN_PATH = re.compile(r"(?:[a-zA-Z]:[\\/]|~[\\/]|\\\\)[\w .\\/-]+")


def wants_open_item(t: str) -> bool:
    """«открой файл отчёт», «открой папку с фото» — это файл, а не сайт из списка."""
    if not re.search(r"\bоткр\w+", t):
        return False
    return bool(_OPEN_ITEM.search(t) or _OPEN_PATH.search(t))


def cmd_open(t):
    m = _OPEN_PATH.search(t)
    if m:
        p = Path(os.path.expandvars(os.path.expanduser(m.group(0).strip().strip("\"'"))))
        if p.exists():
            try:
                os.startfile(str(p))
                notify(f"Открыл: {p}")
                return
            except OSError as e:
                log_error("Открытие файла", e)
    if ai_ready():
        ask_ai(ai_question(t) or t)  # нейросеть найдёт по имени (find_any) и откроет (open_path)
    else:
        notify("Не понял, какой файл открыть. Назови точный путь либо включи нейросеть в настройках, "
               "вкладка «Нейросеть» — она найдёт файл сама.", ok=False)


def _resolve_delete_target(t: str):
    """Имя файла/папки из фразы удаления -> (имя, папка-поиска)."""
    m = re.search(r"\b(?:файл\w*|папк\w*|документ\w*|директори\w*|каталог\w*)\s+"
                  r"(?:с\s+именем\s+|под\s+названием\s+)?(.+?)(?=$|[.,!?])", t)
    name = (m.group(1) if m else "").strip().strip("\"'«»")
    name = re.sub(r"\b(пожалуйста|навсегда|окончательно)\b", "", name).strip()
    if not name:
        return None, None
    return name, _create_dest(t)


def _norm_name(s: str) -> str:
    """Имя для нечёткого сравнения: нижний регистр, без расширения, ё->е, _ и - -> пробел."""
    s = (s or "").strip().lower().replace("ё", "е")
    s = re.sub(r"\.[a-z0-9]{1,5}$", "", s)  # расширение
    s = re.sub(r"[_\-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _find_delete_candidates(name: str, dest: Path, want_dir: bool) -> list:
    """Кандидаты на удаление: точное имя, затем нечёткий поиск рядом.

    Понимает «new file» -> «new_file.txt», игнорирует расширение.
    Ищем только в папке-поиска и в стандартных папках (рабочий стол, документы,
    загрузки) — полный обход всего ПК тут не нужен и может висеть минутами.
    """
    want = _norm_name(name)
    exact = dest / name
    if exact.exists():
        if want_dir and not exact.is_dir():
            pass  # просили папку, а нашёлся файл — ищем дальше
        else:
            return [exact]
    cands = []
    roots = [dest, *(Path(p) for p in user_folders().values())]
    seen = set()
    for root in roots:
        try:
            root = Path(root)
            if not root.is_dir():
                continue
            for p in root.iterdir():
                if str(p) in seen:
                    continue
                if want_dir and not p.is_dir():
                    continue
                norm = _norm_name(p.name)
                if want == norm or want in norm or norm in want:
                    seen.add(str(p))
                    cands.append(p)
                    if len(cands) >= 5:
                        return cands
            # точное совпадение с точками/подчёркиваниями: new file -> new_file*
            for p in root.glob(f"*{name}*"):
                if str(p) in seen:
                    continue
                seen.add(str(p))
                if want_dir and not p.is_dir():
                    continue
                cands.append(p)
                if len(cands) >= 5:
                    return cands
        except OSError:
            continue
    return cands


def _trash_path(p: Path) -> tuple[bool, str]:
    """Удалить файл/папку в корзину Windows. Возвращает (получилось, пояснение).

    Основной путь — COM Shell.Application (именно он кладёт в корзину).
    Путь упаковываем в base64, чтобы любые символы в имени/директории (вкл. кириллицу,
    амперсанд, скобки, доллар и пр.) точно дойшли до PowerShell без искажений.
    Запасной путь — прямое удаление (мимо корзины, но надёжно).
    """
    import base64
    ps = (
        "$s=New-Object -ComObject Shell.Application;"
        "$f=$s.NameSpace('" + str(p.parent) + "');"
        "$i=$f.ParseName('" + p.name + "');"
        "if ($i) { $i.InvokeVerb('delete') } else { exit 2 }"
    )
    # UTF-16LE -> base64: не зависит от экранирования в -Command
    ps_b64 = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    proc = None
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", ps_b64],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        r = proc.returncode
    except (OSError, subprocess.SubprocessError):
        r = -1
    # Дебаг-лог в консоль (не всплывает для пользователя)
    try:
        if proc is not None and proc.stderr:
            _log = proc.stderr.decode("utf-8", "replace").strip()
            if _log:
                log_error("Удаление (COM stderr)", _log)
    except Exception:
        pass
    time.sleep(0.8)
    if not p.exists():
        return True, "в корзину"
    if r != 0:
        # COM не сработал (OneDrive/нет Проводника/путь не в namespace) — удаляем напрямую
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError as e:
            return False, str(e)
        return (not p.exists(), "напрямую (мимо корзины)" if not p.exists() else "сбой в системе")
    return False, "сбой в системе (файл на месте)"


def cmd_delete(t):
    """«удали файл отчёт» / «удали папку моды» — в корзину (через PowerShell, можно восстановить)."""
    name, dest = _resolve_delete_target(t)
    if not name:
        notify("Что удалить? Скажи: «удали файл …» или «удали папку …».", ok=False)
        return
    is_dir_word = bool(re.search(r"\b(?:папк\w*|директори\w*|каталог\w*)\b", t))
    cands = _find_delete_candidates(name, dest, is_dir_word)
    if not cands:
        # точный путь из фразы («удали файл c:\…\отчёт.txt»)?
        m = _OPEN_PATH.search(t)
        if m:
            p = Path(os.path.expandvars(os.path.expanduser(m.group(0).strip().strip("\"'"))))
            if p.exists():
                cands = [p]
    if not cands:
        notify(f"Не нашёл «{name}» — нечего удалять.", ok=False)
        return
    if len(cands) > 1:
        notify(f"Нашёл несколько «{name}» — уточни место, например «в загрузках». "
               f"Первый вариант: {cands[0]}", ok=False)
        return
    p = cands[0]
    try:
        ok, how = _trash_path(p)
    except OSError as e:
        log_error("Удаление файла", e)
        notify(f"Не удалось удалить «{name}».", ok=False)
        return
    if ok:
        notify(f"Удалил ({how}): {p.name} ({p.parent}).")
    else:
        log_error("Удаление файла", RuntimeError(f"{p}: {how}"))
        notify(f"Удалить файл не получилось: {how}.", ok=False)


def cmd_delete_command(t):
    """«удали команду блокнот» / «забудь команду …» — убрать свою команду из настроек."""
    rest = re.sub(r"\b(?:удали|удалить|убери|забудь|сотри|стереть)\b", "", t)
    rest = re.sub(r"\b(?:команду|команда|команды|фразу|приложение|игру|сайт)\b", "", rest)
    rest = re.sub(r"\b(?:пожалуйста|навсегда)\b", "", rest).strip(" ,.!?-—")
    if not rest:
        notify("Какую команду удалить? Скажи: «удали команду …».", ok=False)
        return
    key = _norm(rest)
    cmds = list(CFG["commands"])
    hit = next((c for c in cmds if c["phrase"] == key or key in c["phrase"]
                or c["phrase"] in key), None)
    if hit:
        cmds = [c for c in cmds if c["phrase"] != hit["phrase"]]
        save_user_config({"commands": cmds})
        notify(f"Удалил команду «{hit['phrase']}».")
        return
    games = dict(CFG["games"])
    ghit = next((k for k in games if k == key or key in k or k in key), None)
    if ghit:
        del games[ghit]
        save_user_config({"games": games})
        notify(f"Удалил игру «{ghit}».")
        return
    sites = dict(CFG["sites"])
    shit = next((k for k in sites if k == key or key in k or k in key), None)
    if shit:
        del sites[shit]
        save_user_config({"sites": sites})
        notify(f"Удалил сайт «{shit}».")
        return
    notify(f"Не нашёл команду «{rest}». Свои команды: "
           + (", ".join(c["phrase"] for c in cmds) or "пока нет"), ok=False)


def cmd_dictate(t):
    """«надиктуй …» / «напечатай …» — почистить речь и вставить в активное окно.

    Задержки из config.json -> dictation: delay_sec (дать кликнуть в окно),
    paste_delay (пауза перед Ctrl+V — медленным окнам нужно больше),
    restore_clipboard (вернуть старый буфер после вставки).
    """
    m = re.search(r"\b(?:надиктуй|диктуй|диктовка|напечатай|набери|вставь)\b\s*(.*)", t)
    raw = (m.group(1) if m else "").strip()
    if not raw:
        notify("Что напечатать? Скажи: «надиктуй привет точка как дела вопрос».", ok=False)
        return
    try:
        import jarvis_dictation as d
    except ImportError as e:
        notify(f"Модуль диктовки не найден: {e}", ok=False)
        return
    text = d.cleanup(raw)
    if not text:
        notify("Не расслышал текст для диктовки.", ok=False)
        return
    dc = CFG.get("dictation", {}) or {}
    try:
        delay = max(0.0, float(dc.get("delay_sec", 3)))
    except (TypeError, ValueError):
        delay = 3.0
    try:
        paste_delay = max(0.1, float(dc.get("paste_delay", 0.6)))
    except (TypeError, ValueError):
        paste_delay = 0.6
    restore = bool(dc.get("restore_clipboard", True))
    if delay > 0:
        notify(f"Вставляю «{text}» через {delay:g} с — кликни куда нужно…")
        time.sleep(delay)
    try:
        d.type_into_active_window(text, paste_delay=paste_delay,
                                  restore_clipboard=restore)
        notify(f"Вставил: {text}")
    except Exception as e:
        log_error("Диктовка", e)
        notify("Не удалось вставить текст.", ok=False)


def cmd_create(t):
    plan = parse_create(t)
    if not plan:
        return
    dirs, fname, dest = plan
    what, made = [], []
    base = dest
    for d in dirs:
        p = base / d
        try:
            p.mkdir(parents=True, exist_ok=True)
            made.append(str(p))
            what.append(f"папку «{d}»")
            base = p  # «и в ней файл» — файл кладём внутрь созданной папки
        except OSError as e:
            log_error("Создание папки", e)
            notify(f"Не удалось создать папку «{d}».", ok=False)
            return
    if fname:
        p = base / fname
        if p.exists():
            notify(f"Файл «{fname}» уже есть: {p}", ok=False)
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("", encoding="utf-8")
            made.append(str(p))
            what.append(f"файл «{fname}»")
        except OSError as e:
            log_error("Создание файла", e)
            notify(f"Не удалось создать файл «{fname}».", ok=False)
            return
    place = next((f"{k}" for stem, k in _FOLDER_STEMS if stem in t), "рабочий стол")
    place_txt = {"рабочий стол": "на рабочем столе", "загрузки": "в загрузках", "документы": "в документах",
                 "изображения": "в изображениях", "музыка": "в музыке", "видео": "в видео"}.get(place, f"в папке {place}")
    notify(f"Создал {' и '.join(what)} {place_txt}. {' '.join(made)}")


# ----- история запросов --------------------------------------------------------

def history_add(kind: str, question: str, answer: str, tools=None) -> None:
    """Одна строка истории в JSONL-журнале запросов (~/.jarvis/history.jsonl)."""
    if not CFG.get("history", {}).get("enabled", True):
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        rec = {"time": f"{datetime.now():%Y-%m-%d %H:%M:%S}", "type": kind,
               "question": str(question), "answer": str(answer)}
        if tools:
            rec["tools"] = list(tools)
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _history_trim()
    except Exception as e:  # история не должна ломать основную задачу
        log_error("История запросов", e)


def _history_trim() -> None:
    """Не даём истории расти бесконечно."""
    limit = int(CFG.get("history", {}).get("max") or 300)
    try:
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
        if len(lines) > limit:
            HISTORY_PATH.write_text("\n".join(lines[-limit:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def history_lines(limit: int = 20) -> list:
    """Последние записи истории (старые — в начале списка)."""
    try:
        rows = [json.loads(s) for s in HISTORY_PATH.read_text(encoding="utf-8").splitlines() if s.strip()]
    except (OSError, ValueError):
        return []
    return rows[-limit:]


def history_text(limit: int = 20) -> str:
    rows = history_lines(limit)
    if not rows:
        return "История запросов пуста."
    out = []
    for r in reversed(rows):  # новые сверху
        line = f"{r.get('time', '')}  [{r.get('type', '')}] {r.get('question', '')}\n    → {r.get('answer', '')}"
        if r.get("tools"):
            line += f"\n    (файлы: {', '.join(r['tools'])})"
        out.append(line)
    return f"Последние запросы к Джарвису (новые сверху, всего в файле: {HISTORY_PATH}):\n\n" + "\n\n".join(out)


def cmd_history(t):
    if is_word(t, "очисти", "очистить", "удали", "удалить", "сбрось"):
        try:
            HISTORY_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        notify("История запросов очищена.")
        return
    if not history_lines(1):
        notify("История запросов пока пуста.")
        return
    text = history_text(20)
    # всегда пишем читаемый файл и открываем его: так история видна и без консоли,
    # и когда Джарвис запущен из терминала
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "history.txt"
    try:
        path.write_text(text, encoding="utf-8")
        os.startfile(str(path))  # откроется в Блокноте (или ассоциированной программе)
        notify(f"История запросов открыта: {path}")
    except OSError as e:
        log_error("Открытие истории", e)
        print(text)  # файл открыть не удалось — хотя бы в консоль
        notify(f"Не удалось открыть файл, история выведена в консоль. Файл: {path}", ok=False)


# ----- напоминания ------------------------------------------------------------

REMINDERS_PATH = DATA_DIR / "reminders.json"


def reminders_load() -> list:
    try:
        rows = json.loads(REMINDERS_PATH.read_text(encoding="utf-8"))
        return rows if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def reminders_save(rows: list) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = REMINDERS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, REMINDERS_PATH)
    except OSError as e:
        log_error("Напоминания", e)


def reminder_add(text: str, at: str, daily: bool = False) -> dict:
    """at: «ГГГГ-ММ-ДД ЧЧ:ММ» (разовое) или «ЧЧ:ММ» (ежедневное)."""
    rows = reminders_load()
    row = {"text": str(text).strip(), "at": str(at).strip(), "daily": bool(daily),
           "created": f"{datetime.now():%Y-%m-%d %H:%M}"}
    rows.append(row)
    reminders_save(rows)
    return row


def parse_reminder(t: str):
    """«напомни мне забрать дейлики через 10 минут», «в 20:00 выключи зарядку»,
    «каждый день в 9:00 напомни позвонить» -> (о чём, at, каждый день?) или None."""
    if not re.search(r"\b(?:напомни|напомнить)\b", t):
        return None
    body = re.sub(r"\b(?:напомни|напомнить)(?:\s+мне)?\b", " ", t)
    at, daily = None, False

    md = re.search(r"\b(?:каждый день|ежедневно)\s+(?:в\s+)?(\d{1,2})[:.](\d{2})\b", body)
    if md:
        daily, at = True, f"{int(md.group(1)):02d}:{md.group(2)}"
        body = (body[:md.start()] + " " + body[md.end():]).strip()

    if at is None:
        mc = re.search(r"\bчерез\s+(\d+)\s*(секунд\w*|сек|минут\w*|мин|час\w*|ч)\b", body)
        if mc:
            n, unit = int(mc.group(1)), mc.group(2)
            delta = (timedelta(seconds=n) if unit.startswith("сек")
                     else timedelta(minutes=n) if unit.startswith(("мин", "м"))
                     else timedelta(hours=n))
            at = (datetime.now() + delta).strftime("%Y-%m-%d %H:%M")
            body = (body[:mc.start()] + " " + body[mc.end():]).strip()

    if at is None:
        mt = re.search(r"\b(?:сегодня|завтра)?\s*в\s+(\d{1,2})[:.](\d{2})\b", body)
        if mt:
            when = datetime.now().replace(hour=int(mt.group(1)), minute=int(mt.group(2)),
                                          second=0, microsecond=0)
            if "завтра" in body[:mt.start()].lower():
                when += timedelta(days=1)
            elif when <= datetime.now():
                when += timedelta(days=1)  # время уже прошло — на завтра
            at = when.strftime("%Y-%m-%d %H:%M")
            body = (body[:mt.start()] + " " + body[mt.end():]).strip()

    if at is None:
        return None
    body = re.sub(r"\b(пожалуйста|мне|напомни|напомнить|сегодня|завтра|чтобы|нужно|про)\b", "", body)
    body = re.sub(r"\s{2,}", " ", body).strip(" ,.!?\t")
    return (body, at, daily) if body else None


def reminders_text() -> str:
    rows = reminders_load()
    if not rows:
        return ""
    out = [f"— {r.get('text')} ({'каждый день в ' if r.get('daily') else ''}{r.get('at')})"
           for r in sorted(rows, key=lambda r: str(r.get("at")))]
    return "Напоминания:\n" + "\n".join(out)


def _fire_reminder(text: str) -> None:
    print(f"[напоминание] {text}")
    notify(f"Напоминание: {text}", force_speak=True)
    history_add("напоминание", "напоминание", text)


def reminders_loop() -> None:
    """Фоновая проверка каждые 10 секунд: разовые срабатывают и удаляются, ежедневные — раз в день."""
    while not STATE.stop.is_set():
        time.sleep(10)
        try:
            now = datetime.now()
            rows = reminders_load()
            if not rows:
                continue
            changed = False
            for r in list(rows):
                text, at = str(r.get("text") or ""), str(r.get("at") or "")
                if r.get("daily"):
                    try:
                        hh, mm = map(int, at.split(":"))
                    except ValueError:
                        continue
                    due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                    if now >= due and r.get("last") != f"{now:%Y-%m-%d}":
                        r["last"] = f"{now:%Y-%m-%d}"
                        changed = True
                        _fire_reminder(text)
                else:
                    try:
                        due = datetime.strptime(at, "%Y-%m-%d %H:%M")
                    except ValueError:
                        continue
                    if now >= due:
                        rows.remove(r)
                        changed = True
                        _fire_reminder(text)
            if changed:
                reminders_save(rows)
        except Exception as e:  # noqa: BLE001
            log_error("Напоминания", e)


def cmd_reminders(t):
    if is_word(t, "удали", "удалить", "очисти", "очистить", "сбрось", "отмени", "отменить", "убери"):
        reminders_save([])
        notify("Все напоминания удалены.")
        return
    txt = reminders_text()
    if not txt:
        notify("Напоминаний нет.")
        return
    show_text("reminders.txt", txt)
    notify("Показал напоминания." if len(txt) < 200 else txt)


def cmd_remind(t):
    plan = parse_reminder(t)
    if not plan:
        if ai_ready():
            ask_ai(ai_question(t) or t)  # время поняла только нейросеть (add_reminder)
        else:
            notify("Скажи, когда: «напомни через 10 минут …», «напомни в 20:00 …» или "
                   "«каждый день в 9:00 …».", ok=False)
        return
    text, at, daily = plan
    reminder_add(text, at, daily)
    when = f"каждый день в {at}" if daily else at
    notify(f"Хорошо, напомню: {text} — {when}.")
    history_add("напоминание", t, f"поставлено: {text} ({when})")


def show_text(name: str, text: str) -> None:
    """Печатает в консоль, а в exe без консоли — пишет файл и открывает его."""
    try:
        print(text)
    except UnicodeEncodeError:
        # консоль Windows в cp1251 не знает ✓/✗/«» — печатаем ASCII-вариант
        safe = (text.replace("✓", "[+]").replace("✗", "[ ]").replace("«", '"').replace("»", '"')
                .replace("—", "-").replace("…", "..."))
        print(safe.encode(sys.stdout.encoding or "cp1251", "replace").decode(
            sys.stdout.encoding or "cp1251"))
    if sys.stdout is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / name
        path.write_text(text, encoding="utf-8")
        os.startfile(str(path))


def cmd_help(t):
    show_text("commands.txt", commands_text())
    notify("Список команд открыт." if sys.stdout is None else "Все команды я вывел в консоль.")


def cmd_voice(t):
    STATE.voice_enabled = not STATE.voice_enabled
    notify(f"Голосовой вывод {'включён' if STATE.voice_enabled else 'выключен'}.", force_speak=True)


def cmd_forget(t):
    """«забудь разговор» / «новый разговор» — стереть память диалога у нейросети."""
    if ASSISTANT is not None:
        ASSISTANT.forget()
    STATE.attention_until = 0.0
    notify("Забыл разговор. Начнём заново?")


def cmd_track(t):
    m = TRACK_RE.search(t)
    play_track(m.group(1).strip())


def cmd_search(t):
    query = SEARCH_RE.search(t).group(1).strip(" .,!?")
    if not query:
        notify("Не расслышал, что искать.", ok=False)
        return
    open_url("https://www.google.com/search?q=" + quote_plus(query), f"поиск «{query}»")


# ----- нейросеть --------------------------------------------------------------

def _self_files() -> list:
    """Свои исходники: рядом с программой (git/разработка) либо в папке src рядом с exe."""
    names = ("jarvis.py", "jarvis_ai.py", "jarvis_settings.py")
    out = [str(APP_DIR / n) for n in names if (APP_DIR / n).is_file()]
    if not out:
        out = [str(APP_DIR / "src" / n) for n in names if (APP_DIR / "src" / n).is_file()]
    return out


def ai_context() -> dict:
    launchers = [name for name, finder in (
        ("Genshin Impact", find_genshin), ("Minecraft", find_minecraft), ("Prism Launcher", find_prism),
        ("Discord", discord_command), ("Telegram", find_telegram)) if finder()]
    return {"mode": "игровой" if STATE.playing else "учебный", "steam_exe": find_steam(),
            "launchers": launchers, "known_games": sorted(CFG["games"]),
            "folders": user_folders(),            # рабочий стол, загрузки, документы, фото…
            "telegram": find_telegram(),          # путь к Telegram для отправки сообщений
            "frozen": FROZEN,                     # собран в exe — правка кода требует пересборки
            "self_files": _self_files(),          # нейросеть может редактировать сама себя (ai.self_edit)
            "config_file": str(user_config_path())}


def ai_file_written(path: str) -> None:
    """Нейросеть записала файл — перечитать конфиг или напомнить о перезапуске."""
    try:
        p = Path(path)
        if p.name == "config.json" and p.resolve() == user_config_path().resolve():
            reload_config()
            print("[ai] config.json перечитан")
        elif p.suffix == ".py" and p.parent == APP_DIR:
            notify(f"Я изменил свой код ({p.name}). Перезапусти Джарвиса, чтобы изменения вступили в силу.")
    except Exception as e:  # noqa: BLE001
        log_error("Правка файла нейросетью", e)


# ----- действия нейросети: свои игры, сайты, команды, напоминания -------------

def act_add_game(a) -> str:
    phrase = _norm(str(a.get("phrase") or "").strip())
    appid = int(a.get("appid") or 0)
    if not phrase or appid <= 0:
        raise ValueError("Нужны phrase (фраза) и appid (число из Steam).")
    games = dict(CFG["games"])
    games[phrase] = appid
    save_user_config({"games": games})
    return f"Добавил игру «{phrase}» (appid {appid}). Теперь запускается фразой: «запусти {phrase}»."


def act_add_site(a) -> str:
    phrase = _norm(str(a.get("phrase") or "").strip())
    url = str(a.get("url") or "").strip()
    if not phrase or not url:
        raise ValueError("Нужны phrase и url.")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "https://" + url
    sites = dict(CFG["sites"])
    sites[phrase] = url
    save_user_config({"sites": sites})
    return f"Добавил сайт «{phrase}» ({url}). Открывается фразой: «открой {phrase}»."


def act_add_command(a) -> str:
    phrase = _norm(str(a.get("phrase") or "").strip())
    target = str(a.get("target") or "").strip()
    if not phrase or not target:
        raise ValueError("Нужны phrase и target.")
    cmds = [c for c in CFG["commands"] if c["phrase"] != phrase] + [{"phrase": phrase, "target": target}]
    save_user_config({"commands": cmds})
    return f"Добавил команду «{phrase}» → {target}. Скажи «{phrase}»."


def act_add_reminder(a) -> str:
    text = str(a.get("text") or "").strip()
    at = str(a.get("at") or "").strip()
    daily = str(a.get("repeat") or "").lower() in ("daily", "ежедневно", "каждый день") or bool(a.get("daily"))
    if not text or not at:
        raise ValueError("Нужны text и at.")
    if daily and re.fullmatch(r"\d{1,2}:\d{2}", at):
        at = f"{int(at.split(':')[0]):02d}:{at.split(':')[1]}"
        reminder_add(text, at, True)
        return f"Напомню каждый день в {at}: {text}."
    dt = datetime.fromisoformat(at.replace(" ", "T"))  # «2026-10-07 20:00» или с Т
    reminder_add(text, dt.strftime("%Y-%m-%d %H:%M"), False)
    return f"Напоминание поставлено: «{text}» — {dt:%d.%m.%Y в %H:%M}."


def act_list_reminders(a) -> str:
    return reminders_text() or "Напоминаний нет."

def act_delete_reminders(a) -> str:
    reminders_save([])
    return "Удалил все напоминания."


def _schema(name: str, desc: str, props: dict, required: list) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": props,
                                                            "required": required}}}


AI_ACTION_TOOLS = [
    (_schema("add_game", "Добавить игру в свои команды Джарвиса: голосовая фраза -> appid Steam",
             {"phrase": {"type": "string", "description": "Как назвать игру голосом, например «вуконг»"},
              "appid": {"type": "integer", "description": "appid из Steam"}},
             ["phrase", "appid"]), act_add_game),
    (_schema("add_site", "Добавить сайт в список «открой …»",
             {"phrase": {"type": "string", "description": "Фраза, например «почта»"},
              "url": {"type": "string", "description": "Адрес сайта"}},
             ["phrase", "url"]), act_add_site),
    (_schema("add_command", "Добавить свою команду: голосовая фраза -> программа, папка или ссылка",
             {"phrase": {"type": "string", "description": "Фраза"},
              "target": {"type": "string", "description": "notepad.exe, путь или https://…"}},
             ["phrase", "target"]), act_add_command),
    (_schema("add_reminder", "Поставить напоминание: сработает голосом в указанное время",
             {"text": {"type": "string", "description": "О чём напомнить"},
              "at": {"type": "string", "description": "«ГГГГ-ММ-ДД ЧЧ:ММ» (разовое) или «ЧЧ:ММ» (ежедневное)"},
              "repeat": {"type": "string", "enum": ["once", "daily"],
                         "description": "once — один раз, daily — каждый день"}},
             ["text", "at"]), act_add_reminder),
    (_schema("list_reminders", "Показать все напоминания", {}, []), act_list_reminders),
    (_schema("delete_reminders", "Удалить все напоминания", {}, []), act_delete_reminders),
]


ASSISTANT = (jarvis_ai.Assistant(lambda: CFG["ai"], ai_context, on_write=ai_file_written,
                                 actions=AI_ACTION_TOOLS) if jarvis_ai else None)


def ai_ready() -> bool:
    return ASSISTANT is not None and bool(CFG["ai"]["enabled"])


def ai_question(text: str) -> str:
    """Фраза без обращения к Джарвису."""
    for n in CFG["ai"]["names"]:
        text = text.replace(n, " ")
    return re.sub(r"\s+", " ", text).strip(" ,.!?-—")


def ask_ai(question: str) -> None:
    print(f"[ai] вопрос: {question}")
    if not ASSISTANT.lock.acquire(blocking=False):
        notify("Подожди, я ещё отвечаю на прошлый вопрос.", ok=False)
        return

    def worker():
        try:
            if notifier:
                notifier.show("Думаю…", True, 1500)
            answer = ASSISTANT.ask(question)  # ответ уходит и во всплывашку, и в голос
            history_add("нейросеть", question, answer, ASSISTANT.last_tools)
            notify(answer)
        except jarvis_ai.AIError as e:
            history_add("нейросеть", question, f"ошибка: {e}")
            notify(str(e), ok=False)
        except Exception as e:
            log_error("Нейросеть", e)
            history_add("нейросеть", question, "ошибка: нейросеть недоступна")
            notify("Нейросеть сейчас недоступна.", ok=False)
        finally:
            ASSISTANT.lock.release()

    threading.Thread(target=worker, daemon=True).start()


def cmd_genshin(t):
    task = CFG["genshin_task"]
    if task:
        if run_quiet(["schtasks", "/run", "/tn", task]) == 0:
            notify("Запускаю Genshin Impact.")
            return
        print(f"[genshin] задача «{task}» не запустилась — пробую найти игру напрямую")
    launch_app(find_genshin(), "Genshin Impact", "genshin")


def _game_key(t):
    return next((k for k in CFG["games"] if re.search(r"\b" + re.escape(k), t)), None)


def cmd_steam_game(t):
    key = _game_key(t)
    os.startfile(f"steam://rungameid/{CFG['games'][key]}")
    notify(f"Запускаю {key}.")


def cmd_steam(t):
    path = find_steam()
    if path:
        launch_app(path, "Steam", "steam")
    else:
        try:
            os.startfile("steam://open/main")
            notify("Запускаю Steam.")
        except OSError:
            notify("Steam не найден на этом компьютере.", ok=False)


def cmd_discord(t):
    cmd = discord_command()
    if not cmd:
        notify("Не нашёл Discord. Укажи путь в config.json → paths.discord.", ok=False)
        return
    popen(cmd)
    notify("Запускаю Discord.")


def cmd_close_discord(t):
    # Squirrel-«нянька» Update.exe Discord'а перезапускает его — гасим только ЕЁ
    # (по пути), чтобы не задеть Update.exe других приложений (Slack и т.п.)
    run_quiet(["powershell", "-NoProfile", "-Command",
               r"Get-Process Update -ErrorAction SilentlyContinue | "
               r"Where-Object { $_.Path -like '*\Discord\*' } | Stop-Process -Force"])
    close_app("Discord.exe", "Discord")


def cmd_study(t):
    chrome = find_chrome()
    if chrome:
        popen([chrome, f"--profile-directory={chrome_profile('study')}"])
        notify("Открываю Chrome с учебным профилем.")
    else:
        notify("Chrome не найден — открываю браузер по умолчанию.", ok=False)
        webbrowser.open("https://www.google.com")


def cmd_site(t):
    requested = t.split("открой", 1)[-1].strip()
    key = next((k for k in CFG["sites"] if k in requested), None)
    if key:
        open_url(CFG["sites"][key], key)
    else:
        notify(f"Сайт «{requested}» не в списке разрешённых — не открываю.", ok=False)


def run_target(target: str, label: str) -> None:
    """Ссылка -> браузер; протокол (steam://…) -> ShellExecute; файл/папка -> запуск;
    иначе — команда оболочки (notepad.exe, calc…)."""
    t = target.strip()
    try:
        if re.match(r"^(https?://|www\.)", t, re.I):
            open_url(t if t.lower().startswith("http") else "https://" + t, label)
            return
        if re.match(r"^[a-z][a-z0-9+.-]*://", t, re.I):
            os.startfile(t)
        else:
            path = os.path.expandvars(os.path.expanduser(t.strip('"')))
            if os.path.exists(path):
                shell_open(path, cwd=path if os.path.isdir(path) else os.path.dirname(path))
            else:
                popen(t, shell=True)
        notify(f"Запускаю {label}.")
    except Exception as e:
        log_error(f"Команда «{label}»", e)
        notify(f"Не удалось запустить «{label}».", ok=False)


def _custom_match(t):
    cmds = sorted(CFG["commands"], key=lambda c: -len(c["phrase"]))  # длинные фразы приоритетнее
    return next((c for c in cmds if has(t, c["phrase"])), None)


def cmd_custom(t):
    c = _custom_match(t)
    run_target(c["target"], c["phrase"])


def cmd_settings(t):
    if jarvis_settings is None:
        notify("Для окна настроек нужен customtkinter:  pip install customtkinter", ok=False)
        return
    notify("Открываю настройки.")
    notifier.call(lambda root: jarvis_settings.open_settings(
        root, CFG, save_user_config, AUTOSTART, jarvis_ai,
        say=lambda text: speaker.say(text) if speaker else None))


def U(key):  # ссылка из config.urls
    return lambda t: open_url(CFG["urls"].get(key), key)


CLOSE = lambda t: has(t, "закр")

# Порядок важен: первая подошедшая команда выполняется, остальные пропускаются.
# Третье поле — «только в игровом режиме».
COMMANDS = [
    Cmd(lambda t: is_word(t, "выход", "выйти"), cmd_exit, False),
    Cmd(lambda t: is_word(t, "отмена", "отмени", "отменить") and not has(t, "напоминани"),
        cmd_cancel_shutdown, False),
    Cmd(lambda t: has(t, "настройк"), cmd_settings, False),
    # раньше своих команд: «загугли кс2» должно искать, а не запускать игру
    Cmd(lambda t: bool(SEARCH_RE.search(t)) and not TRACK_RE.search(t), cmd_search, False),
    Cmd(lambda t: _custom_match(t) is not None, cmd_custom, False),  # свои команды — раньше встроенных
    Cmd(lambda t: has(t, "выключ") and is_pc(t), cmd_shutdown, True),
    Cmd(lambda t: has(t, "перезагруз") and is_pc(t), cmd_restart, True),
    Cmd(lambda t: has(t, "заметк", "запис") and has(t, "откр", "покаж", "показ", "прочита",
                                                      "прочит", "посмотр", "читай", "очист",
                                                      "удали", "удалит", "сотр", "стереть",
                                                      "стер", "сброс", "удалить"),
        cmd_notes, False),
    Cmd(lambda t: has(t, "запиш", "заметк"), cmd_note, False),
    Cmd(lambda t: parse_create(t) is not None, cmd_create, False),  # «создай файл …», «создай папку …»
    # удаление — раньше своих команд: «удали команду блокнот» не должно запускать блокнот
    Cmd(lambda t: has(t, "удали", "удалить", "убери", "сотри", "стереть") and has(t, "команду", "команда",
                                                                                 "фразу", "игру", "сайт"),
        cmd_delete_command, False),
    Cmd(lambda t: (has(t, "удали", "удалить", "убери", "сотри", "стереть", "удалю", "удалён")
                   and has(t, "файл", "папк", "документ", "директори", "каталог"))
        or has(t, "удали файл", "удали папку", "удалить файл", "удалить папку"),
        cmd_delete, False),
    # диктовка — раньше «найди» и раньше нейронки: «напечатай …» вставляет, а не гуглит/спрашивает
    Cmd(lambda t: bool(re.search(r"\b(?:надиктуй|диктуй|диктовка|напечатай|напечать|"
                                 r"набери|набрать|вставь|вставить|продиктуй)\b", t)),
        cmd_dictate, False),
    # «открой файл / папку / документ» — не сайт, а файл; раньше игр, «учеб» и «открой-сайт»
    Cmd(wants_open_item, cmd_open, False),
    Cmd(is_help, cmd_help, False),
    Cmd(lambda t: has(t, "истори"), cmd_history, False),  # история запросов / очисти историю
    Cmd(lambda t: has(t, "напоминани"), cmd_reminders, False),  # покажи/удали напоминания
    Cmd(lambda t: has(t, "напомни"), cmd_remind, False),        # напомни мне …
    Cmd(lambda t: is_word(t, "голос"), cmd_voice, False),
    Cmd(lambda t: has(t, "забудь", "забыть") or has(t, "новый разговор"), cmd_forget, False),
    Cmd(lambda t: bool(TRACK_RE.search(t)), cmd_track, False),  # раньше «музык» и «песн»
    Cmd(lambda t: has(t, "музык") and CLOSE(t), lambda t: close_music_windows(), False),
    Cmd(lambda t: has(t, "музык"), lambda t: open_music(), False),
    Cmd(lambda t: has(t, "песн"), lambda t: threading.Thread(target=_resume_last_track, daemon=True).start(), False),
    Cmd(lambda t: has(t, "геншин", "genshin"), cmd_genshin, True),
    Cmd(lambda t: _game_key(t) is not None, cmd_steam_game, True),
    Cmd(lambda t: has(t, "майнкрафт", "minecraft"),
        lambda t: launch_app(find_minecraft(), "Minecraft", "minecraft"), True),
    Cmd(lambda t: has(t, "призм", "prism"), lambda t: launch_app(find_prism(), "Prism Launcher", "prism"), True),
    Cmd(lambda t: has(t, "роблокс", "roblox"), U("roblox"), True),
    Cmd(lambda t: has(t, "логик", "logik"), U("logika"), False),
    Cmd(lambda t: has(t, "стим", "steam") and CLOSE(t), lambda t: close_app("steam.exe", "Steam"), False),
    Cmd(lambda t: has(t, "стим", "steam"), cmd_steam, True),
    Cmd(lambda t: has(t, "дискорд", "discord") and CLOSE(t), cmd_close_discord, False),
    Cmd(lambda t: has(t, "дискорд", "discord"), cmd_discord, True),
    Cmd(lambda t: has(t, "телеграм", "telegram") and CLOSE(t), lambda t: close_app("Telegram.exe", "Telegram"), False),
    Cmd(lambda t: has(t, "телеграм", "telegram"), lambda t: launch_app(find_telegram(), "Telegram", "telegram"), False),
    Cmd(lambda t: has(t, "учеб"), cmd_study, False),
    Cmd(lambda t: is_word(t, "пара", "пару", "пары", "урок", "занятие") or "на пару" in t,
        lambda t: open_url(CFG["urls"].get("classroom"), "classroom", study=True), False),
    Cmd(lambda t: has(t, "фильм", "кино"), U("films"), True),
    Cmd(lambda t: has(t, "аниме"), U("anime"), True),
    Cmd(lambda t: has(t, "гитхаб", "github"), U("github"), False),
    Cmd(lambda t: has(t, "комплектующ"), U("parts"), False),
    Cmd(lambda t: has(t, "браузер") and CLOSE(t), lambda t: close_app("chrome.exe", "браузер"), False),
    Cmd(lambda t: has(t, "открой"), cmd_site, False),
]


# Одиночные команды (состояние, выход, питание): в цепочках не участвуют —
# «выключи пк и открой стим» выполнит только выключение, остальное проигнорирует.
_SINGLE_RUNS = (cmd_exit, cmd_cancel_shutdown, cmd_shutdown, cmd_restart, cmd_voice, cmd_forget)


def _chain_run(parts: list, addressed: bool) -> bool:
    """Выполнить части фразы как цепочку команд по очереди («открой стим и заметки»).
    Часть без глагола наследует его у предыдущей («заметки» -> «открой заметки»).
    Возвращает True, только если ВСЕ части нашли свою команду, — иначе вызывающий
    откатывается на обычную логику для целой фразы."""
    matched = []
    verb = ""
    for part in parts:
        cmd, trial = None, part
        if verb:
            # «заметки» после «открой стим» — это «открой заметки», а не «запиши»:
            # пробуем с глаголом СНАЧАЛА, иначе голое слово совпадёт не с той командой
            trial = f"{verb} {part}"
            cmd = next((c for c in COMMANDS if c.match(trial)), None)
        if cmd is None:
            trial = part
            cmd = next((c for c in COMMANDS if c.match(part)), None)
        if cmd is None and ai_ready():
            q = ai_question(part)
            if q and jarvis_ai.is_question(q) and not is_help(q):
                matched.append((None, q))  # вопрос нейросети — тоже часть цепочки
                continue
        if cmd is None:
            return False
        if cmd.run in _SINGLE_RUNS:  # выход/сон/голос/забывание — только отдельно, не в цепочке
            return False
        matched.append((cmd, trial))
        verb = trial.split(" ", 1)[0]
    P = CFG["phrases"]
    for cmd, trial in matched:
        if cmd is None:
            ask_ai(trial)
            continue
        if cmd.play_only and not STATE.playing:
            notify(f"Сейчас учебный режим. Скажи «{P['play_mode']}».", ok=False)
            continue
        cmd.run(trial)
        # самим командам журналировать себя важнее (в них уже есть свой ответ)
        if addressed and cmd.run not in (cmd_history, cmd_remind, cmd_reminders):
            history_add("команда", trial, "выполнена")
    return True


def process(text: str) -> None:
    P = CFG["phrases"]
    if not STATE.listening:
        if P["resume"] in text:
            STATE.listening = True
            notify("Джарвис снова слушает команды.")
        return

    wake = CFG["wake_word"]
    if wake["enabled"]:
        if wake["word"] not in text:
            return
        text = text.replace(wake["word"], "", 1).strip()

    # Обращение к Джарвису: слово-активатор уже проверено выше, иначе ищем имя в фразе.
    # Если Джарвис «держит внимание» (только что говорили) — имя можно не называть.
    named = any(n in text for n in CFG["ai"]["names"])
    attentive = time.time() < STATE.attention_until
    addressed = bool(wake["enabled"]) or named or attentive
    if addressed and ai_ready():
        window = (CFG["ai"].get("chat") or {}).get("attention_sec", 25)
        STATE.attention_until = time.time() + max(0.0, window)
    ask = ai_question(text) if addressed and ai_ready() else None

    if P["pause"] in text:
        STATE.listening = False
        notify(f"Джарвис на паузе. Скажите «{P['resume']}», чтобы возобновить.")
        return
    if P["study_mode"] in text:
        STATE.playing = False
        notify("Включаю учебный режим.")
        return
    if P["play_mode"] in text:
        STATE.playing = True
        notify("Включаю игровой режим.")
        return

    # Несколько команд сразу: «открой стим и заметки», «запусти майнкрафт, потом музыку».
    # Одиночные (пауза, режимы, сон/выход, голос, забывание) в цепочках не участвуют —
    # их выполнение среди прочего было бы сюрпризом.
    if not any(k in text for k in (P["pause"], P["study_mode"], P["play_mode"])):
        parts = split_chain(text)
        if len(parts) > 1 and _chain_run(parts, addressed):
            return

    # вопрос («какая погода», «что поиграть») — сразу нейросети, а не по списку команд.
    # НО: диктовка («напечатай …») и удаление («удали файл …») — всегда локальные команды,
    # даже если сказаны с обращением «Джарвис»: иначе «напечатай в телеграм» уходит нейронке.
    _local_first = re.search(r"\b(?:надиктуй|диктуй|диктовка|напечатай|напечать|"
                             r"набери|набрать|вставь|вставить|продиктуй)\b", text)
    if _local_first:
        for cmd in COMMANDS:
            if cmd.run is cmd_dictate and cmd.match(text):
                cmd.run(text)
                if addressed:
                    history_add("команда", text, "выполнена")
                return
    if ask and jarvis_ai.is_question(ask) and not is_help(ask) and not _local_first:
        ask_ai(ask)
        return

    for cmd in COMMANDS:
        if cmd.match(text):
            if cmd.play_only and not STATE.playing:
                notify(f"Сейчас учебный режим. Скажи «{P['play_mode']}».", ok=False)
            else:
                cmd.run(text)
                # самим командам журналировать себя важнее (в них уже есть свой ответ)
                if addressed and cmd.run not in (cmd_history, cmd_remind, cmd_reminders):
                    history_add("команда", text, "выполнена")
            return

    if ask:  # обратились по имени, но это не команда — пусть ответит нейросеть
        ask_ai(ask)
    elif addressed and jarvis_ai and not CFG["ai"]["enabled"] and jarvis_ai.is_question(ai_question(text)):
        notify("Нейросеть выключена. Включи её в настройках, вкладка «Нейросеть», и нажми «Сохранить».", ok=False)


# ============================================================================
#  Прослушивание
# ============================================================================

recognizer = sr.Recognizer()
audio_q: queue.Queue = queue.Queue(maxsize=5)


def listener_loop(ready: threading.Event) -> None:
    """Микрофон открыт постоянно, распознавание идёт в другом потоке —
    поэтому фразы не теряются, пока Google думает."""
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
            ready.set()
            while not STATE.stop.is_set():
                if speaker and speaker.busy.is_set():
                    source.stream.read(source.CHUNK)  # вычитываем и выбрасываем эхо Джарвиса
                    continue
                try:
                    audio = recognizer.listen(source, timeout=1, phrase_time_limit=12)
                except sr.WaitTimeoutError:
                    continue
                if speaker and speaker.busy.is_set():
                    continue
                try:
                    audio_q.put_nowait(audio)
                except queue.Full:
                    pass
    except Exception as e:
        log_error("Микрофон", e)
        print("Не удалось открыть микрофон. Проверь, что он подключён и разрешён в настройках Windows.")
        STATE.stop.set()
    finally:
        ready.set()


def main_loop() -> None:
    last_net_warning = 0.0
    while not STATE.stop.is_set():
        try:
            audio = audio_q.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            text = _norm(recognizer.recognize_google(audio, language=CFG["language"]))
            print(f"Вы сказали: {text}")
            process(text)
        except sr.UnknownValueError:
            pass
        except sr.RequestError as e:
            log_error("Сервис распознавания", e)
            if time.time() - last_net_warning > 30:
                notify("Нет связи с сервисом распознавания речи.", ok=False)
                last_net_warning = time.time()
        except Exception as e:
            log_error("Обработка команды", e)
            notify(f"Ошибка: {e}"[:120], ok=False)


# ============================================================================
#  Диагностика и точка входа
# ============================================================================

def print_check() -> None:
    rows = [
        ("Chrome", find_chrome()),
        ("Chrome-профиль (основной)", chrome_profile("main")),
        ("Chrome-профиль (учебный)", chrome_profile("study")),
        ("YouTube Music (ярлык PWA)", find_ytmusic_shortcut() or "нет — откроется через Chrome --app"),
        ("Discord", " ".join(discord_command() or []) or None),
        ("Telegram", find_telegram()),
        ("Steam", find_steam()),
        ("Genshin Impact", f"задача {CFG['genshin_task']}" if CFG["genshin_task"] else find_genshin()),
        ("Minecraft Launcher", find_minecraft()),
        ("Prism Launcher", find_prism()),
        ("Голос", current_voice_name()),
        ("Голос (запасной SAPI)", _sapi_name() or None),
        ("Голос (запасной pyttsx3)", "установлен" if pyttsx3 else None),
        ("Нейросеть", (f"{CFG['ai']['provider']}, ключ {'задан' if jarvis_ai and jarvis_ai.resolve(CFG['ai'])[2] else 'НЕ задан'}"
                       if CFG["ai"]["enabled"] else "выключена (настройки → Нейросеть)") if jarvis_ai else None),
        ("ytmusicapi", "установлен" if YTMusic else None),
        ("Папка данных", str(DATA_DIR)),
    ]
    lines = [f"  {'✓' if val else '✗'} {name:28} {val or 'не найдено'}" for name, val in rows]
    for k in ("classroom", "logika"):
        if not CFG["urls"].get(k):
            lines.append(f"  ! urls.{k} не задан (config.json) — команда работать не будет")
    show_text("check.txt", "\n".join(lines))


def list_voices() -> None:
    print("Живые нейроголоса Piper (офлайн, auto-скачивание ~63 МБ):")
    try:
        import jarvis_voice_piper as p

        for name, ok, size in p.list_status():
            mark = "скачан" if ok else "скачается при первом использовании"
            extra = f" ({size} МБ)" if ok else ""
            cur = "  <-- текущий" if name == (CFG["voice"].get("piper_voice") or "dmitri") else ""
            print(f"  {name}{extra}: {mark}{cur}")
        print("Смена голоса: config.json -> voice.piper_voice "
              "(dmitri | ruslan | irina | denis) или в окне настроек.")
    except Exception as e:
        print(f"Piper недоступен: {e} (pip install piper-tts)")
    print("\nГолоса Windows SAPI (запасные):")
    try:
        _sp, tokens = sapi_voices()
    except Exception as e:
        print(f"SAPI недоступен: {e}")
        return
    for t in tokens:
        desc, langs = _token_info(t)
        print(f"{desc}  [языки: {', '.join(langs) or '?'}]\n   id: {t.Id}")
    if not tokens:
        print("Голосов нет. Добавь голос: Параметры → Время и язык → Речь.")


def say_test(text: str) -> None:
    """jarvis.py --say "текст": проверка голоса. Ошибки озвучки пишутся в errors.log."""
    sp = Speaker()
    sp.say(text)
    time.sleep(0.3)
    while sp.busy.is_set():
        time.sleep(0.1)
    print(f"Готово. Если звука не было, смотри {ERROR_LOG}")


def ask_test(question: str) -> None:
    """jarvis.py --ask "вопрос": спросить нейросеть из консоли, без микрофона и голоса."""
    if ASSISTANT is None:
        print("Модуль jarvis_ai не найден.")
        return
    try:
        answer = ASSISTANT.ask(_norm(question))
        print(answer)
        history_add("консоль", question, answer, ASSISTANT.last_tools)
    except jarvis_ai.AIError as e:
        print(f"[!!] {e}")
        history_add("консоль", question, f"ошибка: {e}")


def main() -> None:
    global notifier, speaker
    ap = argparse.ArgumentParser(description="Джарвис — голосовой ассистент")
    ap.add_argument("--check", action="store_true", help="показать, что найдено на этом ПК")
    ap.add_argument("--list-voices", action="store_true", help="список голосов TTS")
    ap.add_argument("--say", metavar="ТЕКСТ", help="проверить голос: произнести текст")
    ap.add_argument("--ask", metavar="ВОПРОС", help="спросить нейросеть (нужен ключ в настройках)")
    args = ap.parse_args()
    if args.check:
        print_check()
        return
    if args.list_voices:
        list_voices()
        return
    if args.say:
        say_test(args.say)
        return
    if args.ask:
        ask_test(args.ask)
        return

    if not single_instance():
        ctypes.windll.user32.MessageBoxW(0, "Джарвис уже запущен.", "Джарвис", 0x40)
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    notifier = Notifier()
    speaker = Speaker()

    ready = threading.Event()
    threading.Thread(target=listener_loop, args=(ready,), daemon=True).start()
    ready.wait(15)  # приветствие — после калибровки шума, чтобы голос не сбил порог
    if not STATE.stop.is_set():
        notify("Джарвис слушает вас, господин.")
    threading.Thread(target=reminders_loop, daemon=True).start()  # напоминания: «напомни через …»

    try:
        main_loop()
    except KeyboardInterrupt:
        pass
    finally:
        STATE.stop.set()
        waited = 0.0
        while speaker.busy.is_set() and waited < 5:  # дать договорить последнюю фразу
            time.sleep(0.1)
            waited += 0.1
        notifier.close()
        stuck = [t.name for t in threading.enumerate() if t is not threading.main_thread() and not t.daemon]
        if stuck:  # такие потоки не дают процессу завершиться — пишем в лог, чтобы найти причину
            log_error("Выход", RuntimeError(f"не завершились потоки: {stuck}"))
        os._exit(0)  # без этого процесс мог остаться висеть в фоне, хотя Джарвис уже не слушает


if __name__ == "__main__":
    main()