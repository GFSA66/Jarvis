import os
import sys
import threading
import tkinter as tk
import subprocess

try:
    import pyaudiowpatch as pyaudio
    sys.modules['pyaudio'] = pyaudio
except ImportError:
    pass

import speech_recognition as sr


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

YT_MUSIC_APP = [
    r"C:\Program Files\Google\Chrome\Application\chrome_proxy.exe",
    "--profile-directory=Default",
    "--app-id=cinhimbnkkaeohfgghhklpknlkffjgod",
]

STUDY_PROFILE_APP = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "--profile-directory=Profile 2",
]

MAIN_PROFILE_APP = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "--profile-directory=Default",
]

CLASSROOM_URL = "https://classroom.google.com/c/ODc2MTc3NTI3Mzg5"


def notify(message: str, ok: bool = True, duration_ms: int = 2000) -> None:
    """Маленькое всплывающее окно в правом нижнем углу на ~2 секунды.
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


r = sr.Recognizer()
notify("Джарвис слушает вас, господин ...", ok=True)


def open_site(name: str) -> None:
    url = SITES.get(name)
    if url:
        subprocess.Popen(MAIN_PROFILE_APP + [url])
        notify(f"Открываю: {url}", ok=True)
    else:
        notify(f"Сайт «{name}» не в списке разрешённых — не открываю.", ok=False)


def launch_app(path: str, name: str) -> None:
    try:
        os.startfile(path)
        notify(f"Запускаю {name}.", ok=True)
    except FileNotFoundError:
        notify(f"Не нашёл {name} по пути «{path}» — проверь путь.", ok=False)


def open_music() -> None:
    try:
        subprocess.Popen(YT_MUSIC_APP)
        notify("Открываю YouTube Music.", ok=True)
    except FileNotFoundError:
        notify("Не нашёл chrome_proxy.exe — проверь путь.", ok=False)


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


STOP_PHRASE = "огуречный салат"
RESUME_PHRASE = "банановые кокосы"

listening = True

while True:
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

            if "выход" in text:
                notify("Выход из программы.", ok=True)
                break

            elif "музык" in text:
                open_music()

            elif "геншин" in text or "genshin" in text:
                launch_game()

            elif "стим" in text and "закр" in text:
                close_app("steam.exe", "Steam")

            elif "steam" in text and "закр" in text:
                close_app("steam.exe", "Steam")

            elif "стим" in text or "steam" in text:
                launch_app(STEAM_PATH, "Steam")

            elif "дискорд" in text and "закр" in text:
                close_discord()

            elif "discord" in text and "закр" in text:
                close_discord()

            elif "дискорд" in text or "discord" in text:
                launch_app(DISCORD_PATH, "Discord")

            elif "учеб" in text:
                open_study_profile()

            elif "пара" in text or "занят" in text or "урок" in text:
                subprocess.Popen(STUDY_PROFILE_APP + [CLASSROOM_URL])
                notify("Открываю Google Classroom в учебном профиле.", ok=True)

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
            print(f"Ошибка сервиса распознавания речи: {e}")