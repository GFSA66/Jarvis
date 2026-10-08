"""Тесты логики таймеров (без Windows)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta  # noqa: E402

import jarvis_timers as jt  # noqa: E402


def _store(tmp_path):
    return jt.TimerStore(tmp_path / "timers.json")


def test_add_and_fire_timer(tmp_path):
    store = _store(tmp_path)
    now = datetime(2026, 10, 7, 12, 0, 0)
    store.add_timer(60, "чай", now=now)
    assert store.pop_expired(now + timedelta(seconds=30)) == []
    fired = store.pop_expired(now + timedelta(seconds=61))
    assert len(fired) == 1
    assert fired[0]["text"] == "чай"
    assert store.pop_expired(now + timedelta(seconds=62)) == []


def test_timer_survives_restart(tmp_path):
    store = _store(tmp_path)
    now = datetime(2026, 10, 7, 12, 0, 0)
    store.add_timer(10, "проверка", now=now)
    store2 = _store(tmp_path)  # перезапуск
    fired = store2.pop_expired(now + timedelta(seconds=11))
    assert len(fired) == 1  # просроченный срабатывает при старте


def test_alarm_tomorrow_if_time_passed(tmp_path):
    store = _store(tmp_path)
    now = datetime(2026, 10, 7, 12, 0, 0)
    row = store.add_alarm("07:30", "подъём", now=now)
    due = datetime.fromisoformat(row["due"])
    assert due.date() == (now + timedelta(days=1)).date()
    up = store.upcoming(now)
    assert up and up[0]["kind"] == "alarm"


def test_cancel_last(tmp_path):
    store = _store(tmp_path)
    now = datetime(2026, 10, 7, 12, 0, 0)
    store.add_timer(60, "чай", now=now)
    store.add_timer(120, "ужин", now=now)
    hit = store.cancel("")
    assert hit["text"] == "ужин"  # последний
    hit = store.cancel("чай")
    assert hit["text"] == "чай"
    assert store.cancel("") is None


def test_stopwatch(tmp_path):
    store = _store(tmp_path)
    now = datetime(2026, 10, 7, 12, 0, 0)
    store.stopwatch_start(now)
    assert store.stopwatch_elapsed(now + timedelta(seconds=45)) == 45
    store.stopwatch_toggle(now + timedelta(seconds=45))  # пауза
    assert store.stopwatch_elapsed(now + timedelta(seconds=100)) == 45
    store.stopwatch_toggle(now + timedelta(seconds=100))  # продолжить
    assert store.stopwatch_elapsed(now + timedelta(seconds=110)) == 55
    assert store.stopwatch_reset()
    assert store.stopwatch_elapsed(now) is None


def test_parse_timer_phrase():
    p = jt.parse_timer_phrase("поставь таймер на 10 минут")
    assert p["kind"] == "timer" and p["seconds"] == 600
    p = jt.parse_timer_phrase("таймер на пять минут на чай")
    assert p["kind"] == "timer" and p["seconds"] == 300
    p = jt.parse_timer_phrase("поставь будильник на 7:30")
    assert p == {"kind": "alarm", "clock": "07:30", "text": ""}
    p = jt.parse_timer_phrase("напомни через полчаса проверить печь")
    assert p and p["kind"] == "timer" and p["seconds"] == 1800
    assert jt.parse_timer_phrase("загугли погоду") is None


def test_parse_stopwatch():
    p = jt.parse_timer_phrase("засеки время")
    assert p == {"kind": "stopwatch"}


def test_timer_message():
    assert "чай" in jt.timer_message({"kind": "timer", "text": "чай"})
    assert "Будильник" in jt.timer_message({"kind": "alarm", "text": "подъём",
                                            "clock": "07:30"})


def test_daily_due():
    now = datetime(2026, 10, 7, 9, 0, 0)  # среда, weekday()==2
    row = {"time": "08:30", "text": "таблетки", "weekdays": []}
    assert jt.daily_due(row, now)  # прошло время, сегодня ещё не срабатывало
    row = jt.daily_mark_fired(row, now)
    assert not jt.daily_due(row, now)  # уже сработало сегодня
    row["weekdays"] = [4]  # только пятница
    row["last"] = ""
    assert not jt.daily_due(row, now)  # сегодня среда
    row["weekdays"] = [2]
    assert jt.daily_due(row, now)


def test_daily_bad_time():
    assert not jt.daily_due({"time": "семь", "weekdays": []})
