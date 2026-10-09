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


# --- питание ПК: высший приоритет, до «закрой …» ----------------------------

def test_power_intent_priority_phrases():
    assert routing.power_intent("выключи пк") == "shutdown"
    assert routing.power_intent("выключи компьютер") == "shutdown"
    assert routing.power_intent("выруби ноутбук") == "shutdown"
    assert routing.power_intent("перезагрузи компьютер") == "restart"
    assert routing.power_intent("заверши работу пк") == "shutdown"
    # искажения Google STT
    assert routing.power_intent("выключи пэка") == "shutdown"
    assert routing.power_intent("выключи пика") == "shutdown"
    assert routing.power_intent("выключи пк-а") == "shutdown"
    assert routing.power_intent("отмени выключение") == "cancel"
    assert routing.power_intent("режим сна") == "sleep"
    assert routing.power_intent("заблокируй пк") == "lock"


def test_power_intent_does_not_hijack_volume_and_timers():
    assert routing.power_intent("выключи звук") is None
    assert routing.power_intent("отмени таймер") is None
    assert routing.power_intent("закрой блокнот") is None
    assert routing.power_intent("") is None


def test_power_wins_over_close_in_diagnose():
    for phrase in ("выключи пк", "выключи компьютер", "перезагрузи пк"):
        _text, matches = routing.diagnose(phrase)
        assert matches[0].name.startswith("power:")


# --- закрытие окон: цель из фразы ------------------------------------------

def test_resolve_close_app_and_alias():
    aliases = {"блокнот": "notepad.exe"}
    req = routing.resolve_close("закрой блокнот пожалуйста", aliases)
    assert req["kind"] == "app" and req["target"] == "notepad.exe"
    req = routing.resolve_close("блокнот закрой", aliases)
    assert req["kind"] == "app" and req["target"] == "notepad.exe"


def test_resolve_close_never_targets_pc():
    for phrase in ("закрой пк", "закрой компьютер", "закрой ноутбук", "закрой систему"):
        req = routing.resolve_close(phrase)
        assert req["kind"] == "power_hint"
        assert "выключи компьютер" in req["message"]


def test_resolve_close_active_window_and_empty():
    assert routing.resolve_close("закрой это")["kind"] == "active"
    assert routing.resolve_close("закрой окно")["kind"] == "active"
    assert routing.resolve_close("закрой текущее окно")["kind"] == "active"
    assert routing.resolve_close("закрой")["kind"] == "error"
    assert routing.resolve_close("выключить")["kind"] == "error"
    assert routing.resolve_close("открой ютуб")["kind"] == "error"


def test_close_verb_exact_forms_only():
    assert routing.close_verb("закрой блокнот")
    assert routing.close_verb("блокнот закрой")
    assert routing.close_verb("закрыть блокнот")
    assert not routing.close_verb("закройщик смены")
    assert not routing.close_verb("открой блокнот")


# --- отрицания и рекомендации ----------------------------------------------

def test_negation_blocks_launches():
    for phrase in ("посоветуй игру, не киберпанк",
                   "во что поиграть кроме кс",
                   "не запускай майнкрафт",
                   "запусти всё кроме стима",
                   "во что мне лучше поиграть, только не киберпанк"):
        assert routing.launch_blocked(phrase), phrase
    for phrase in ("запусти киберпанк", "открой github", "запусти roblox"):
        assert not routing.launch_blocked(phrase), phrase


def test_negated_terms_in_negation_scope():
    assert routing.negated_terms("во что поиграть, только не киберпанк", ["киберпанк"]) == {"киберпанк"}
    assert routing.negated_terms("во что поиграть кроме кс", ["кс"]) == {"кс"}
    assert routing.negated_terms("не запускай майнкрафт", ["майнкрафт"]) == {"майнкрафт"}
    # «не киберпанк, а гта» — «гта» не в зоне отрицания
    assert routing.negated_terms("не киберпанк, а гта", ["киберпанк", "гта"]) == {"киберпанк"}


def test_chain_not_split_for_questions_and_negations():
    assert not routing.can_split_chain("во что поиграть, только не киберпанк")
    assert not routing.can_split_chain("не запускай майнкрафт")
    assert not routing.can_split_chain("какую игру посоветуешь")
    assert routing.can_split_chain("открой стим и заметки")
    assert routing.can_split_chain("запусти майнкрафт, потом музыку")


def test_filler_phrases_are_not_recommendations():
    for phrase in ("ну", "давай", "так", "ага", "сначала хочу все-таки подделывать"):
        assert not routing.is_recommendation(phrase), phrase