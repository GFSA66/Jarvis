"""Матрица «фраза → ожидаемое решение» на реальных репликах владельца.

Здесь — чистая маршрутизация (jarvis_routing), проверяемая без Windows и Tk.
Полная таблица интентов команд растёт по мере развития реестра.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jarvis_intents as ji  # noqa: E402
import jarvis_routing as routing  # noqa: E402


# --- декларативный реестр: токенный скор, приоритет, переспрос --------------

SAMPLE = [
    ji.Intent("volume", ("громче", "тише", "громкость"), 20),
    ji.Intent("steam_game", ("киберпанк", "кс"), 32),
    ji.Intent("close_app", ("закрой блокнот",), 10,
              pattern=r"\b(?:закрой|закрыть)\s+\w+"),
    ji.Intent("track", (), 26, pattern=r"\b(?:включи|найди)\s+(?:трек|песню)\s+\S+"),
]


def test_intent_exact_and_prefix_tokens():
    hits = ji.match("громче", SAMPLE)
    assert hits and hits[0].intent.name == "volume"
    # глагол с одинаковым префиксом из 5 букв тоже распознаётся
    hits = ji.match("закрой блокнот пожалуйста", SAMPLE)
    assert hits[0].intent.name == "close_app"
    # короткое слово не должно совпадать по префиксу — только целиком
    assert not ji.match("блок", SAMPLE)


def test_intent_pattern_phrases():
    hits = ji.match("включи трек немо", SAMPLE)
    assert hits and hits[0].intent.name == "track"


def test_intent_tie_triggers_clarify():
    twin = [
        ji.Intent("note", ("заметка",), 51),
        ji.Intent("notes", ("заметка",), 51),
    ]
    hits = ji.match("заметка", twin)
    assert ji.is_tie(hits)
    assert ji.tie_options(hits) == ["note", "notes"]
    assert not ji.is_tie(ji.match("громче", SAMPLE))


def test_clarify_choice_words():
    assert ji.clarify_choice("первая") == 0
    assert ji.clarify_choice("вторая") == 1
    assert ji.clarify_choice("второе") == 1
    assert ji.clarify_choice("2") == 1
    assert ji.clarify_choice("открой стим") is None


def test_intent_threshold_rejects_partial_phrase():
    # не все слова фразы на месте — интент не срабатывает
    assert not ji.match("закрой", SAMPLE)
    assert not ji.match("гром", SAMPLE)


# Фразы из ~/.jarvis/history.jsonl владельца: фраза → ожидаемое решение
POWER_CASES = {
    "выключи пк": "shutdown",
    "выключи компьютер": "shutdown",
    "выключи пк-а": "shutdown",
}

# Негативы: филлеры и обрывки не должны считаться рекомендацией/вопросом нейросети
NEGATIVE_CASES = [
    "ну", "давай", "так", "ага", "нет", "спасибо",
    "сначала хочу все-таки подделывать",
]

# Фразы из истории: не должны запускать игры
NO_LAUNCH_CASES = [
    "во что поиграть кроме киберпанка",
    "посоветуй игру, не киберпанк",
    "не запускай майнкрафт",
    "запусти всё кроме стима",
]

# Должны запускать (по прямой просьбе)
LAUNCH_CASES = [
    "запусти roblox",
    "запусти киберпанк",
]


def test_history_power_phrases():
    for phrase, expected in POWER_CASES.items():
        assert routing.power_intent(phrase) == expected, phrase


def test_history_negatives_are_not_recommendations():
    for phrase in NEGATIVE_CASES:
        assert not routing.is_recommendation(phrase), phrase


def test_history_negation_phrases_block_launch():
    for phrase in NO_LAUNCH_CASES:
        assert routing.launch_blocked(phrase), phrase


def test_history_direct_launch_allowed():
    for phrase in LAUNCH_CASES:
        assert not routing.launch_blocked(phrase), phrase


def test_history_close_pc_is_power_hint_not_process():
    for phrase in ("закрой пк", "закрой компьютер", "закрой ноутбук"):
        assert routing.resolve_close(phrase)["kind"] == "power_hint", phrase
