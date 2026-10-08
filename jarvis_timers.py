"""Таймеры, будильники, секундомер и ежедневные напоминания (задачи 15 и 42).

Состояние — ~/.jarvis/timers.json, переживает перезапуск: просроченные
срабатывают при старте. Windows-импортов нет — логика тестируется на Linux:
    python -m pytest tests/test_timers.py
Озвучку и уведомления при срабатывании вызывает jarvis.py (callback fire).
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta

try:
    import jarvis_utils as u
except ImportError:  # pragma: no cover
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import jarvis_utils as u


class TimerStore:
    """Хранилище таймеров/будильников/секундомера с атомарной записью."""

    def __init__(self, path):
        self.path = os.path.expanduser(str(path))
        self.lock = threading.Lock()
        self._rows: list[dict] = self._load()

    # --- файл ---------------------------------------------------------------
    def _load(self) -> list[dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                rows = json.load(f)
            return rows if isinstance(rows, list) else []
        except (OSError, ValueError):
            return []

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._rows, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # --- чтение ---------------------------------------------------------------
    def rows(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self._rows]

    def upcoming(self, now: datetime | None = None) -> list[dict]:
        """Непросроченные таймеры и будильники, отсортированные по сроку."""
        now = now or datetime.now()
        out = []
        for r in self.rows():
            if r.get("kind") == "stopwatch":
                continue
            rem = u.timer_remaining(str(r.get("due") or ""), now)
            if rem is not None and rem > 0:
                out.append({**r, "remaining": rem})
        out.sort(key=lambda r: r["remaining"])
        return out

    # --- запись ---------------------------------------------------------------
    def add_timer(self, seconds: int, text: str, now: datetime | None = None) -> dict:
        row = {"kind": "timer", "text": (text or "таймер").strip(),
               "due": u.timer_due(seconds, now).isoformat(timespec="seconds"),
               "created": f"{now or datetime.now():%Y-%m-%d %H:%M:%S}"}
        with self.lock:
            self._rows.append(row)
            self.save()
        return row

    def add_alarm(self, clock: str, text: str, now: datetime | None = None) -> dict:
        """clock — «ЧЧ:ММ»; если время уже прошло — на завтра."""
        now = now or datetime.now()
        hh, mm = (int(x) for x in clock.split(":"))
        due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        row = {"kind": "alarm", "text": (text or "будильник").strip(),
               "clock": clock, "due": due.isoformat(timespec="seconds"),
               "created": f"{now:%Y-%m-%d %H:%M:%S}"}
        with self.lock:
            self._rows.append(row)
            self.save()
        return row

    def cancel(self, selector: str) -> dict | None:
        """Убрать таймер по имени/фрагменту; пустой selector — последний."""
        sel = (selector or "").strip().lower()
        with self.lock:
            active = [r for r in self._rows if r.get("kind") in ("timer", "alarm")]
            hit = None
            if sel:
                for r in active:
                    if sel in str(r.get("text", "")).lower():
                        hit = r
                        break
            if hit is None and active:
                hit = active[-1]
            if hit is not None:
                self._rows.remove(hit)
                self.save()
            return dict(hit) if hit else None

    def pop_expired(self, now: datetime | None = None) -> list[dict]:
        """Все просроченные (включая «задержавшиеся» после перезапуска)."""
        now = now or datetime.now()
        fired = []
        with self.lock:
            keep = []
            for r in self._rows:
                if r.get("kind") == "stopwatch":
                    keep.append(r)
                    continue
                if u.timer_expired(str(r.get("due") or ""), now):
                    fired.append(dict(r))
                else:
                    keep.append(r)
            if len(keep) != len(self._rows):
                self._rows = keep
                self.save()
        return fired

    # --- секундомер ------------------------------------------------------------
    def stopwatch_start(self, now: datetime | None = None) -> dict:
        now = now or datetime.now()
        with self.lock:
            self._rows = [r for r in self._rows if r.get("kind") != "stopwatch"]
            row = {"kind": "stopwatch", "started": now.isoformat(timespec="seconds"),
                   "elapsed": 0, "paused": False}
            self._rows.append(row)
            self.save()
        return row

    def stopwatch_toggle(self, now: datetime | None = None) -> dict | None:
        """Пауза/продолжить. None — секундомер не запущен."""
        now = now or datetime.now()
        with self.lock:
            row = next((r for r in self._rows if r.get("kind") == "stopwatch"), None)
            if row is None:
                return None
            started = datetime.fromisoformat(row["started"])
            if row.get("paused"):
                row["started"] = (now - timedelta(
                    seconds=int(row.get("elapsed") or 0))).isoformat(timespec="seconds")
                row["paused"] = False
            else:
                row["elapsed"] = int((now - started).total_seconds())
                row["paused"] = True
            self.save()
            return dict(row)

    def stopwatch_elapsed(self, now: datetime | None = None) -> int | None:
        now = now or datetime.now()
        with self.lock:
            row = next((r for r in self._rows if r.get("kind") == "stopwatch"), None)
            if row is None:
                return None
            if row.get("paused"):
                return int(row.get("elapsed") or 0)
            return int((now - datetime.fromisoformat(row["started"])).total_seconds())

    def stopwatch_reset(self) -> bool:
        with self.lock:
            n = len(self._rows)
            self._rows = [r for r in self._rows if r.get("kind") != "stopwatch"]
            changed = len(self._rows) != n
            if changed:
                self.save()
            return changed


# ============================================================================
#  Разбор фраз (чистая логика)
# ============================================================================

_TIMER_WORDS = ("таймер", "будильник", "секундомер", "засеки", "засечь")


def parse_timer_phrase(text: str) -> dict | None:
    """«таймер на 10 минут», «поставь будильник на 7:30», «напомни через полчаса».

    -> {"kind": "timer"|"alarm", "seconds": int, "clock": "ЧЧ:ММ", "text": str}
    или None, если фраза не про таймер/будильник.
    """
    t = (text or "").lower().replace("ё", "е")
    if not any(w in t for w in _TIMER_WORDS) and "через" not in t:
        return None
    # секундомер отдельно
    if "секундомер" in t or "засеки" in t or "засечь" in t:
        return {"kind": "stopwatch"}
    # будильник: время ЧЧ:ММ
    if "будильник" in t:
        clock = u.parse_clock_ru(t)
        if clock:
            label = _between(t, "будильник")
            return {"kind": "alarm", "clock": clock, "text": label or "будильник"}
        return None
    # таймер: длительность
    seconds = u.parse_duration_ru(t)
    if seconds:
        label = _between(t, "таймер")
        if not label:
            label = _between(t, "через")
        return {"kind": "timer", "seconds": seconds, "text": label or "таймер"}
    return None


def _between(text: str, word: str) -> str:
    """Смысловой хвост фразы: «таймер на чай» -> «чай»."""
    import re
    m = re.search(rf"\b{word}\b\s+(?:на|через)?\s+(.*)", text)
    if not m:
        return ""
    tail = m.group(1)
    # отрезаем служебные слова в середине хвоста
    for cut in ("через", "поставь", "поставить", "включи", "включить"):
        idx = tail.find(cut)
        if 0 < idx:
            tail = tail[:idx]
    tail = tail.strip(" ,.!?")
    # хвост «10 минут» — это не название, а длительность
    if not tail or tail[0].isdigit() or u.parse_duration_ru(tail) is not None:
        return ""
    return tail


def timer_message(row: dict) -> str:
    """Речь при срабатывании."""
    kind = row.get("kind")
    text = row.get("text") or "таймер"
    if kind == "alarm":
        return f"Будильник! {text} — сейчас {row.get('clock', '')}."
    return f"Время вышло: {text}."


# ============================================================================
#  Ежедневные напоминания (задача 42): время, текст, дни недели
# ============================================================================

WEEKDAY_NAMES = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def daily_due(row: dict, now: datetime | None = None) -> bool:
    """Сегодня ли срабатывает ежедневное напоминание (учитывает дни недели)."""
    now = now or datetime.now()
    clock = str(row.get("time") or row.get("at") or "")
    try:
        hh, mm = (int(x) for x in clock.split(":")[:2])
    except (ValueError, AttributeError):
        return False
    if now.hour < hh or (now.hour == hh and now.minute < mm):
        return False  # время ещё не пришло
    days = row.get("weekdays")
    if days:  # пустой список = каждый день; формат 0=пн..6=вс или имена
        today = now.weekday()
        normalized = set()
        for d in days:
            if isinstance(d, int) and 0 <= d <= 6:
                normalized.add(d)
            elif isinstance(d, str):
                d = d.lower().replace("ё", "е")[:2]
                if d in WEEKDAY_NAMES:
                    normalized.add(WEEKDAY_NAMES.index(d))
        if normalized and today not in normalized:
            return False
    last = str(row.get("last") or "")
    return last != f"{now:%Y-%m-%d}"


def daily_mark_fired(row: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    row = dict(row)
    row["last"] = f"{now:%Y-%m-%d}"
    return row
