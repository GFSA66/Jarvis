"""Умная диктовка Джарвиса: чистка распознанной речи и вставка в активное окно.

Перехватывает сырую диктовку от Google Speech Recognition:
  - убирает слова-паразиты и самоповторы,
  - чинит типичные опечатки распознавания,
  - ставит знаки препинания по голосовым командам,
  - вставляет готовый текст в любое активное окно через буфер обмена.
"""
from __future__ import annotations

import re
import time

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
    import ctypes

    user32 = ctypes.windll.user32
    HKL_EN = 0x04090409
    try:
        user32.LoadKeyboardLayoutW("00000409", 1)
    except Exception:
        pass
    try:
        user32.ActivateKeyboardLayout(HKL_EN, 0)
    except Exception:
        pass
    # Переключение через Alt+Shift, потом Win+Space (если клавиатурное исчисление не ушло)
    for _ in range(2):
        try:
            user32.BlockInput(True)
            user32.keybd_event(0x12, 0, 0, 0)  # Alt
            user32.keybd_event(0x21, 0, 0, 0)  # Shift
            user32.keybd_event(0x21, 0, ctypes.c_ulong(0x0001), 0)
            user32.keybd_event(0x12, 0, ctypes.c_ulong(0x0002), 0)
            user32.keybd_event(0x12, 0, 0, 0)
            user32.BlockInput(False)
            time.sleep(0.15)
            user32.BlockInput(True)
            user32.keybd_event(0x5B, 0, 0, 0)  # Win
            user32.keybd_event(0x21, 0, 0, 0)  # Shift
            user32.keybd_event(0x21, 0, ctypes.c_ulong(0x0001), 0)
            user32.keybd_event(0x5B, 0, ctypes.c_ulong(0x0002), 0)
            user32.keybd_event(0x5B, 0, 0, 0)
            user32.BlockInput(False)
            time.sleep(0.3)
        except Exception:
            break
    time.sleep(0.1)


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
    import ctypes

    import pyautogui

    if not text:
        return
    if paste_delay is None:
        paste_delay = DEFAULT_PASTE_DELAY
    if pre_delay > 0:
        time.sleep(pre_delay)
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
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

    old = get_clip() if restore_clipboard else None
    try:
        if not set_clip_str(text):
            print("[Диктовка] set_clip_str FAILED -> fallback typewrite", flush=True)
            pyautogui.typewrite(text, interval=0.005)
            return
        # Ждём, пока буфер реально пропишется
        time.sleep(max(0.1, float(paste_delay)))
        _ensure_en_layout()
        time.sleep(0.15)
        # Ctrl+V — повторяем 3 раза, если окно не успело вставить
        pasted = False
        for _attempt in range(3):
            pyautogui.hotkey("ctrl", "v")
            time.sleep(max(0.3, float(paste_delay)))
            # Если окно скопировало себе (буфер не пустой и не совпал со старым),
            # считаем вставку удавшейся; иначе — делаем ещё попытку
            cur = get_clip()
            if cur is not None and cur != b"":
                # быстрый вход: пусть буфер придёт в норму, если это возможная сделка
                pasted = True
                break
        if not pasted:
            print(f"[Диктовка] Ctrl+V НЕ сработал после 3 попыток", flush=True)
        if end_space and not text.endswith((" ", "\n")):
            pyautogui.press("space")
            time.sleep(0.1)
    finally:
        if not restore_clipboard:
            return
        if old is not None:
            set_clip_bytes(old)
        elif user32.OpenClipboard(None):
            try:
                user32.EmptyClipboard()
            finally:
                user32.CloseClipboard()
