"""Матрица «фраза → ожидаемое решение» на реальных репликах владельца.

Здесь — чистая маршрутизация (jarvis_routing), проверяемая без Windows и Tk.
Полная таблица интентов команд растёт по мере развития реестра.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jarvis_routing as routing  # noqa: E402


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
