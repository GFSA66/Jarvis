import os
import sys
import threading
import time
import tkinter as tk
import subprocess
from datetime import datetime

try:
    import pyaudiowpatch as pyaudio
    sys.modules['pyaudio'] = pyaudio
except ImportError:
    pass

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    import gettext as _gettext_module

    _original_gettext_translation = _gettext_module.translation

    def _gettext_translation_with_fallback(*args, **kwargs):
        # ytmusicapi при создании YTMusic() зовёт gettext.translation(...) без
        # fallback=True, чтобы подгрузить свои файлы локализации (.mo). Если
        # собрать проект в .exe через PyInstaller/auto-py-to-exe, эти файлы
        # (не .py-код, а данные) не попадают в сборку автоматически — и
        # gettext.translation роняет FileNotFoundError прямо в конструкторе
        # YTMusic(), хотя как обычный .py-скрипт всё работало нормально.
        # Форсируем fallback=True: если файла нет, вернётся "нулевой" перевод
        # (исходные строки без изменений) вместо падения — для языка по
        # умолчанию (en) результат ровно тот же, что и с настоящим файлом.
        kwargs.setdefault("fallback", True)
        return _original_gettext_translation(*args, **kwargs)

    _gettext_module.translation = _gettext_translation_with_fallback
except ImportError:
    pass

try:
    from ytmusicapi import YTMusic
except ImportError:
    YTMusic = None

import speech_recognition as sr
import pyautogui
import win32con
import win32gui


# Заранее прописанные сайты — никаких URL "из воздуха" по услышанному тексту.
# Ключ ищем ВНУТРИ фразы после "открой", а не берём хвост фразы как домен.
SITES = {
    "браузер": "https://www.google.com",
    "гугл": "https://www.google.com",
    "google": "https://www.google.com",
    "ютуб": "https://www.youtube.com",
    "youtube": "https://www.youtube.com",
    "клод": "https://claude.ai",
    "claude": "https://claude.ai",
}

GAME_PATH = r"D:\Epic Games\GenshinImpact\games\Genshin Impact game\GenshinImpact.exe"

STEAM_PATH = r"D:\Steam\Steam.exe"
DISCORD_PATH = r"C:\Users\GF66s\AppData\Local\Discord\app-1.0.9256\Discord.exe"
TELEGRAM_PATH = r"C:\Users\GF66s\AppData\Roaming\Telegram Desktop\Telegram.exe"

YT_MUSIC_APP = [
    r"C:\Program Files\Google\Chrome\Application\chrome_proxy.exe",
    "--profile-directory=Default",
    "--app-id=cinhimbnkkaeohfgghhklpknlkffjgod",
]

# Подстрока для поиска окна PWA YouTube Music среди всех окон — используется,
# чтобы найти его и нажать пробел после загрузки (см. _resume_last_track).
YT_MUSIC_WINDOW_TITLE = "YouTube Music"

STUDY_PROFILE_APP = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "--profile-directory=Profile 2",
]

MAIN_PROFILE_APP = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "--profile-directory=Default",
]

CLASSROOM_URL = "https://classroom.google.com/c/ODc2MTc3NTI3Mzg5"
FILMS_URL = "https://rezka.ag/films/best/"
ANIME_URL = "https://old.yummyani.me/"
GITHUB_URL = "https://github.com"
PARTS_URL = "https://ek.ua/ua/"
LOGIKA_URL = "https://backoffice.logikaschool.com.ua/groups/"

# Фразы, после которых всё, что сказано дальше, считается названием трека
# для поиска в YouTube Music. Порядок важен только косметически.
TRACK_TRIGGERS = (
    "включи трек",
    "поставь трек",
    "найди трек",
    "поставь песню",
    "найди песню",
)

# Steam-игры запускаем через протокол steam://rungameid/<appid> —
# не завязано на путь установки, работает даже если библиотека Steam переедет.
# Добавить новую игру: правый клик по игре в Steam -> "Свойства" (или зайди на её
# страницу магазина) -> появится число в URL store.steampowered.com/app/<appid>/...
GAMES = {
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
}

# Не-Steam лаунчеры — пути по умолчанию, ПРОВЕРЬ и поправь под свою систему.
MINECRAFT_LAUNCHER_PATH = r"C:\XboxGames\Minecraft Launcher\Content\Minecraft.exe"
PRISM_LAUNCHER_PATH = r"D:\PrismLauncher\prismlauncher.exe"
ROBLOX_URL = "https://www.roblox.com/home"

NOTES_PATH = os.path.join(os.path.expanduser("~"), "Скрытая папка", "jarvis_notes.txt")
ERROR_LOG_PATH = os.path.join(os.path.expanduser("~"), "Скрытая папка", "jarvis_errors.log")

# Впиши сюда id понравившегося голоса — увидишь список в консоли при запуске
# (обычно там что-то вроде "HKEY_LOCAL_MACHINE\...\Tokens\TTS_MS_RU-RU_..." для русского,
# либо "...ZIRA..."/"...DAVID..." для английских голосов).
VOICE_ID = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens\TTS_MS_RU-RU_IRINA_11.0"

COMMANDS_LIST = """Список команд Джарвиса:
— выход — завершить программу
— музыка — открыть YouTube Music (и продолжить последнюю песню)
— закрой музыку — закрыть ВСЕ открытые окна YouTube Music (и основное, и с треками)
— включи трек <название> / поставь трек <название> / найди трек <название> —
  найти конкретную песню в YouTube Music и сразу её включить
— геншин / genshin — запустить Genshin Impact
— назови любую игру из GAMES (кс2, ведьмак, киберпанк, гта, найн солс, таунскейпер,
  блэк дезерт, ассасин, неон вайт, resident evil village, дайинг лайт,
  меча хамелеон, синкинг сити, вольюм) — запустится через Steam
— майнкрафт / minecraft, призм / prism — запуск лаунчеров
— роблокс / roblox — открыть сайт Roblox
— стим / steam, закрой стим — запуск/закрытие Steam
— дискорд / discord, закрой дискорд — запуск/закрытие Discord
— телеграм / telegram, закрой телеграм — запуск/закрытие Telegram
— учёба — Chrome с учебным профилем
— пара / занятие / урок — Google Classroom
— фильм / кино — rezka.ag
— аниме — yummyani.me
— гитхаб / github — github.com
— комплектующие — ek.ua
— закрой браузер — закрыть все окна Chrome
— открой <сайт> — открыть сайт из списка (браузер, гугл, ютуб, клод и т.д.)
— запиши <текст> / заметка <текст> — сохранить заметку
— что ты умеешь / список команд — показать этот список
— голос — включить/выключить голосовые ответы (текст и попапы остаются всегда)
— огуречный салат — пауза, банановые кокосы — возобновление"""


speaking_event = threading.Event()


def speak(text: str) -> None:
    """Озвучивает текст через pyttsx3 (офлайн-TTS), в отдельном потоке,
    чтобы не блокировать прослушивание микрофона."""
    if pyttsx3 is None:
        return

    def _speak():
        speaking_event.set()  # "не слушай, я говорю" — иначе Джарвис услышит сам себя
        try:
            engine = pyttsx3.init()
            if VOICE_ID:
                engine.setProperty("voice", VOICE_ID)
            engine.setProperty("rate", 175)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            print(f"Ошибка озвучки: {e}")
        finally:
            time.sleep(0.4)  # даём эху в комнате затихнуть перед тем как снова слушать
            speaking_event.clear()

    threading.Thread(target=_speak, daemon=True).start()


def notify(message: str, ok: bool = True, duration_ms: int = 2000, force_speak: bool = False) -> None:
    """Маленькое всплывающее окно в правом нижнем углу на ~2 секунды +
    голосовой ответ через speak() (если voice_enabled, либо force_speak=True).
    ok=True — успешная команда (зеленоватый акцент), ok=False — неудачная (красноватый).
    Работает в отдельном потоке, чтобы не блокировать прослушивание микрофона.
    """

    def _show():
        bg = "#1f3d2b" if ok else "#3d1f1f"
        root = tk.Tk()
        root.overrideredirect(True)  # без рамки и заголовка окна
        root.attributes("-topmost", True)
        root.configure(bg=bg)

        label = tk.Label(
            root,
            text=message,
            bg=bg,
            fg="#ffffff",
            font=("Segoe UI", 11),
            padx=16,
            pady=10,
            wraplength=320,
            justify="left",
        )
        label.pack()

        root.update_idletasks()
        width = root.winfo_width()
        height = root.winfo_height()
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = screen_w - width - 20
        y = screen_h - height - 60
        root.geometry(f"{width}x{height}+{x}+{y}")

        root.after(duration_ms, root.destroy)
        root.mainloop()

    # daemon=False, чтобы последнее уведомление (например, при выходе)
    # успело показаться, даже если основной поток уже дошёл до конца.
    threading.Thread(target=_show, daemon=False).start()
    if voice_enabled or force_speak:
        speak(message)


voice_enabled = True
r = sr.Recognizer()
notify("Джарвис слушает вас, господин.", ok=True)


def toggle_voice() -> None:
    global voice_enabled
    voice_enabled = not voice_enabled
    state = "включён" if voice_enabled else "выключен"
    # force_speak=True — подтверждение переключения звучит и показывается
    # в любом случае, даже если голос только что выключили.
    notify(f"Голосовой вывод {state}.", ok=True, force_speak=True)


def open_site(name: str) -> None:
    url = SITES.get(name)
    if url:
        subprocess.Popen(MAIN_PROFILE_APP + [url])
        notify(f"Открываю {name}.", ok=True)
    else:
        notify(f"Сайт «{name}» не в списке разрешённых — не открываю.", ok=False)


def open_url(url: str, label: str) -> None:
    subprocess.Popen(MAIN_PROFILE_APP + [url])
    notify(f"Открываю {label}.", ok=True)


def launch_app(path: str, name: str) -> None:
    try:
        os.startfile(path)
        notify(f"Запускаю {name}.", ok=True)
    except FileNotFoundError:
        notify(f"Не нашёл {name} по пути «{path}» — проверь путь.", ok=False)


def _find_all_windows_by_title_substring(substring: str):
    """Возвращает список ВСЕХ видимых окон верхнего уровня, в заголовке
    которых встречается substring (регистронезависимо)."""
    substring_lower = substring.lower()
    result = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if substring_lower in title.lower():
                result.append(hwnd)
        return True

    win32gui.EnumWindows(callback, None)
    return result


def _find_window_by_title_substring(substring: str):
    """Ищет первое видимое окно верхнего уровня, в заголовке которого есть substring."""
    windows = _find_all_windows_by_title_substring(substring)
    return windows[0] if windows else None


def _wait_for_window(substring: str, timeout: float = 10.0, interval: float = 0.5):
    """Опрашивает список окон, пока не появится совпадение или не истечёт timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = _find_window_by_title_substring(substring)
        if hwnd:
            return hwnd
        time.sleep(interval)
    return None


def _resume_last_track() -> None:
    """Дожидается окна YouTube Music и жмёт пробел, чтобы продолжить последний трек.
    Из-за политики автовоспроизведения Chrome сайт почти всегда открывается на паузе
    с уже восстановленным треком/очередью — так что пробел практически гарантированно
    ЗАПУСКАЕТ воспроизведение, а не ставит его на паузу."""
    hwnd = _wait_for_window(YT_MUSIC_WINDOW_TITLE, timeout=10)
    if not hwnd:
        print("[YouTube Music] окно не появилось за 10 секунд — не могу нажать play.")
        return
    print(f"[YouTube Music] окно найдено: «{win32gui.GetWindowText(hwnd)}» (hwnd={hwnd})")
    try:
        win32gui.SetForegroundWindow(hwnd)
        print("[YouTube Music] SetForegroundWindow выполнен без ошибок.")
    except Exception as e:
        print(f"[YouTube Music] SetForegroundWindow упал: {e}")
    time.sleep(0.3)
    active_hwnd = win32gui.GetForegroundWindow()
    active_title = win32gui.GetWindowText(active_hwnd)
    print(f"[YouTube Music] активное окно перед нажатием пробела: «{active_title}»")
    pyautogui.press("space")


def open_music() -> None:
    try:
        subprocess.Popen(YT_MUSIC_APP)
        notify("Открываю YouTube Music.", ok=True)

    except FileNotFoundError:
        notify("Не нашёл chrome_proxy.exe — проверь путь.", ok=False)


# --- Поиск и запуск конкретного трека -------------------------------------
#
# Идея: искать трек через неофициальный API YouTube Music (ytmusicapi),
# который умеет искать без авторизации (см. документацию проекта:
# "Unauthenticated requests for retrieving playlist content or searching").
# Получаем videoId лучшего совпадения и открываем прямую ссылку
# https://music.youtube.com/watch?v=<id> в отдельном "app-режиме" Chrome
# (флаг --app=<url>, а не --app-id, поскольку --app-id открывает только
# зафиксированный стартовый URL установленного PWA и не годится для
# произвольного videoId).
#
# Установка: pip install ytmusicapi
#
# ВАЖНО для сборки в .exe (PyInstaller / auto-py-to-exe): ytmusicapi хранит
# файлы переводов (.mo) в папке ytmusicapi/locales внутри самого пакета —
# это данные, а не код, и PyInstaller их САМ НЕ подхватывает. Если после
# сборки .exe поиск треков перестал работать (а как .py-скрипт работал) —
# почти наверняка дело в этом. Решение — при сборке добавить сбор данных
# пакета, см. инструкцию в конце файла / в чате.

_ytmusic_client = None


def _log_error(context: str, exc: Exception) -> None:
    """Пишет traceback ошибки в файл-лог. Нужно на случай, если .exe собран
    в режиме "Window Based" (без консоли) — тогда print() никто не увидит,
    а лог-файл останется и его можно будет открыть и прочитать."""
    import traceback

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{context}] {exc}"
    print(line)
    try:
        os.makedirs(os.path.dirname(ERROR_LOG_PATH), exist_ok=True)
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {context}\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            f.write("\n")
    except Exception:
        pass  # даже если лог не записать — не роняем поток из-за этого


def _get_ytmusic_client():
    """Ленивая инициализация клиента ytmusicapi (без авторизации,
    только для публичного поиска). Раньше YTMusic() создавался ВНЕ
    try/except — если конструктор падал (например, из-за недостающих
    файлов локализации в собранном .exe), исключение вылетало в фоновом
    потоке никем не пойманным и просто "тихо" всё ломало."""
    global _ytmusic_client
    if YTMusic is None:
        return None
    if _ytmusic_client is None:
        try:
            _ytmusic_client = YTMusic()
        except Exception as e:
            _log_error("Инициализация YTMusic()", e)
            return None
    return _ytmusic_client


def _find_track_video_id(query: str):
    """Возвращает videoId первого подходящего результата поиска
    или None, если ничего не нашлось / клиент недоступен."""
    yt = _get_ytmusic_client()
    if yt is None:
        return None
    try:
        results = yt.search(query, filter="songs", limit=5)
        if not results:
            results = yt.search(query, filter="videos", limit=5)
        return results[0]["videoId"] if results else None
    except Exception as e:
        _log_error("Поиск трека в YouTube Music", e)
        return None


def play_track(query: str) -> None:
    """Ищет конкретный трек по названию и сразу включает его."""

    def _worker():
        if YTMusic is None:
            notify(
                "Поиск треков недоступен: не установлен пакет ytmusicapi "
                "(выполни pip install ytmusicapi).",
                ok=False,
            )
            return

        notify(f"Ищу трек «{query}»…", ok=True)
        video_id = _find_track_video_id(query)
        if not video_id:
            notify(f"Не нашёл трек «{query}».", ok=False)
            return

        url = f"https://music.youtube.com/watch?v={video_id}"
        subprocess.Popen(MAIN_PROFILE_APP + [f"--app={url}"])
        notify(f"Включаю «{query}».", ok=True)
        # Подстраховка на случай, если автовоспроизведение не сработает
        # (та же логика и тот же риск, что и в _resume_last_track: если
        # видео и так уже начало играть само, пробел его поставит на паузу).
        threading.Thread(target=_resume_last_track, daemon=True).start()

    threading.Thread(target=_worker, daemon=True).start()


def close_music_windows() -> None:
    """Закрывает ВСЕ открытые окна YouTube Music — и основное PWA-окно
    («музыка»), и окна с конкретными треками, открытые через play_track():
    у всех у них в заголовке присутствует YT_MUSIC_WINDOW_TITLE.

    Закрываем через WM_CLOSE (PostMessage), а не taskkill по имени процесса —
    иначе заодно прибило бы и обычные окна Chrome с браузером/учёбой, которые
    тоже работают через chrome.exe."""
    windows = _find_all_windows_by_title_substring(YT_MUSIC_WINDOW_TITLE)
    if not windows:
        notify("Окна YouTube Music не найдены — закрывать нечего.", ok=False)
        return

    closed = 0
    for hwnd in windows:
        try:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            closed += 1
        except Exception as e:
            print(f"[Закрытие музыки] Не удалось закрыть окно {hwnd}: {e}")

    if closed:
        word = "окно" if closed == 1 else "окна" if closed < 5 else "окон"
        notify(f"Закрываю {closed} музыкальных {word}.", ok=True)
    else:
        notify("Не удалось закрыть окна YouTube Music.", ok=False)


# ---------------------------------------------------------------------------


def open_study_profile() -> None:
    try:
        subprocess.Popen(STUDY_PROFILE_APP)
        notify("Открываю Chrome с учебным профилем.", ok=True)
    except FileNotFoundError:
        notify("Не нашёл chrome.exe — проверь путь.", ok=False)


def close_app(process_name: str, display_name: str) -> None:
    result = os.system(f"taskkill /IM {process_name} /F")
    if result == 0:
        notify(f"Закрываю {display_name}.", ok=True)
    else:
        notify(f"Не удалось закрыть {display_name} (код возврата: {result}).", ok=False)


def close_discord() -> None:
    # У Discord есть фоновый процесс-нянька Update.exe (Squirrel.Windows),
    # который следит за Discord.exe и почти мгновенно перезапускает его,
    # если он исчезает. Поэтому сначала гасим "няньку", а уже потом сам Discord —
    # иначе она успеет поднять его заново между двумя командами.
    os.system("taskkill /IM Update.exe /F")
    result = os.system("taskkill /IM Discord.exe /F")
    if result == 0:
        notify("Закрываю Discord.", ok=True)
    else:
        notify(f"Не удалось закрыть Discord (код возврата: {result}).", ok=False)


def launch_game() -> None:
    # os.system буквально выполняет команду через cmd.exe,
    # как если бы ты сам её вписал в терминал.
    result = os.system('schtasks /run /tn "GenshinLaunch"')
    if result == 0:
        notify("Запускаю Genshin Impact.", ok=True)
    else:
        notify(f"Не удалось запустить задачу GenshinLaunch (код возврата: {result}).", ok=False)


def launch_steam_game(key: str) -> None:
    appid = GAMES.get(key)
    if appid:
        os.startfile(f"steam://rungameid/{appid}")
        notify(f"Запускаю {key}.", ok=True)
    else:
        notify(f"Игра «{key}» не настроена.", ok=False)


def save_note(text: str) -> None:
    trigger = "запиши" if "запиши" in text else "заметк"
    note = text.split(trigger, 1)[-1].strip()
    if not note:
        notify("Не расслышал, что записать.", ok=False)
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(NOTES_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {note}\n")
    notify(f"Записал: {note}", ok=True)

def shutdown_system() -> None:
    result = os.system("shutdown /s /t 0")
    if result == 0:
        notify("Выключаю.", ok=True)
    else:
        notify(f"Не удалось выключить систему (код возврата: {result}).", ok=False)

def restart_system() -> None:
    result = os.system("shutdown /r /t 0")
    if result == 0:
        notify("Перезагружаю.", ok=True)
    else:
        notify(f"Не удалось перезагрузить систему (код возврата: {result}).", ok=False)

STOP_PHRASE = "огуречный салат"
RESUME_PHRASE = "банановые кокосы"
WORK_PHRASE = "скоро урок"
ENJOY_PHRASE = "время игр"

enjoing = True
listening = True

while True:
    try:
        if speaking_event.is_set():
            time.sleep(0.1)
            continue

        with sr.Microphone() as source:
            audio = r.listen(source)
            try:
                text = r.recognize_google(audio, language="ru-RU").lower()
                print(f"Вы сказали: {text}")

                # Пока на паузе — реагируем только на стоп-слово для возобновления,
                # остальные команды игнорируем полностью.
                if not listening:
                    if RESUME_PHRASE in text:
                        listening = True
                        notify("Джарвис снова слушает команды.", ok=True)
                    continue

                if STOP_PHRASE in text:
                    listening = False
                    notify(f"Джарвис на паузе. Скажите «{RESUME_PHRASE}», чтобы возобновить.", ok=True)
                    continue
                
                if WORK_PHRASE in text:
                    enjoing = False
                    notify("Включаю учебный режим.", ok=True)

                if ENJOY_PHRASE in text:
                    enjoing = True
                    notify("Включаю игровой режим.", ok=True)

                if "выход" in text:
                    notify("Выход из программы.", ok=True)
                    break
                
                elif "выключ" in text and ("пк" in text or "компьютер" in text) and enjoing:
                    shutdown_system()

                elif "перезагруз" in text and ("пк" in text or "компьютер" in text) and enjoing:
                    restart_system()

                elif "запиши" in text or "заметк" in text:
                    save_note(text)

                elif "что ты умеешь" in text or "список команд" in text or text.strip() == "помощь":
                    print(COMMANDS_LIST)
                    notify("Все команды я вывел в консоль.", ok=True)

                elif "голос" in text and enjoing:
                    toggle_voice()

                elif "музык" in text and "закр" in text:
                    # Проверяем ДО открытия музыки, иначе "закрой музыку"
                    # перехватилось бы веткой ниже и просто открыло бы новую.
                    close_music_windows()

                elif "музык" in text:
                    open_music()

                elif (trig := next((t for t in TRACK_TRIGGERS if t in text), None)) is not None:
                    # ВАЖНО: эта ветка должна идти раньше проверки "песн" in text —
                    # иначе "поставь песню Californication" перехватится веткой
                    # продолжения последнего трека, так и не дойдя до поиска.
                    query = text.split(trig, 1)[-1].strip()
                    if query:
                        play_track(query)
                    else:
                        notify("Не расслышал название трека.", ok=False)

                elif "песн" in text:
                    threading.Thread(target=_resume_last_track, daemon=True).start()

                elif "геншин" in text or "genshin" in text and enjoing:
                    launch_game()

                elif (game_key := next((k for k in GAMES if k in text), None)) is not None:
                    launch_steam_game(game_key)

                elif "майнкрафт" in text or "minecraft" in text and enjoing:
                    launch_app(MINECRAFT_LAUNCHER_PATH, "Minecraft")

                elif "призм" in text or "prism" in text and enjoing:
                    launch_app(PRISM_LAUNCHER_PATH, "Prism Launcher")

                elif ("роблокс" in text or "roblox" in text) and enjoing:
                    open_url(ROBLOX_URL, "Roblox")

                elif ("логик" in text or "logik" in text) and enjoing:
                    open_url(LOGIKA_URL , "Logika Backoffice")

                elif "стим" in text and "закр" in text:
                    close_app("steam.exe", "Steam")

                elif "steam" in text and "закр" in text:
                    close_app("steam.exe", "Steam")

                elif "стим" in text or "steam" in text and enjoing:
                    launch_app(STEAM_PATH, "Steam")

                elif "дискорд" in text and "закр" in text:
                    close_discord()

                elif "discord" in text and "закр" in text:
                    close_discord()

                elif "дискорд" in text or "discord" in text and enjoing:
                    launch_app(DISCORD_PATH, "Discord")

                elif "телеграм" in text and "закр" in text:
                    close_app("Telegram.exe", "Telegram")

                elif "telegram" in text and "закр" in text:
                    close_app("Telegram.exe", "Telegram")

                elif "телеграм" in text or "telegram" in text:
                    launch_app(TELEGRAM_PATH, "Telegram")

                elif "учеб" in text:
                    open_study_profile()

                elif "пара" in text in text or "на пару" in text:
                    subprocess.Popen(STUDY_PROFILE_APP + [CLASSROOM_URL])
                    notify("Открываю Google Classroom в учебном профиле.", ok=True)

                elif "фильм" in text or "кино" in text and enjoing:
                    open_url(FILMS_URL, "фильмы")

                elif "аниме" in text and enjoing:
                    open_url(ANIME_URL, "аниме")

                elif "гитхаб" in text or "github" in text:
                    open_url(GITHUB_URL, "GitHub")

                elif "комплектующ" in text:
                    open_url(PARTS_URL, "комплектующие")

                elif "браузер" in text and "закр" in text:
                    close_app("chrome.exe", "браузер")

                elif "открой" in text:
                    requested = text.split("открой")[-1].strip()
                    matched = next((key for key in SITES if key in requested), None)
                    if matched:
                        open_site(matched)
                    else:
                        notify(f"Сайт «{requested}» не в списке разрешённых — не открываю.", ok=False)

            except sr.UnknownValueError:
                pass  # спокойно слушаем дальше, если был просто шум
            except sr.RequestError as e:
                notify(f"Ошибка сервиса распознавания речи!", ok=False)
    except Exception as e:
        notify(f"Ошибка!", ok=False)
        time.sleep(1)  # небольшая пауза перед повторной попыткой