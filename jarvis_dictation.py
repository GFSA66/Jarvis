"""Умная диктовка Джарвиса: чистка распознанной речи и вставка в активное окно.

Перехватывает сырую диктовку от Google Speech Recognition:
  - убирает слова-паразиты и самоповторы,
  - чинит типичные опечатки распознавания,
  - ставит знаки препинания по голосовым командам,
  - вставляет готовый текст в любое активное окно через буфер обмена.
"""
from __future__ import annotations

import ctypes
import os
import re
import time
from ctypes import wintypes

FILLERS = (
    "э", "э-э", "эээ", "а-а", "м-м", "ммм", "ну", "вот", "как бы", "типа",
    "это самое", "значит", "так сказать", "короче",
)

VOICE_MARKS = [
    ("восклицательный знак", "!"),
    ("вопросительный знак", "?"),
    ("точка с запятой", ";"),
    ("двоеточие", ":"),
    ("многоточие", "..."),
    ("открыть кавычки", "«"),
    ("закрыть кавычки", "»"),
    ("открыть скобку", "("),
    ("закрыть скобку", ")"),
    ("новый абзац", "\n\n"),
    ("новая строка", "\n"),
    ("точка", "."),
    ("запятая", ","),
    ("вопрос", "?"),
    ("тире", " — "),
    ("дефис", "-"),
    ("пробел", " "),
]

TYPO_FIX = {
    "што": "что", "щто": "что", "щас": "сейчас", "ща": "сейчас",
    "счаз": "сейчас", "канешна": "конечно", "канэшно": "конечно",
    "низзя": "нельзя", "низя": "нельзя", "чё": "что", "чо": "что",
    "зделать": "сделать", "зделаю": "сделаю", "зделаешь": "сделаешь",
    "зделает": "сделает", "зделаем": "сделаем", "зделаете": "сделаете",
    "зделают": "сделают", "зделал": "сделал", "зделала": "сделала",
    "зделали": "сделали", "зделано": "сделано",
    "вообщем": "в общем", "вобщем": "в общем",
    "извените": "извините", "превет": "привет", "пажалуйста": "пожалуйста",
    "пожайлуста": "пожалуйста", "спосибо": "спасибо", "харашо": "хорошо",
    "ето": "это", "када": "когда", "тада": "тогда", "вобще": "вообще",
}


def _apply_voice_marks(text: str) -> str:
    t = f" {text} "
    for phrase, mark in VOICE_MARKS:
        t = re.sub(r"\s+" + re.escape(phrase) + r"(?=[\s,.!?;:])",
                   " " + mark + " ", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+" + re.escape(phrase) + r"\s+", " " + mark + " ", t,
                   flags=re.IGNORECASE)
    return t.strip()


def _drop_fillers(text: str) -> str:
    t = f" {text} "
    for f in sorted(FILLERS, key=len, reverse=True):
        t = re.sub(r"\s+" + re.escape(f) + r"(?=[\s,.!?;:])", " ", t,
                   flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", t).strip()


def _fix_typos(text: str) -> str:
    def rep(m):
        word, fixed = m.group(0), TYPO_FIX[m.group(0).lower()]
        return fixed.capitalize() if word[:1].isupper() else fixed
    if not TYPO_FIX:
        return text
    pat = re.compile(r"\b(" + "|".join(map(re.escape, TYPO_FIX)) + r")\b",
                     flags=re.IGNORECASE)
    return pat.sub(rep, text)


def _spacing(text: str) -> str:
    t = re.sub(r"[ \t]+", " ", text).strip()
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r" +([,.!?;:%)])", r"\1", t)
    t = re.sub(r"([«\(]) +", r"\1", t)
    t = re.sub(r" *— *", " — ", t)
    t = re.sub(r" {2,}", " ", t)
    return t.strip()


def _capitalize(text: str) -> str:
    def cap(m):
        return m.group(1) + m.group(2).upper()
    # начало текста и начало предложений после . ! ? … и переносов
    t = re.sub(r"(^|[.!?…]\s+|\n+)([а-яёa-z])", cap, text)
    # одинокое «я» в начале предложения тоже с большой (остальные случаи — по правилу выше)
    t = re.sub(r"(^|[.!?…]\s+)я\b", lambda m: m.group(1) + "Я", t)
    return t


def cleanup(raw: str) -> str:
    """Сырая диктовка -> готовый текст со знаками препинания."""
    if not (raw or "").strip():
        return ""
    t = raw.strip().lower()
    t = _apply_voice_marks(t)
    t = _drop_fillers(t)
    t = _fix_typos(t)
    t = _spacing(t)
    t = _capitalize(t)
    return t.strip(" ,")


# сколько ждать перед Ctrl+V после установки буфера (сек): малое значение на
# медленных окнах (браузер, Telegram) даёт «вставилось 2 символа». 0.6 по умолчанию.
DEFAULT_PASTE_DELAY = 0.6


def _ensure_en_layout() -> None:
    """Переключить раскладку на английскую для Ctrl+V.

    pyautogui.hotkey('ctrl', 'v') отправляет виртуальный код клавиши V (0x56) по
    SendInput: на русской раскладке этот код по-прежнему 0x56, но элемент управления
    (IME/языковая панель) может заменить комбинацию на Ctrl+М, и вставка не сработает.
    Поэтому принудительно активируем EN и перепроверяем (Alt+Shift / Win+Space),
    при необходимости — пару раз.
    """
    user32 = ctypes.windll.user32

    def fg_lang() -> int:
        """LCID раскладки активного окна — её и применит Ctrl+V."""
        fg = user32.GetForegroundWindow()
        tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        return int(user32.GetKeyboardLayout(tid)) & 0xFFFF

    try:
        user32.LoadKeyboardLayoutW("00000409", 1)
    except Exception:
        pass
    try:
        user32.ActivateKeyboardLayout(0x04090409, 0)  # раскладка текущего потока
    except Exception:
        pass
    if fg_lang() == 0x0409:
        return
    # Переключение целевого окна хоткеем: Alt+Shift, затем Win+Space (проверяем результат)
    KEYUP = 0x0002
    for mod, key in ((0x12, 0x10), (0x5B, 0x20)):
        if fg_lang() == 0x0409:
            return
        try:
            user32.keybd_event(mod, 0, 0, 0)        # модификатор вниз
            user32.keybd_event(key, 0, 0, 0)         # клавиша вниз
            user32.keybd_event(key, 0, KEYUP, 0)     # клавиша вверх
            user32.keybd_event(mod, 0, KEYUP, 0)     # модификатор вверх
            time.sleep(0.25)
        except Exception:
            break
    time.sleep(0.1)


_JARVIS_PID = os.getpid()
_REMEMBERED_HWND = 0


def _window_pid(hwnd: int) -> int:
    try:
        user32 = ctypes.windll.user32
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def _is_own_window(hwnd: int) -> bool:
    """Окно принадлежит самому Джарвису (консоль / настройки) — не цель."""
    if not hwnd:
        return True
    try:
        if hwnd == int(ctypes.windll.kernel32.GetConsoleWindow() or 0):
            return True
    except Exception:
        pass
    if _window_pid(hwnd) == _JARVIS_PID and _JARVIS_PID:
        return True
    t = _window_title(hwnd).lower()
    for bad in ("jarvis", "джарвис", "settings", "настройки джарвиса"):
        if bad in t:
            return True
    try:
        cls = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(int(hwnd), cls, 256)
        c = cls.value or ""
        if c in ("ConsoleWindowClass",):
            # чужая консоль — тоже не лучшая цель, но своя — точно нет
            if _window_pid(hwnd) == _JARVIS_PID:
                return True
    except Exception:
        pass
    return False


def _window_title(hwnd: int) -> str:
    """Заголовок окна (пусто, если окно без заголовка — служебное окно/всплывашка)."""
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(int(hwnd), buf, 512)
    return buf.value


# окна-оболочка Windows: рабочий стол, панель задач и т.п. — не получатели вставки
_SHELL_CLASSES = frozenset({
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "NotifyIconOverflowWindow", "Windows.UI.Core.CoreWindow", "DV2ControlHost",
    "GDI+ Hook Window Class", "MediaPlayer SMTC window - {818281FB-E9BF-46AD-A7ED-5692A57E4675}",
    "MediaPlayer SMTC window - {D212EB6A-747A-4E31-9D79-BB0464E670D0}",
    "TtkMonitorClass", "PyInstallerOnefileHiddenWindow", "COMTASKSWINDOWCLASS",
    "OperationStatusWindow", "WUIconClass", "Static",
})


def _is_target_window(hwnd: int, own_ok: bool = True) -> bool:
    """Обычное окно приложения: видимое, с заголовком, не окно оболочки Windows.

    own_ok=False — дополнительно исключить окна самого Джарвиса (уведомления,
    консоль, настройки): автовыбор не должен вставлять сам в себя.
    """
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
        return False
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    cls = buf.value or ""
    if cls in _SHELL_CLASSES:
        return False
    if "GDI+" in cls or "Hook Window" in cls:
        return False
    if cls.startswith("Qt51515QWindowToolTip") or cls.startswith("Qt51515QWindowPopup"):
        return False
    if cls.startswith("HwndWrapper["):
        return False
    if not _window_title(hwnd).strip():
        return False  # без заголовка — служебное окно либо всплывашка уведомления
    if not own_ok and _is_own_window(hwnd):
        return False
    return True


def _enum_z() -> list[int]:
    """Все top-level окна в Z-порядке: сверху (самое новое) вниз."""
    out: list[int] = []
    user32 = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        out.append(int(hwnd))
        return True

    try:
        user32.EnumWindows(cb, 0)
    except Exception:
        pass
    return out


def pick_target_window() -> int | None:
    """Окно-получатель вставки.

    Если пользователь уже выбрал окно (на переднем плане обычное окно приложения) —
    возвращаем его. Иначе (рабочий стол, панель задач, всплывашка самого Джарвиса) —
    сама выбирает ближайшее обычное окно в Z-порядке: обычно это то окно,
    которое было активно последним.
    """
    user32 = ctypes.windll.user32
    global _REMEMBERED_HWND
    fg = int(user32.GetForegroundWindow() or 0)
    if _is_target_window(fg, own_ok=False):
        _REMEMBERED_HWND = fg
        return fg
    if _REMEMBERED_HWND and _is_target_window(_REMEMBERED_HWND, own_ok=False):
        return _REMEMBERED_HWND
    for hwnd in _enum_z():
        if _is_target_window(hwnd, own_ok=False) and not user32.IsIconic(hwnd):
            _REMEMBERED_HWND = hwnd
            return hwnd
    for hwnd in _enum_z():  # всё свёрнуто — берём ближайшее, развернём при активации
        if _is_target_window(hwnd, own_ok=False):
            _REMEMBERED_HWND = hwnd
            return hwnd
    return fg or None


def activate_window(hwnd: int) -> bool:
    """Вывести окно на передний план (развернуть, если свёрнуто)."""
    import pyautogui

    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        for _ in range(3):
            if int(user32.GetForegroundWindow() or 0) == hwnd:
                return True
            pyautogui.press("alt")  # Windows разрешает смену фокуса после «недавнего ввода»
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.2)
        if int(user32.GetForegroundWindow() or 0) != hwnd:
            user32.SwitchToThisWindow(hwnd, 1)  # запасной путь
            time.sleep(0.3)
    except Exception as e:
        print(f"[Диктовка] активация окна: {e}", flush=True)
    ok = int(user32.GetForegroundWindow() or 0) == hwnd
    if not ok:
        print(f"[Диктовка] фокус не получен: «{_window_title(hwnd)}»", flush=True)
    return ok


def _send_ctrl_v():
    import pyautogui
    try:
        u = ctypes.windll.user32
        u.keybd_event(0x11, 0, 0, 0)
        time.sleep(0.05)
        u.keybd_event(0x56, 0, 0, 0)
        time.sleep(0.05)
        u.keybd_event(0x56, 0, 0x0002, 0)
        time.sleep(0.03)
        u.keybd_event(0x11, 0, 0x0002, 0)
    except Exception:
        pyautogui.hotkey("ctrl", "v")


def type_into_active_window(text: str, end_space: bool = True,
                            paste_delay: float | None = None,
                            restore_clipboard: bool = True,
                            pre_delay: float = 0.0) -> None:
    """Вставить текст в активное окно через буфер обмена (Ctrl+V).

    Через clipboard — единственный надёжный способ для кириллицы
    (pyautogui.typewrite с русской раскладкой печатает кракозябры).

    pre_delay — пауза ДО вставки (дать кликнуть в нужное окно).
    paste_delay — пауза между set_clip и Ctrl+V (медленным окнам нужно больше;
        при малом значении вставляется только начало текста).
    restore_clipboard — вернуть старый буфер после вставки (с задержкой,
        чтобы окно успело забрать текст; иначе в буфере остаётся вставленное).
    """
    import pyautogui

    if not text:
        return
    if paste_delay is None:
        paste_delay = DEFAULT_PASTE_DELAY
    if pre_delay > 0:
        time.sleep(pre_delay)
    # Окно-получатель: пользователь мог выбрать его сам (клик за delay_sec),
    # а мог не выбрать — тогда берём ближайшее обычное окно сами и активируем,
    # чтобы Ctrl+V не улетел в рабочий стол / панель задач / всплывашку уведомления.
    target = pick_target_window()
    if target:
        activate_window(target)
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    # 64-битные handle'ы: без явных прототипов ctypes обрезает GlobalAlloc/GetClipboardData
    # до c_int и set_clip_str падает (нет вставки вообще)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalSize.argtypes = [wintypes.HANDLE]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
    kernel32.GlobalFree.restype = wintypes.HANDLE
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    def get_clip():
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
                return ctypes.string_at(p, kernel32.GlobalSize(h))
            finally:
                kernel32.GlobalUnlock(h)
        finally:
            user32.CloseClipboard()

    def set_clip_bytes(data: bytes) -> bool:
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

    def set_clip_str(s: str) -> bool:
        return set_clip_bytes(s.encode("utf-16-le") + b"\0\0")

    def set_clip_retry(s, tries=8):
        data = s.encode("utf-16-le") + b"\0\0"
        for _ in range(max(1, tries)):
            if set_clip_bytes(data):
                return True
            time.sleep(0.07)
        return False

    def clip_text():
        raw = get_clip()
        if not raw:
            return None
        try:
            return raw.decode("utf-16-le").rstrip(chr(0))
        except Exception:
            return None

    old = get_clip() if restore_clipboard else None
    try:
        if not set_clip_retry(text):
            print("clipboard busy, fallback typewrite", flush=True)
            if target:
                activate_window(target)
            pyautogui.typewrite(text, interval=0.005)
            return
        for _ in range(5):
            if clip_text() == text:
                break
            time.sleep(0.07)
            set_clip_retry(text, tries=1)
        time.sleep(max(0.1, float(paste_delay)))
        _ensure_en_layout()
        time.sleep(0.15)
        if target and int(user32.GetForegroundWindow() or 0) != target:
            activate_window(target)
        _send_ctrl_v()
        time.sleep(max(0.6, float(paste_delay)))
        if end_space and not text.endswith((" ", "\n")):
            pyautogui.press("space")
            time.sleep(0.1)
        time.sleep(0.6)
    finally:
        if restore_clipboard:
            if old is not None:
                for _ in range(5):
                    if set_clip_bytes(old):
                        break
                    time.sleep(0.07)
            elif user32.OpenClipboard(None):
                try:
                    user32.EmptyClipboard()
                finally:
                    user32.CloseClipboard()
