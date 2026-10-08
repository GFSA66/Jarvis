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


def close_verb(text: str) -> bool:
    return has(text, "закр", "закрыт", "выключ", "останов", "заверш", "убери")


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