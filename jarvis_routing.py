"""Чистая диагностика приоритета голосовых команд.

Модуль намеренно не импортирует Windows/Tk и используется ранним CLI-путём
``jarvis.py --match`` также в Linux CI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е")).strip(" ,.!?—-")


def has(text: str, *stems: str) -> bool:
    return any(re.search(r"\b" + re.escape(stem), text) for stem in stems)


CLOSE_VERBS = ("закрой", "закрыть", "закройте", "закрывать", "выключь", "выключить",
               "останови", "остановить", "заверши", "завершить", "убери", "убрать")
_CLOSE_RE = re.compile(r"\b(?:" + "|".join(CLOSE_VERBS) + r")\b")
_FILLERS = ("пожалуйста", "пожалуй", "please")


def close_verb(text: str) -> bool:
    """Точная форма глагола закрытия — не «закройщик» и не любая основа закр…"""
    return bool(_CLOSE_RE.search(text))


# ---------------------------------------------------------------------------
#  Питание ПК — высший приоритет, до таблицы COMMANDS и до «закрой …»
# ---------------------------------------------------------------------------
_PC_RE = re.compile(
    r"\b(?:пк|пэка|пека|пика|комп(?:ьютер\w*)?|ноутбук\w*|машин\w*|систем\w*|винд\w*|windows)\b"
)


def is_pc_target(text: str) -> bool:
    """Цель — сам компьютер, включая искажения Google STT («пэка», «пика», «пк-а»)."""
    return bool(_PC_RE.search(text or ""))


def power_intent(text: str) -> str | None:
    """«shutdown» / «restart» / «cancel» / «sleep» / «hibernate» / «lock» или None.

    Вызывается ДО разбора COMMANDS, поэтому «выключи пк» никогда не попадёт
    в обработчик закрытия окон. Требует явной цели-компьютера, чтобы
    «выключи звук» оставалось командой громкости.
    """
    t = normalize(text)
    if not t:
        return None
    if has(t, "отмен") and has(t, "выключ", "перезагруз", "shutdown"):
        return "cancel"
    if has(t, "перезагруз") and (is_pc_target(t) or has(t, "работ")):
        return "restart"
    if has(t, "выключ", "выруб", "заверш") and (is_pc_target(t) or has(t, "работ")):
        return "shutdown"
    if has(t, "режим сна") or re.search(r"\bусни\b|\bспи\b", t):
        return "sleep"
    if has(t, "гибернац"):
        return "hibernate"
    if has(t, "заблокир", "блокируй пк"):
        return "lock"
    return None


# ---------------------------------------------------------------------------
#  Закрытие окон: цель из фразы (чистая логика; исполнение — jarvis_system)
# ---------------------------------------------------------------------------
_ACTIVE_TARGETS = {"это", "окно", "текущее", "активное", "данное", "сейчас",
                   "это окно", "текущее окно", "активное окно", "данное окно"}


def resolve_close(text: str, aliases: dict | None = None) -> dict:
    """Решение по фразе закрытия: kind = app | active | power_hint | error."""
    t = normalize(text)
    if not close_verb(t):
        return {"kind": "error", "message": "Это не похоже на команду закрытия."}
    target = t
    for verb in CLOSE_VERBS:
        target = re.sub(rf"\b{verb}\b", " ", target)
    for filler in _FILLERS:
        target = re.sub(rf"\b{filler}\b", " ", target)
    target = re.sub(r"\s+", " ", target).strip(" ,.!?-—")
    if not target:
        return {"kind": "error", "message": "Не понял, какое окно закрыть."}
    if target in _ACTIVE_TARGETS:
        return {"kind": "active", "target": "", "label": "активное окно"}
    if is_pc_target(target):
        return {"kind": "power_hint", "target": target,
                "message": "Компьютер нельзя закрыть как окно. "
                           "Скажи «выключи компьютер», чтобы выключить."}
    resolved = (aliases or {}).get(target, target)
    return {"kind": "app", "target": resolved, "label": target}


# ---------------------------------------------------------------------------
#  Отрицания: «только не киберпанк», «кроме кс», «не запускай майнкрафт»
# ---------------------------------------------------------------------------
_NEG_RE = re.compile(
    r"\b(?:не|нет|только\s+не|не\s+надо|не\s+хочу|не\s+нужно|кроме|без|исключая|"
    r"не\s+запуск\w*|не\s+открыв\w*|не\s+включ\w*|не\s+делай)\b"
)
_QUESTION_STARTS = {"что", "какой", "какая", "какое", "какие", "какую", "как", "когда",
                    "где", "куда", "почему", "зачем", "сколько", "кто", "во что"}


def has_negation(text: str) -> bool:
    return bool(_NEG_RE.search(normalize(text)))


def is_recommendation(text: str) -> bool:
    """Фраза-просьба посоветовать: её нельзя резать и по ней нельзя запускать игры."""
    t = normalize(text)
    if any(w in t for w in ("посоветуй", "посоветуешь", "рекоменд", "предложи игру",
                            "что поиграть", "во что", "какую игру", "что лучше поиграть")):
        return True
    return bool(t) and t.split()[0] in _QUESTION_STARTS


def negated_terms(text: str, terms) -> set[str]:
    """Сущности из terms, оказавшиеся в зоне отрицания (до запятой/«но»/«и»)."""
    t = normalize(text)
    out: set[str] = set()
    marks = list(_NEG_RE.finditer(t))
    if not marks:
        return out
    for term in terms:
        term_l = normalize(str(term))
        if not term_l:
            continue
        for m in re.finditer(re.escape(term_l), t):
            prior = [x for x in marks if x.start() < m.start()]
            if not prior:
                continue
            between = t[prior[-1].end():m.start()]
            if re.search(r"[,;!?]|(?:\bно\b)|\bплюс\b", between):
                continue  # отрицание относится к другой части фразы
            if len(between.split()) <= 6:
                out.add(str(term))
                break
    return out


def launch_blocked(text: str) -> bool:
    """Запрет запуска: есть отрицание либо фраза является рекомендацией/вопросом."""
    t = normalize(text)
    return bool(t) and (has_negation(t) or is_recommendation(t))


def can_split_chain(text: str) -> bool:
    """Резать цепочку «и/потом/запятая» нельзя для вопросов и фраз с отрицанием."""
    t = normalize(text)
    return bool(t) and not has_negation(t) and not is_recommendation(t)


@dataclass(frozen=True)
class Match:
    name: str
    reason: str


def diagnose(text: str, custom_commands: list[dict] | None = None) -> tuple[str, list[Match]]:
    """Вернуть нормализованный текст и все подходящие правила в порядке COMMANDS.

    Список повторяет конфликтные и пользовательские правила ассистента. Он нужен
    именно для объяснения маршрутизации, а не для запуска команд.
    """
    t = normalize(text)
    matches: list[Match] = []
    def add(name: str, ok: bool, reason: str) -> None:
        if ok:
            matches.append(Match(name, reason))

    power = power_intent(t)
    add(f"power:{power}", power is not None, "питание ПК — высший приоритет, до COMMANDS")
    close_req = resolve_close(t)
    add("close_pc_hint", close_req["kind"] == "power_hint",
        "глагол закрытия направлен на сам ПК — подсказка про «выключи компьютер»")
    add("translate_clipboard", has(t, "переведи буфер"), "основа «переведи буфер»")
    add("clipboard", has(t, "прочитай буфер", "прочитай выделенн", "прочти выделенн",
                          "озвучь выделенн", "читай выделенн", "что в буфере", "озвучь буфер"),
        "основа чтения буфера/выделения")
    add("dice", (has(t, "брос", "кин", "бросок") and ("d" in t or "д" in t or has(t, "куб", "кост")))
        or has(t, "подбрось монет", "монетк"), "основа броска/кубика/монетки")
    add("media", (has(t, "следующ", "дальше", "вперед", "предыдущ", "прошл", "назад", "верни")
                  and has(t, "трек", "песн")), "слово направления и «трек/песня»")
    add("close_any", close_verb(t) and has(t, "блокнот", "notepad"),
        "глагол закрытия и известное приложение")
    for command in sorted(custom_commands or [], key=lambda c: -len(str(c.get("phrase", "")))):
        phrase = normalize(str(command.get("phrase", "")))
        if phrase and has(t, phrase) and not close_verb(t):
            add("custom", True, f"пользовательская фраза «{phrase}»")
    return t, matches


def format_diagnosis(text: str, custom_commands: list[dict] | None = None) -> str:
    normalized, matches = diagnose(text, custom_commands)
    lines = [f"Нормализовано: {normalized or '—'}"]
    if not matches:
        return "\n".join(lines + ["Совпадений: нет."])
    first = matches[0]
    lines.append(f"Первая команда: #0 {first.name} ({first.reason})")
    lines.append("Другие совпадения:")
    lines.extend(f"  #{i} {m.name}: {m.reason}" for i, m in enumerate(matches[1:], 1))
    return "\n".join(lines)