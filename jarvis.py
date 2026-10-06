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
from datetime import datetime
from functools import lru_cache
from pathlib import Path

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

YT_MUSIC_URL = "https://music.youtube.com"
YT_MUSIC_WINDOW_TITLE = "YouTube Music"

DEFAULT_CONFIG = {
    "language": "ru-RU",
    "wake_word": {"enabled": False, "word": "джарвис"},
    "voice": {"enabled": True, "id": None, "rate": 175},
    "shutdown_delay_sec": 15,
    "chrome": {"main_profile": "Default", "study_profile": None},
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


_MERGE_KEYS = ("voice", "wake_word", "chrome")


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


class Speaker:
    """Очередь реплик + один воркер. busy выставляется сразу при постановке в очередь
    и снимается только когда очередь пуста — Джарвис не слышит сам себя."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.busy = threading.Event()
        if pyttsx3 is not None:
            threading.Thread(target=self._run, daemon=True).start()

    def say(self, text: str) -> None:
        if pyttsx3 is None:
            return
        self.busy.set()
        self.q.put(text)

    def _run(self) -> None:
        engine = None
        while True:
            text = self.q.get()
            try:
                if engine is None:
                    engine = pyttsx3.init()
                    vid = _pick_voice(engine)
                    if vid:
                        engine.setProperty("voice", vid)
                    engine.setProperty("rate", CFG["voice"]["rate"])
                engine.say(text)
                engine.runAndWait()
            except Exception as e:
                log_error("Озвучка", e)
                engine = None
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


STATE = State()
notifier: Notifier | None = None
speaker: Speaker | None = None


def notify(message: str, ok: bool = True, force_speak: bool = False) -> None:
    print(("[ok] " if ok else "[!!] ") + message)
    if notifier:
        notifier.show(message, ok)
    if speaker and (STATE.voice_enabled or force_speak):
        speaker.say(message)


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


def is_pc(text: str) -> bool:
    return is_word(text, "пк", "комп", "компьютер", "компьютера", "ноутбук")


TRACK_RE = re.compile(r"\b(?:включи|поставь|найди)\s+(?:трек|песню|песня)\s+(.+)")
Cmd = namedtuple("Cmd", "match run play_only")


def commands_text() -> str:
    return f"""Список команд Джарвиса:
— выход — завершить программу
— музыка — открыть YouTube Music; закрой музыку — закрыть все окна YouTube Music
— песня — нажать play/pause в YouTube Music
— включи/поставь/найди трек <название> — найти и включить трек
— геншин; майнкрафт; призм; роблокс — запуск игр и лаунчеров
— игры Steam: {", ".join(sorted(CFG["games"]))}
— стим / дискорд / телеграм (+ «закрой …») — запуск и закрытие
— учёба — Chrome с учебным профилем; пара / урок / занятие — Google Classroom
— логика — backoffice Logika; фильм / кино; аниме; гитхаб; комплектующие
— закрой браузер — закрыть все окна Chrome
— открой <сайт> — сайт из списка: {", ".join(sorted(CFG["sites"]))}
— запиши <текст> / заметка <текст> — сохранить заметку ({NOTES_PATH})
— выключи / перезагрузи пк — через {CFG["shutdown_delay_sec"]} с; «отмена» — отменить
— голос — вкл/выкл голосовые ответы
— открой настройки — окно настроек (свои команды, игры, ссылки, пути, автозапуск)
— «{CFG["phrases"]["study_mode"]}» / «{CFG["phrases"]["play_mode"]}» — учебный / игровой режим
— «{CFG["phrases"]["pause"]}» — пауза, «{CFG["phrases"]["resume"]}» — продолжить

Мои команды:
{chr(10).join("— " + c["phrase"] + " → " + c["target"] for c in CFG["commands"]) or "— пока нет (добавь в настройках)"}"""


def cmd_exit(t):
    notify("Выход из программы.")
    STATE.stop.set()


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


def show_text(name: str, text: str) -> None:
    """Печатает в консоль, а в exe без консоли — пишет файл и открывает его."""
    print(text)
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


def cmd_track(t):
    m = TRACK_RE.search(t)
    play_track(m.group(1).strip())


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
    notifier.call(lambda root: jarvis_settings.open_settings(root, CFG, save_user_config, AUTOSTART))


def U(key):  # ссылка из config.urls
    return lambda t: open_url(CFG["urls"].get(key), key)


CLOSE = lambda t: has(t, "закр")

# Порядок важен: первая подошедшая команда выполняется, остальные пропускаются.
# Третье поле — «только в игровом режиме».
COMMANDS = [
    Cmd(lambda t: is_word(t, "выход", "выйти"), cmd_exit, False),
    Cmd(lambda t: is_word(t, "отмена", "отмени", "отменить"), cmd_cancel_shutdown, False),
    Cmd(lambda t: has(t, "настройк"), cmd_settings, False),
    Cmd(lambda t: _custom_match(t) is not None, cmd_custom, False),  # свои команды — раньше встроенных
    Cmd(lambda t: has(t, "выключ") and is_pc(t), cmd_shutdown, True),
    Cmd(lambda t: has(t, "перезагруз") and is_pc(t), cmd_restart, True),
    Cmd(lambda t: has(t, "запиш", "заметк"), cmd_note, False),
    Cmd(lambda t: "что ты умеешь" in t or "список команд" in t or t.strip() == "помощь", cmd_help, False),
    Cmd(lambda t: is_word(t, "голос"), cmd_voice, False),
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

    for cmd in COMMANDS:
        if cmd.match(text):
            if cmd.play_only and not STATE.playing:
                notify(f"Сейчас учебный режим. Скажи «{P['play_mode']}».", ok=False)
            else:
                cmd.run(text)
            return


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
        ("Голос TTS", "pyttsx3 установлен" if pyttsx3 else None),
        ("ytmusicapi", "установлен" if YTMusic else None),
        ("Папка данных", str(DATA_DIR)),
    ]
    lines = [f"  {'✓' if val else '✗'} {name:28} {val or 'не найдено'}" for name, val in rows]
    for k in ("classroom", "logika"):
        if not CFG["urls"].get(k):
            lines.append(f"  ! urls.{k} не задан (config.json) — команда работать не будет")
    show_text("check.txt", "\n".join(lines))


def list_voices() -> None:
    if pyttsx3 is None:
        print("pyttsx3 не установлен")
        return
    for v in pyttsx3.init().getProperty("voices"):
        print(f"{v.name}\n   id: {v.id}")


def main() -> None:
    global notifier, speaker
    ap = argparse.ArgumentParser(description="Джарвис — голосовой ассистент")
    ap.add_argument("--check", action="store_true", help="показать, что найдено на этом ПК")
    ap.add_argument("--list-voices", action="store_true", help="список голосов TTS")
    args = ap.parse_args()
    if args.check:
        print_check()
        return
    if args.list_voices:
        list_voices()
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


if __name__ == "__main__":
    main()
