"""Диспетчер истории: одна фраза — одна запись; фильтры филлеров и галлюцинаций."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jarvis_history as jh  # noqa: E402


def test_filler_words_are_ignored():
    for phrase in ("ну", "давай", "ага", "так", "да", "угу", "ладно", ""):
        assert jh.is_filler(phrase), phrase


def test_filler_allows_commands_and_sentences():
    for phrase in ("открой стим", "ну открой стим", "громче", "яркость 70", "сделай громче"):
        assert not jh.is_filler(phrase), phrase


def test_hallucinations_detected():
    for phrase in ("Продолжение следует", "спасибо за просмотр", "субтитры"):
        assert jh.is_hallucination(phrase), phrase
    assert not jh.is_hallucination("открой ютуб")


def test_dispatcher_writes_single_entry_per_request():
    d = jh.HistoryDispatcher()
    assert d.begin("открой стим", now=100.0)
    d.set("команда", "открой стим", "выполнена")
    # вторая запись в рамках одного запроса игнорируется
    d.set("нейросеть", "открой стим", "дубль")
    assert d.take() == ("команда", "открой стим", "выполнена", None)
    assert d.take() is None  # один раз взяли — пусто


def test_dispatcher_dedups_same_phrase_within_3_seconds():
    d = jh.HistoryDispatcher()
    assert d.begin("яркость", now=100.0)
    d.set("команда", "яркость", "выполнена")
    d.take()
    # повторный захват того же аудио в пределах 3 с — обработку не начинаем
    assert not d.begin("яркость", now=101.5)
    # спустя 3 секунды та же фраза — легальный повтор
    assert d.begin("яркость", now=104.0)


def test_dispatcher_different_phrases_do_not_dedup():
    d = jh.HistoryDispatcher()
    assert d.begin("яркость", now=100.0)
    d.set("команда", "яркость", "выполнена")
    d.take()
    assert d.begin("яркость 70", now=100.5)
