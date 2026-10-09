"""Тесты Windows-обёрток через подмену низкоуровневого ввода."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jarvis_system as js  # noqa: E402


def test_media_virtual_key_constants_and_mapping(monkeypatch):
    pressed = []
    monkeypatch.setattr(js, "_press_key", pressed.append)
    js.media_key("nexttrack")
    js.media_key("prevtrack")
    assert js.VK_MEDIA_NEXT_TRACK == 0xB0
    assert js.VK_MEDIA_PREV_TRACK == 0xB1
    assert pressed == [0xB0, 0xB1]


# --- закрытие окон по заголовку/имени (без реального Win32) ------------------

class _Proc:
    def __init__(self, pid):
        self.pid = pid


def _patch_close_env(monkeypatch, windows=(), procs=(), active=None):
    monkeypatch.setattr(js, "visible_windows", lambda limit=200: list(windows))
    monkeypatch.setattr(js, "find_process", lambda q: list(procs))
    monkeypatch.setattr(js, "active_window", lambda: active or {"hwnd": 0, "title": "", "pid": 0})
    monkeypatch.setattr(js, "window_is_elevated", lambda hwnd: False)
    closed = []
    monkeypatch.setattr(js, "_send_wm_close", closed.append)
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    return closed


def test_close_window_by_title(monkeypatch):
    closed = _patch_close_env(monkeypatch, windows=[(11, "Без названия — Блокнот")])
    res = js.close_window_by_name("блокнот")
    assert res["closed"] == 1 and res["remaining"] == 0
    assert closed == [11]


def test_close_window_reports_open_windows_when_not_found(monkeypatch):
    _patch_close_env(monkeypatch, windows=[(11, "Документ1 — Word"), (12, "YouTube Music")])
    try:
        js.close_window_by_name("ютика")
    except js.ActionError as e:
        assert "Не нашёл окно «ютика»" in str(e)
        assert "Открытые окна:" in str(e)
        assert "Документ1 — Word" in str(e)
    else:
        raise AssertionError("должен быть ActionError")


def test_close_window_empty_target(monkeypatch):
    _patch_close_env(monkeypatch)
    try:
        js.close_window_by_name("")
    except js.ActionError as e:
        assert "Не понял" in str(e)
    else:
        raise AssertionError("должен быть ActionError")


def test_close_active_window(monkeypatch):
    closed = _patch_close_env(monkeypatch,
                              active={"hwnd": 7, "title": "Без названия — Блокнот", "pid": 3})
    res = js.close_window_by_name("это")
    assert res["closed"] == 1 and closed == [7]


def test_close_active_window_refuses_own_window(monkeypatch):
    _patch_close_env(monkeypatch,
                     active={"hwnd": 7, "title": "Джарвис — настройки", "pid": 3})
    try:
        js.close_window_by_name("это")
    except js.ActionError as e:
        assert "Джарвиса" in str(e)
    else:
        raise AssertionError("должен быть ActionError")


def test_kill_pids_skips_system_processes(monkeypatch):
    killed = []
    class _P:
        def __init__(self, name):
            self._n = name
        def name(self):
            return self._n
        def kill(self):
            killed.append(self._n)
    import sys, types
    fake = types.ModuleType("psutil")
    fake.Process = lambda pid: _P({1: "notepad.exe", 2: "csrss.exe"}[pid])
    monkeypatch.setitem(sys.modules, "psutil", fake)
    n = js.kill_pids([1, 2])
    assert n == 1 and killed == ["notepad.exe"]