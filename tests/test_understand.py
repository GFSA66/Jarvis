"""Чистые регрессии общего лексикона и фонетического понимания."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jarvis_understand as understand  # noqa: E402


CFG = {
    "system": {"app_aliases": {"блокнот": "notepad.exe", "обс": "obs64.exe"}},
    "paths": {"vlc": r"C:\Program Files\VideoLAN\VLC\vlc.exe"},
    "games": {"Counter-Strike 2": 730, "Minecraft": 10},
    "sites": {"гитхаб": "https://github.com", "ютуб": "https://youtube.com"},
    "urls": {"films": "https://example.invalid/films"},
    "commands": [{"phrase": "мой сервер", "target": "ssh.exe"}],
    "pronunciations": {"с ним": {"target": "app:steam", "count": 4}},
}


def _lexicon():
    return understand.build_lexicon(CFG, {"folders": {"загрузки": r"C:\Users\me\Downloads"},
                                          "running": ["steam.exe"], "recent": ["app:steam"]})


def test_lexicon_is_built_from_all_config_sources():
    entries = {e.id: e for e in _lexicon().entries}
    assert "app:блокнот" in entries
    assert "app:обс" in entries
    assert "app:vlc" in entries
    assert "game:730" in entries
    assert "site:гитхаб" in entries
    assert "command:мой сервер" in entries
    assert "folder:загрузки" in entries


def test_spoken_forms_are_generated_not_hand_written_per_object():
    forms = understand.spoken_forms("Counter-Strike 2")
    assert "counter strike 2" in forms
    assert "коунтер-стрике 2" in forms
    assert "cs2" in forms
    assert any("два" in form for form in forms)
    assert "vlc" in understand.spoken_forms("VLC")
    assert any("эл" in form for form in understand.spoken_forms("VLC"))


def test_universal_phonetic_key_handles_joining_translit_and_voicing():
    assert understand.phonetic_similarity("steam", "стим") > 0.70
    assert understand.phonetic_similarity("сним", "стим") > 0.70
    assert understand.phonetic_similarity("дискорд", "discord") > 0.70
    assert understand.phonetic_similarity("хром", "chrome") > 0.55


def test_slot_space_is_restricted_by_verb_kind():
    lexicon = _lexicon()
    d = understand.understand([("закрой гитхаб", 0.95, "vosk")], cfg=CFG, lexicon=lexicon)
    assert d.action == "ignore"  # сайт нельзя «закрыть» как процесс без окна
    d = understand.understand([("открой гитхаб", 0.95, "vosk")], cfg=CFG, lexicon=lexicon)
    assert d.intent == "open" and d.slot_id == "site:гитхаб"


def test_multihypothesis_consensus_selects_known_object():
    d = understand.understand([
        ("закрой с ним", 0.62, "vosk"),
        ("закрой стим", 0.79, "google"),
        ("закрой ским", 0.64, "whisper"),
    ], cfg=CFG, lexicon=_lexicon())
    assert d.intent == "close"
    assert d.slot_id == "app:steam"
    assert d.action in ("execute", "confirm")


def test_medium_risk_low_confidence_requires_confirmation_or_clarification():
    d = understand.understand([("закрой блокнот", 0.45, "vosk")], cfg=CFG, lexicon=_lexicon())
    assert d.action in ("confirm", "clarify", "ignore")
    d = understand.understand([("открой блокнот", 0.95, "vosk")], cfg=CFG, lexicon=_lexicon())
    assert d.action == "execute"


def test_generated_coverage_has_all_actionable_entries():
    rows = understand.generated_phrases(_lexicon())
    covered = {(intent, slot) for _phrase, intent, slot in rows}
    for entry in _lexicon().entries:
        for action in entry.actions & {"open", "launch", "close", "search"}:
            assert (action, entry.id) in covered