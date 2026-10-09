"""Декларативный реестр голосовых интентов (чистый модуль, без Windows/Tk).

Каждый интент — имя, обучающие фразы, приоритет, флаги. Сопоставление:
нормализация → точные фразы → токенный скор (без «слово начинается с основы»
для коротких слов) → при ничьей — переспрос («Ты имел в виду: А или Б?»),
а не угадывание по порядку строк.

Таблица приоритетов (меньше — выше):
питание/выход/пауза (0–9) > управление окнами (10–19) >
громкость/яркость (20–29) > запуск приложений (30–39) > поиск (40–49) >
заметки/напоминания/таймеры (50–59) > остальное (60+).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е")).strip(" ,.!?—-")


def tokenize(text: str) -> list[str]:
    return [w for w in re.split(r"[^0-9a-zа-я]+", normalize(text)) if w]


def _token_match(phrase_tok: str, text_tok: str) -> bool:
    """Точное совпадение; для слов длиной ≥5 — по префиксу из 5 букв
    («открой» ловит «откройте»), короткие слова только целиком."""
    if phrase_tok == text_tok:
        return True
    if len(phrase_tok) >= 5 and text_tok.startswith(phrase_tok[:5]):
        return True
    return False


def phrase_score(text_tokens: list[str], phrase: str) -> float:
    """Доля слов фразы, найденных в тексте. 1.0 — все слова на месте."""
    ptoks = tokenize(phrase)
    if not ptoks:
        return 0.0
    matched = sum(1 for p in ptoks if any(_token_match(p, t) for t in text_tokens))
    return matched / len(ptoks)


@dataclass(frozen=True)
class Intent:
    name: str
    phrases: tuple = ()
    priority: int = 50
    play_only: bool = False
    pattern: str | None = None  # regex для произвольных целей: «закрой <что угодно>»

    def score(self, text_tokens: list[str], text: str) -> float:
        best = max((phrase_score(text_tokens, p) for p in self.phrases), default=0.0)
        if self.pattern and re.search(self.pattern, text):
            best = max(best, 1.0)
        return best


@dataclass(frozen=True)
class Hit:
    intent: Intent
    score: float


def match(text: str, intents, threshold: float = 1.0) -> list[Hit]:
    """Все совпавшие интенты, отсортированные: приоритет, затем скор."""
    t = normalize(text)
    toks = tokenize(t)
    hits = [Hit(it, s) for it in intents if (s := it.score(toks, t)) >= threshold]
    hits.sort(key=lambda h: (h.intent.priority, -h.score))
    return hits


def is_tie(hits: list[Hit]) -> bool:
    """Ничья: два интента одного приоритета с одинаковым скором — угадывать нельзя."""
    return (len(hits) >= 2
            and hits[0].intent.priority == hits[1].intent.priority
            and hits[0].score == hits[1].score)


def tie_options(hits: list[Hit], limit: int = 2) -> list[str]:
    """Подписи для переспроса «Ты имел в виду: А или Б?»."""
    best = hits[0].score
    pri = hits[0].intent.priority
    return [h.intent.name for h in hits
            if h.intent.priority == pri and h.score == best][:limit]


# Обработка ответа на переспрос: «первая», «вторая», «второе», «1», «2»
_FIRST_WORDS = {"первая", "первой", "первое", "первый", "1", "один", "одна"}
_SECOND_WORDS = {"вторая", "второй", "второе", "2", "два", "две"}


def clarify_choice(text: str, limit: int = 2) -> int | None:
    """Индекс выбранной опции (0-based) по ответу «первая/вторая», иначе None."""
    t = normalize(text)
    if t in _FIRST_WORDS:
        return 0
    if limit >= 2 and t in _SECOND_WORDS:
        return 1
    return None
