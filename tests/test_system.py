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