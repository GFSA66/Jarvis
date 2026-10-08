"""Чистая логика Джарвиса: числа, длительности, диктовка, кубики, история, бэкапы.

Здесь НЕТ Windows-импортов — модуль импортируется и тестируется на Linux:
    python -m pytest tests/
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

# ============================================================================
#  Числа словами (0–100)
# ============================================================================

_UNITS = {
    "ноль": 0, "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
    "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
    "девятнадцать": 19,
}
_TENS = {
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
    "сто": 100, "ста": 100,
}


def parse_number_ru(text: str) -> int | None:
    """«30», «тридцать», «сто», «два» -> число. Ищет первое число 0–100 в фразе."""
    if not text:
        return None
    t = text.lower().replace("ё", "е")
    digits = re.search(r"\b\d{1,3}\b", t)
    word_pos, word_val = None, None
    for word, val in {**_UNITS, **_TENS}.items():
        m2 = re.search(r"\b" + word + r"\b", t)
        if m2 and (word_pos is None or m2.start() < word_pos):
            word_pos, word_val = m2.start(), val
    if digits and (word_pos is None or digits.start() < word_pos):
        n = int(digits.group(0))
        if 0 <= n <= 100:
            return n
    if word_pos is not None:
        m4 = re.match(r"(\w+)\s+(\w+)", t[word_pos:])  # «двадцать пять» -> 25
        if m4 and m4.group(1) in _TENS and m4.group(2) in _UNITS:
            return _TENS[m4.group(1)] + _UNITS[m4.group(2)]
        return word_val
    if digits:
        n = int(digits.group(0))
        if 0 <= n <= 100:
            return n
    return None


# ============================================================================
#  Длительности: «пять минут», «полтора часа», «через час», «2 часа 15 минут»
# ============================================================================

_UNIT_SECONDS = {
    "сек": 1, "секунд": 1, "секунду": 1, "секунды": 1,
    "мин": 60, "минут": 60, "минуту": 60, "минуты": 60,
    "ч": 3600, "час": 3600, "часа": 3600, "часов": 3600, "часу": 3600,
    "день": 86400, "дня": 86400, "дней": 86400,
}
_WORD_NUM = {**_UNITS, **_TENS, "полтора": 1.5, "полторы": 1.5}


def _num_before(words: list[str], idx: int) -> float | None:
    """Число (цифрой или словом) непосредственно перед words[idx]."""
    if idx == 0:
        return None
    prev = words[idx - 1]
    if prev.replace(".", "", 1).isdigit():
        return float(int(float(prev)))
    if prev in _WORD_NUM:
        val = _WORD_NUM[prev]
        if idx >= 2 and words[idx - 2] in _TENS and val < 100:
            return float(_TENS[words[idx - 2]] + int(val))
        return float(val)
    return None


def parse_duration_ru(text: str) -> int | None:
    """«5 минут» -> 300; «полтора часа» -> 5400; «полчаса» -> 1800;
    «через час» -> 3600; «2 часа 15 минут» -> 8100. Суммирует все куски.
    Возвращает секунды или None, если длительности нет."""
    if not text:
        return None
    t = text.lower().replace("ё", "е")
    total = 0.0
    found = False
    m = re.search(r"\bпол\s?часа\b", t)
    if m:
        total += 1800
        found = True
        t = t[:m.start()] + " " + t[m.end():]
    words = re.findall(r"[\d.]+|[^\s.,;:!?]+", t)
    i = 0
    while i < len(words):
        w = words[i]
        if w in _UNIT_SECONDS:
            unit_idx = i
        elif i + 1 < len(words) and words[i + 1] in _UNIT_SECONDS and w in _WORD_NUM:
            unit_idx = i + 1  # «пять минут» — единица после числа
        else:
            i += 1
            continue
        n = float(_WORD_NUM[w]) if unit_idx == i + 1 else _num_before(words, unit_idx)
        if n is None:
            n = 1.0  # «через час», «через минуту» — единица без числа = 1
        total += n * _UNIT_SECONDS[words[unit_idx]]
        found = True
        i = unit_idx + 1
    if not found:
        return None
    return int(total) if total > 0 else None


def parse_clock_ru(text: str) -> str | None:
    """«в 20:30», «в 9 утра» -> «20:30» / «09:00» (ЧЧ:ММ) или None."""
    if not text:
        return None
    t = text.lower().replace("ё", "е")
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"
        return None
    m = re.search(r"\bв\s+(\d{1,2})\b(?:\s*(утра|вечера|вечерем|утром|дня|днём|ночи))?", t)
    if m:
        h = int(m.group(1))
        part = m.group(2) or ""
        if part in ("вечера", "вечерем", "дня", "днём") and h < 12:
            h += 12
        if part == "ночи" and 12 <= h <= 16:
            h -= 12
        if 0 <= h <= 23:
            return f"{h:02d}:00"
    return None


# ============================================================================
#  Диктовка: голосовые знаки и правки (чистая логика)
# ============================================================================

# (слова, вставка). Порядок важен: длинные фразы первыми.
DICTATION_MARKS: tuple[tuple[str, str], ...] = (
    ("восклицательный знак", "!"),
    ("вопросительный знак", "?"),
    ("точка с запятой", ";"),
    ("многоточие", "..."),
    ("открывающая кавычка", "«"),
    ("закрывающая кавычка", "»"),
    ("открывается скобка", "("),
    ("закрывается скобка", ")"),
    ("открывающая скобка", "("),
    ("закрывающая скобка", ")"),
    ("скобка открывается", "("),
    ("скобка закрывается", ")"),
    ("новый абзац", "\n\n"),
    ("новая строка", "\n"),
    ("двоеточие", ":"),
    ("кавычки", "\""),
    ("тире", " — "),
    ("дефис", "-"),
    ("запятая", ","),
    ("кавычка", "\""),
    ("точка", "."),
    ("пробел", " "),
)
# команды-правки (не вставляют текст, а меняют уже введённое)
DICTATION_DELETE_LAST_WORD = ("удали последнее слово", "сотри последнее слово",
                              "убери последнее слово", "удали слово")
DICTATION_DELETE_LAST_SENTENCE = ("удали последнюю фразу", "сотри последнюю фразу",
                                 "удали фразу", "убери последнюю фразу")
DICTATION_CANCEL = ("отмени ввод", "отменить ввод", "сотри всё", "очисти ввод")


def _capitalize_after(text: str) -> str:
    """Заглавная буква после . ! ? и в начале текста, после перевода строки."""
    def cap(m: re.Match) -> str:
        return m.group(1) + m.group(2).upper()
    return re.sub(r"(^|[.!?…]\s+|\n\s*)([а-яёa-z])", cap, text)


def _spacing(text: str) -> str:
    """Пробел после знаков препинания, без пробела перед ними."""
    t = re.sub(r"[ \t]+", " ", text)
    t = re.sub(r" *(\n) *", r"\1", t)
    t = re.sub(r" +([,.!?;:%)])", r"\1", t)
    t = re.sub(r"([«(\"])( +)", r"\1", t)
    t = re.sub(r"([.!?,:;])([^\s\n\d])", r"\1 \2", t)  # «привет.как» -> «привет. как»
    t = re.sub(r"(?<![.!?…]) {2,}", " ", t)
    return t


def apply_dictation_commands(text: str, buffer: str = "",
                             autoformat: bool = True) -> tuple[str, str, int]:
    """Применить голосовые знаки/правки к фразе диктовки.

    Возвращает (фраза_для_ввода, новый_буфер, стереть_символов):
      - delete_count > 0 — сначала нажать Backspace столько раз;
      - фраза_для_ввода — что ввести после стирания (может быть "");
      - буфер — весь ожидаемый текст после ввода (для отмены и удалений).
    buffer — текст, уже введённый в этой сессии диктовки.
    """
    raw = (text or "").strip()
    if not raw:
        return "", buffer, 0
    low = raw.lower().replace("ё", "е").rstrip(".!?")
    # отмена всего введённого
    if low in DICTATION_CANCEL:
        return "", "", len(buffer)
    # удаление последнего слова
    if any(low.startswith(c) for c in DICTATION_DELETE_LAST_WORD):
        stripped = buffer.rstrip()
        if stripped:
            last = stripped.rsplit(" ", 1)[-1]
            new_buf = stripped[:len(stripped) - len(last)].rstrip(" ")
            result = new_buf + " " if new_buf else ""
            return "", result, len(buffer) - len(result)
        return "", buffer, 0
    # удаление последней фразы (последнего куска до . ! ? \n)
    if any(low.startswith(c) for c in DICTATION_DELETE_LAST_SENTENCE):
        stripped = buffer.rstrip()
        m = re.search(r"(?:^|[.!?…\n])\s*([^.!?…\n]*)$", stripped)
        if m and m.group(1).strip():
            cut_from = m.start(1)
            return "", buffer[:cut_from], len(buffer) - cut_from
        return "", "", len(buffer)
    # голосовые знаки — заменяем фразы внутри текста
    out = f" {raw} "
    for phrase, mark in DICTATION_MARKS:
        out = re.sub(r"\s+" + re.escape(phrase) + r"(?=[\s,.!?;:]|$)", " " + mark + " ", out,
                     flags=re.IGNORECASE)
    out = re.sub(r"[ \t]{2,}", " ", out).strip(" \t")  # переносы строк сохраняем
    if not out:
        return "", buffer, 0
    # склейка с предыдущим вводом
    if buffer:
        if out[0] in "\n.," or out[0] in "!?;:%)»":
            joined = buffer.rstrip(" ") + out
        elif buffer.endswith("\n"):
            joined = buffer + out
        else:
            joined = buffer + " " + out
    else:
        joined = out
    if autoformat:
        joined = _spacing(joined)
        joined = _capitalize_after(joined)
    if joined.startswith(buffer):
        return joined[len(buffer):], joined, 0
    # автоформат изменил уже введённое — переписываем буфер целиком
    return joined, joined, len(buffer)


# ============================================================================
#  Кубики и монетка
# ============================================================================

MAX_DICE = 100
MAX_FACES = 1000


def roll_dice(expr: str) -> dict:
    """«d20», «4d6», «d6 плюс 3», «d6+3» -> {total, rolls, mod, detail}.

    Лимиты: до 100 кубиков, до 1000 граней. ValueError — с непонятной формулой.
    """
    t = (expr or "").lower().replace("ё", "е").strip()
    t = re.sub(r"\s+", "", t)
    t = t.replace("плюс", "+").replace("минус", "-")
    m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", t)
    if not m:
        raise ValueError(f"не понял формулу «{expr}»: нужно вроде d20, 4d6, d6+3")
    count = int(m.group(1)) if m.group(1) else 1
    faces = int(m.group(2))
    mod = int(m.group(3)) if m.group(3) else 0
    if count < 1 or count > MAX_DICE:
        raise ValueError(f"кубиков можно от 1 до {MAX_DICE}")
    if faces < 2 or faces > MAX_FACES:
        raise ValueError(f"граней можно от 2 до {MAX_FACES}")
    import random
    rolls = [random.randint(1, faces) for _ in range(count)]
    total = sum(rolls) + mod
    detail = f"{count}d{faces}" + (f"{mod:+d}" if mod else "")
    return {"total": total, "rolls": rolls, "mod": mod, "detail": detail}


def flip_coin() -> str:
    """«орёл» / «решка»."""
    import random
    return random.choice(("орёл", "решка"))


# ============================================================================
#  История (JSONL) и бэкапы: ротация
# ============================================================================

def trim_jsonl_lines(lines: list[str], max_count: int) -> list[str]:
    """Оставить не больше max_count последних непустых строк."""
    lines = [ln for ln in lines if ln.strip()]
    if max_count > 0 and len(lines) > max_count:
        return lines[-max_count:]
    return lines


def history_record(time: str, source: str, text: str, result: str,
                   ok: bool = True) -> dict:
    """Единая запись истории (время, текст, кто выполнил, успех)."""
    return {"time": time, "type": source, "question": text, "answer": result,
            "ok": bool(ok)}


def history_line(rec: dict) -> str:
    return json.dumps(rec, ensure_ascii=False)


def parse_history_line(line: str) -> dict | None:
    try:
        rec = json.loads(line)
        return rec if isinstance(rec, dict) else None
    except (ValueError, TypeError):
        return None


def history_search(lines: list[str], word: str) -> list[dict]:
    """Записи истории, содержащие слово (в вопросе или ответе)."""
    w = (word or "").lower().replace("ё", "е")
    out = []
    for ln in lines:
        rec = parse_history_line(ln)
        if not rec:
            continue
        blob = f"{rec.get('question', '')} {rec.get('answer', '')}".lower().replace("ё", "е")
        if w in blob:
            out.append(rec)
    return out


def backup_names_to_delete(names: list[str], keep: int = 20) -> list[str]:
    """Имена файлов бэкапов (config-YYYYmmdd-HHMMSS.json) -> какие удалить,
    оставив keep самых новых."""
    if keep <= 0 or len(names) <= keep:
        return []
    ordered = sorted(names)
    return ordered[:len(ordered) - keep]


# ============================================================================
#  Список дел и заметки (чистая логика над строками)
# ============================================================================

def todo_add(todos: list, text: str) -> list:
    text = (text or "").strip()
    if text:
        todos = list(todos)
        todos.append({"text": text, "done": False})
    return todos


def todo_done(todos: list, selector: str) -> tuple[list, str | None]:
    """Отметить выполненным по номеру («1») или по тексту.
    -> (список, найденный текст|None)."""
    sel = (selector or "").strip().lower().replace("ё", "е")
    if not sel:
        return todos, None
    if sel.isdigit():
        idx = int(sel) - 1
        if 0 <= idx < len(todos):
            todos[idx]["done"] = True
            return todos, todos[idx]["text"]
        return todos, None
    for row in todos:
        if sel in str(row.get("text", "")).lower().replace("ё", "е"):
            row["done"] = True
            return todos, row["text"]
    return todos, None


def todo_clear_done(todos: list) -> list:
    return [r for r in todos if not r.get("done")]


def todo_text(todos: list) -> str:
    if not todos:
        return "Список дел пуст."
    out = []
    for i, row in enumerate(todos, 1):
        mark = "✓" if row.get("done") else "•"
        out.append(f"{i}. {mark} {row.get('text', '')}")
    return "\n".join(out)


def notes_search(text: str, word: str) -> list[str]:
    """Строки notes.txt, содержащие слово (без учёта регистра, ё/е)."""
    w = (word or "").lower().replace("ё", "е")
    return [ln for ln in (text or "").splitlines()
            if w in ln.lower().replace("ё", "е")]


def notes_last(text: str) -> str | None:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1] if lines else None


def notes_drop_last(text: str) -> str:
    lines = (text or "").splitlines()
    idx = max((i for i, ln in enumerate(lines) if ln.strip()), default=None)
    if idx is None:
        return ""
    del lines[idx]
    return "\n".join(lines) + ("\n" if lines else "")


# ============================================================================
#  Таймеры: разбор и проверка срока (чистая логика)
# ============================================================================

def timer_due(seconds: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    return now + timedelta(seconds=max(1, int(seconds)))


def timer_remaining(due_iso: str, now: datetime | None = None) -> int | None:
    """Секунды до срока; отрицательное — просрочен; None — дата битая."""
    now = now or datetime.now()
    try:
        due = datetime.fromisoformat(due_iso)
    except (ValueError, TypeError):
        return None
    return int((due - now).total_seconds())


def timer_expired(due_iso: str, now: datetime | None = None) -> bool:
    rem = timer_remaining(due_iso, now)
    return rem is not None and rem <= 0


def format_remaining(seconds: int) -> str:
    """«1 ч 5 мин», «45 с» — для озвучки сколько осталось."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} ч")
    if m:
        parts.append(f"{m} мин")
    if s or not parts:
        parts.append(f"{s} с")
    return " ".join(parts)


# ============================================================================
#  Режим диктовки: вкл/выкл, автовыход, пропуск команд
# ============================================================================

DICTATION_START_WORDS = ("режим диктовки", "начать диктовку", "начни диктовку",
                         "диктуй", "включи диктовку")
DICTATION_STOP_WORDS = ("закончить диктовку", "стоп диктовка", "останови диктовку",
                        "выйти из диктовки", "хватит диктовать", "конец диктовки")


def dictation_mode_detect(text: str) -> str | None:
    """«start» / «stop» / None — команды включения/выключения режима диктовки."""
    t = (text or "").lower().replace("ё", "е")
    for w in DICTATION_STOP_WORDS:
        if w in t:
            return "stop"
    for w in DICTATION_START_WORDS:
        if w in t:
            return "start"
    return None


def dictation_idle_expired(last_seen: float, now: float, timeout_sec) -> bool:
    """Автовыход из режима диктовки по тишине (timeout_sec, по умолчанию 120 с)."""
    try:
        timeout = float(timeout_sec)
    except (TypeError, ValueError):
        timeout = 120.0
    if timeout <= 0:
        return False
    return (now - last_seen) >= timeout


def is_dictation_text(mode_active: bool, text: str) -> bool:
    """True — фраза должна уйти в текст диктовки, а НЕ в таблицу COMMANDS.

    В режиме диктовки любая фраза (включая «громче», «таймер», «выключи»)
    считается текстом; команды включения/выключения режима обрабатывает
    вызывающий код ДО этой проверки.
    """
    if not mode_active:
        return False
    return dictation_mode_detect(text) is None
