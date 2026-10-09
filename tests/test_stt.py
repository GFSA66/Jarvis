"""STT-слой: VAD, грамматика, цепочка бэкендов и фильтрация мусора."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jarvis_stt as stt  # noqa: E402


def test_defaults_merge_for_old_config():
    eng = stt.STTEngine({})  # старый config.json без секции «stt»
    assert eng.cfg["engine"] == "vosk"
    assert eng.confidence_min() == 0.35


def test_build_grammar_filters_garbage():
    words = ["Открой", "стим", "a", "12", "блокнот", "блокнот", "hi-fi", "юTube!"]
    gram = stt.build_grammar(words)
    # дедуп, без мусора (короткие/с посторонними символами отбрасываются)
    assert gram == ["открой", "стим", "блокнот", "hi-fi"]


def test_vad_detects_speech_start_and_end():
    vad = stt.StreamVAD(margin=2.0, min_rms=300.0, silence_frames=3, min_speech_frames=2)
    # тишина адаптируется
    for _ in range(5):
        assert vad.feed(100.0) == "silence"
    # два чанка речи — начало фразы (первый — накопление, второй — «speech»)
    assert vad.feed(3000.0) is None
    assert vad.feed(3000.0) == "speech"
    # короткая пауза — речь ещё идёт
    assert vad.feed(100.0) is None
    # длинная пауза — конец фразы
    end = None
    for _ in range(3):
        end = vad.feed(100.0)
    assert end == "silence"


def test_vad_adapts_to_noisy_room():
    vad = stt.StreamVAD(margin=2.0, min_rms=300.0)
    # шум на грани порога: адаптивная оценка тишины растёт, порог поднимается
    for _ in range(100):
        vad.feed(500.0)
    assert vad.threshold > 900.0
    # 700 теперь уже тишина, а не речь
    assert vad.feed(700.0) == "silence"


def _fake_backend(name, text, conf, errors=None):
    class B:
        pass
    b = B()
    b.name = name

    def transcribe(pcm, rate):
        if errors:
            raise errors
        return text, conf
    b.transcribe = transcribe
    return b


def test_engine_low_confidence_marks_rejected(monkeypatch):
    eng = stt.STTEngine({"engine": "google", "confidence_min": 0.5})
    monkeypatch.setattr(stt, "GoogleBackend", lambda lang="ru-RU": _fake_backend("google", "да", 0.3))
    res = eng.transcribe(b"\x00" * 100, 16000)
    assert res.rejected.startswith("уверенность")


def test_engine_hybrid_falls_back_when_vosk_fails(monkeypatch):
    eng = stt.STTEngine({"engine": "hybrid", "confidence_min": 0.3})
    monkeypatch.setattr(stt, "VoskBackend",
                        lambda cfg, grammar=None, use_grammar=True: _fake_backend(
                            "vosk", "", 0.0,
                            errors=stt.STTError("нет модели")))
    monkeypatch.setattr(stt, "GoogleBackend",
                        lambda lang="ru-RU": _fake_backend("google", "открой стим", 0.8))
    res = eng.transcribe(b"\x00" * 100, 16000)
    assert res.text == "открой стим" and res.engine == "google" and not res.rejected


def test_engine_silence_rejected(monkeypatch):
    eng = stt.STTEngine({"engine": "google"})
    monkeypatch.setattr(stt, "GoogleBackend", lambda lang="ru-RU": _fake_backend("google", "", 0.0))
    res = eng.transcribe(b"\x00" * 100, 16000)
    assert res.rejected == "тишина"


def test_ensure_model_error_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(stt, "models_dir", lambda cfg=None: tmp_path)
    def boom(url, dest, log=None):
        raise OSError("network down")
    monkeypatch.setattr(stt, "_download", boom)
    try:
        stt.ensure_vosk_model("small", {})
    except stt.STTError as e:
        assert "интернет" in str(e)
    else:
        raise AssertionError("должен быть STTError")
