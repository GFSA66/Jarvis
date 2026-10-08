"""Регрессии диагностики приоритета команд, без Windows."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jarvis_routing as routing  # noqa: E402


def test_clipboard_variants_route_to_clipboard():
    for phrase in ("прочитай выделенное", "прочти выделенный текст", "озвучь выделенное",
                   "читай выделенное", "прочитай буфер", "что в буфере", "озвучь буфер"):
        _text, matches = routing.diagnose(phrase)
        assert matches[0].name == "clipboard"


def test_close_beats_custom_application_command():
    commands = [{"phrase": "блокнот", "target": "notepad.exe"}]
    for phrase in ("закрой блокнот", "закрой блокнот пожалуйста", "блокнот закрой", "закрыть блокнот"):
        _text, matches = routing.diagnose(phrase, commands)
        assert matches[0].name == "close_any"


def test_dice_and_media_are_not_intercepted():
    assert routing.diagnose("брось 5д20")[1][0].name == "dice"
    for phrase in ("следующий трек", "дальше песня", "вперед трек",
                   "предыдущий трек", "прошлая песня", "назад трек", "верни трек"):
        assert routing.diagnose(phrase)[1][0].name == "media"


def test_diagnosis_includes_normalization_index_name_and_reason():
    text = routing.format_diagnosis("  ПРОЧТИ   ВЫДЕЛЕННОЕ! ")
    assert "Нормализовано: прочти выделенное" in text
    assert "#0 clipboard" in text
    assert "основа чтения буфера/выделения" in text