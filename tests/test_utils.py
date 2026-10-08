"""Тесты чистой логики Джарвиса (без Windows)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime  # noqa: E402

import jarvis_utils as u  # noqa: E402


# --- числа -------------------------------------------------------------------

def test_parse_number_digits():
    assert u.parse_number_ru("громкость на 30") == 30
    assert u.parse_number_ru("30") == 30


def test_parse_number_words():
    assert u.parse_number_ru("громкость на тридцать") == 30
    assert u.parse_number_ru("сто") == 100
    assert u.parse_number_ru("двадцать пять") == 25
    assert u.parse_number_ru("два") == 2


def test_parse_number_none():
    assert u.parse_number_ru("") is None
    assert u.parse_number_ru("просто фраза без чисел") is None


# --- длительности ------------------------------------------------------------

def test_parse_duration():
    assert u.parse_duration_ru("5 минут") == 300
    assert u.parse_duration_ru("пять минут") == 300
    assert u.parse_duration_ru("полтора часа") == 5400
    assert u.parse_duration_ru("через час") == 3600
    assert u.parse_duration_ru("полчаса") == 1800
    assert u.parse_duration_ru("2 часа 15 минут") == 8100
    assert u.parse_duration_ru("таймер на 10 минут") == 600
    assert u.parse_duration_ru("напомни через 30 секунд") == 30


def test_parse_duration_none():
    assert u.parse_duration_ru("просто текст") is None
    assert u.parse_duration_ru("") is None


def test_parse_clock():
    assert u.parse_clock_ru("поставь будильник на 7:30") == "07:30"
    assert u.parse_clock_ru("в 20:00") == "20:00"
    assert u.parse_clock_ru("в 9 утра") == "09:00"
    assert u.parse_clock_ru("в 8 вечера") == "20:00"
    assert u.parse_clock_ru("времени нет") is None


# --- диктовка: знаки и правки -------------------------------------------------

def test_dictation_marks():
    typed, buf, delete = u.apply_dictation_commands(
        "привет запятая как дела", "", True)
    assert delete == 0
    assert "," in buf
    assert buf.startswith("Привет")  # заглавная в начале


def test_dictation_capital_after_dot():
    _t, buf, _d = u.apply_dictation_commands("привет точка", "", True)
    _t2, buf2, _d2 = u.apply_dictation_commands("как дела", buf, True)
    assert "Привет" in buf2
    assert ". Как" in buf2


def test_dictation_new_line():
    _t, buf, _d = u.apply_dictation_commands("строка новая строка", "", True)
    assert "\n" in buf


def test_dictation_delete_last_word():
    typed, buf, delete = u.apply_dictation_commands(
        "удали последнее слово", "привет мир")
    assert delete == len("привет мир") - len("привет ")
    assert buf == "привет "


def test_dictation_cancel():
    typed, buf, delete = u.apply_dictation_commands("отмени ввод", "abc")
    assert buf == "" and delete == 3 and typed == ""


def test_dictation_no_autoformat():
    _t, buf, _d = u.apply_dictation_commands("привет", "", False)
    assert buf == "привет"  # без заглавной


def test_dictation_passthrough_words_are_text():
    # слова-команды внутри диктовки — обычный текст, а не COMMANDS
    for word in ("громче", "таймер", "скриншот", "выключи"):
        assert u.is_dictation_text(True, f"сделай {word} пожалуйста")
        assert not u.is_dictation_text(False, f"сделай {word} пожалуйста")


def test_dictation_mode_detect():
    assert u.dictation_mode_detect("режим диктовки") == "start"
    assert u.dictation_mode_detect("сейчас закончить диктовку") == "stop"
    assert u.dictation_mode_detect("открой ютуб") is None


def test_dictation_idle_timeout():
    now = 1000.0
    assert not u.dictation_idle_expired(now - 60, now, 120)
    assert u.dictation_idle_expired(now - 130, now, 120)
    assert not u.dictation_idle_expired(now - 9999, now, 0)  # 0 — выключено


# --- кубики -------------------------------------------------------------------

def test_roll_dice_d20():
    r = u.roll_dice("d20")
    assert 1 <= r["total"] <= 20
    assert r["rolls"] == [r["total"]]


def test_roll_dice_4d6_plus3():
    r = u.roll_dice("4d6 плюс 3")
    assert len(r["rolls"]) == 4
    assert all(1 <= x <= 6 for x in r["rolls"])
    assert sum(r["rolls"]) + 3 == r["total"]


def test_roll_dice_limits():
    import pytest
    with pytest.raises(ValueError):
        u.roll_dice("101d6")
    with pytest.raises(ValueError):
        u.roll_dice("d1001")
    with pytest.raises(ValueError):
        u.roll_dice("что-то не то")


def test_flip_coin():
    assert u.flip_coin() in ("орёл", "решка")


# --- история и бэкапы ---------------------------------------------------------

def test_history_record_roundtrip():
    rec = u.history_record("2026-10-07 12:00:00", "команда", "открой ютуб", "выполнена")
    parsed = u.parse_history_line(u.history_line(rec))
    assert parsed["question"] == "открой ютуб"
    assert parsed["ok"] is True


def test_history_search():
    lines = [
        u.history_line(u.history_record("t1", "команда", "громче", "ок")),
        u.history_line(u.history_record("t2", "нейросеть", "какая погода", "солнечно")),
    ]
    assert len(u.history_search(lines, "погода")) == 1
    assert len(u.history_search(lines, "громче")) == 1
    assert u.history_search(lines, "хомяк") == []


def test_trim_jsonl():
    lines = [f"line{i}" for i in range(50)]
    assert len(u.trim_jsonl_lines(lines, 300)) == 50
    assert len(u.trim_jsonl_lines(lines, 10)) == 10
    assert u.trim_jsonl_lines(["", "a", "b"], 10) == ["a", "b"]


def test_backup_rotation():
    names = [f"config-20260101-00000{i:02d}.json" for i in range(25)]
    dead = u.backup_names_to_delete(names, keep=20)
    assert len(dead) == 5
    assert dead == sorted(names)[:5]
    assert u.backup_names_to_delete(names, keep=30) == []


# --- список дел и заметки -----------------------------------------------------

def test_todo_flow():
    todos = u.todo_add([], "купить молоко")
    todos = u.todo_add(todos, "позвонить маме")
    todos, hit = u.todo_done(todos, "1")
    assert hit == "купить молоко"
    assert "✓" in u.todo_text(todos)
    assert len(u.todo_clear_done(todos)) == 1  # остался невыполненный


def test_todo_done_by_text():
    todos = u.todo_add([], "купить хлеб")
    todos, hit = u.todo_done(todos, "хлеб")
    assert hit == "купить хлеб"
    assert todos[0]["done"] is True


def test_todo_done_missing():
    todos = u.todo_add([], "купить хлеб")
    _t, hit = u.todo_done(todos, "9")
    assert hit is None


def test_notes_logic():
    text = "первая заметка\nвторая про погоду\nтретья\n"
    assert u.notes_last(text) == "третья"
    assert u.notes_search(text, "погоду") == ["вторая про погоду"]
    assert u.notes_last(u.notes_drop_last(text)) == "вторая про погоду"


# --- таймеры ------------------------------------------------------------------

def test_timer_due_and_remaining():
    now = datetime(2026, 10, 7, 12, 0, 0)
    due = u.timer_due(60, now)
    assert u.timer_remaining(due.isoformat(), now) == 60
    assert not u.timer_expired(due.isoformat(), now)
    assert u.timer_expired(due.isoformat(), due)
    assert u.timer_remaining("не дата", now) is None


def test_format_remaining():
    assert u.format_remaining(45) == "45 с"
    assert u.format_remaining(3600 + 300) == "1 ч 5 мин"
    assert u.format_remaining(0) == "0 с"
