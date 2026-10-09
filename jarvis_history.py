"""Диспетчер истории запросов: одна фраза — одна запись в history.jsonl.
Модуль чистый (без Windows/Tk) — тестируется и в Linux CI.
Логика: перед обработкой фразы вызывается begin(); команды кладут свой
результат через set(); в конце обработки take() отдаёт единственную запись.
Повтор той же фразы в пределах DEDUP_SEC (повторный захват того же аудио)
игнорируется целиком.
"""
from __future__ import annotations

import time

# Слова-паразиты и обрывки: в окне внимания не выполняются и не идут в нейросеть
FILLERS = frozenset({
    "ну", "давай", "ага", "угу", "ок", "окей", "хорошо", "понял", "спасибо",
    "так", "это", "да", "нет", "мм", "ладно", "конечно", "пожалуй", "вот",
    "короче", "значит", "просто", "типа", "слушай", "блин", "погоди",
})

# Галлюцинации бесплатных STT-движков — молча, без записи и выполнения
HALLUCINATIONS = (
    "продолжение следует", "продолжение", "спасибо за просмотр", "субтитры",
    "перевод предоставлен", "переведено", "subscribe", "подпишитесь",
)


def is_filler(text: str) -> bool:
    """Филлер/обрывок: подряд слова-паразиты либо одно слово короче 4 букв."""
    words = [w.strip(",.!?;:—-") for w in (text or "").lower().replace("ё", "е").split()]
    words = [w for w in words if w]
    if not words:
        return True
    if all(w in FILLERS for w in words):
        return True
    return len(words) == 1 and len(words[0]) < 4


def is_hallucination(text: str) -> bool:
    """Повторяющаяся галлюцинация STT («продолжение следует», «субтитры…»)."""
    t = (text or "").lower().replace("ё", "е")
    return any(s in t for s in HALLUCINATIONS)


class HistoryDispatcher:
    """Накапливает запись текущего запроса; дублей не бывает по построению."""

    DEDUP_SEC = 3.0

    def __init__(self) -> None:
        self._entry: tuple | None = None
        self._last_text = ""
        self._last_time = 0.0

    def begin(self, text: str, now: float | None = None) -> bool:
        """Начать обработку фразы. False — повтор того же аудио, обработку пропускаем."""
        now = time.time() if now is None else now
        self._entry = None
        if text and text == self._last_text and now - self._last_time < self.DEDUP_SEC:
            return False
        self._last_text = text
        self._last_time = now
        return True

    def set(self, kind: str, question: str, answer: str, tools=None) -> None:
        """Зафиксировать единственный итог запроса (первая запись побеждает)."""
        if self._entry is None:
            self._entry = (kind, question, answer, tools)

    def take(self) -> tuple | None:
        """Забрать запись (один раз) и начать новый запрос пустым."""
        entry, self._entry = self._entry, None
        return entry


DISPATCH = HistoryDispatcher()
