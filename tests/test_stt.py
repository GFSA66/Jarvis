"""STT-слой: VAD, грамматика, цепочка бэкендов и фильтрация мусора."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jarvis_stt as stt  # noqa: E402


def _fake_vosk_module(payload):
    """Собрать заглушку пакета vosk, чей FinalResult отдаёт payload."""
    import json  # noqa: PLC0415

    class Mod:
        @staticmethod
        def SetLogLevel(level):
            pass

        class Model:
            def __init__(self, path):
                pass

        class Rec:
            def __init__(self, model, rate, grammar=""):
                pass

            def SetWords(self, flag):
                pass

            def Reset(self):
                pass

            def AcceptWaveform(self, pcm):
                pass

            def FinalResult(self):
                return json.dumps(payload, ensure_ascii=False)

        SetLogLevel = SetLogLevel
        Model = Model
        KaldiRecognizer = Rec

    return Mod


def test_vosk_confidence_from_word_confs(monkeypatch):
    """Уверенность = среднее conf по словам (FinalResult без верхнеуровневого confidence)."""
    import sys  # noqa: PLC0415
    monkeypatch.setattr(stt, "ensure_vosk_model", lambda model, cfg: "x")
    payload = {"text": "выключи компьютер",
               "result": [{"word": "выключи", "conf": 0.9},
                          {"word": "компьютер", "conf": 0.7}]}
    monkeypatch.setitem(sys.modules, "vosk", _fake_vosk_module(payload))
    backend = stt.VoskBackend({"model": "small"}, grammar=["выключи", "компьютер"])
    text, conf = backend.transcribe(b"", 16000)
    assert text == "выключи компьютер"
    assert abs(conf - 0.8) < 1e-9, conf


def test_vosk_text_without_word_conf_defaults(monkeypatch):
    """Текст есть, но conf по словам нет — дефолт 0.7 (не 0), чтобы не резало всё."""
    import sys  # noqa: PLC0415
    monkeypatch.setattr(stt, "ensure_vosk_model", lambda model, cfg: "x")
    payload = {"text": "джарвис", "result": []}
    monkeypatch.setitem(sys.modules, "vosk", _fake_vosk_module(payload))
    backend = stt.VoskBackend({"model": "small"}, grammar=["джарвис"])
    text, conf = backend.transcribe(b"", 16000)
    assert text == "джарвис"
    assert conf == 0.7, conf


def test_vosk_recognizer_reused_between_phrases(monkeypatch):
    """Recognizer переиспользуется между фразами: Kaldi строит грамматику один раз.

    Иначе на каждую фразу он заново строит FST и сыплет «Ignoring word missing
    in vocabulary» на каждое слово списка — консоль заваливается warning'ами.
    """
    import sys  # noqa: PLC0415
    created = []
    resets = []

    class Mod:
        @staticmethod
        def SetLogLevel(level):
            pass

        class Model:
            def __init__(self, path):
                pass

        class Rec:
            def __init__(self, model, rate, grammar=""):
                created.append(rate)

            def SetWords(self, flag):
                pass

            def Reset(self):
                resets.append(1)

            def AcceptWaveform(self, pcm):
                pass

            def FinalResult(self):
                return '{"text": "привет", "result": []}'

        SetLogLevel = SetLogLevel
        Model = Model
        KaldiRecognizer = Rec

    monkeypatch.setattr(stt, "ensure_vosk_model", lambda model, cfg: "x")
    monkeypatch.setitem(sys.modules, "vosk", Mod)
    backend = stt.VoskBackend({"model": "small"}, grammar=["привет"])
    for _ in range(3):
        assert backend.transcribe(b"", 16000) == ("привет", 0.7)
    # три фразы — один созданный recognizer, но три сброса состояния
    assert created == [16000]
    assert len(resets) == 3


def test_defaults_merge_for_old_config():
    eng = stt.STTEngine({})  # старый config.json без секции «stt»
    assert eng.cfg["engine"] == "vosk"
    assert eng.confidence_min() == 0.35


def test_build_grammar_filters_garbage():
    words = ["Открой", "стим", "a", "12", "блокнот", "блокнот", "hi-fi", "юTube!",
             "bяркость", "bнапомни"]
    gram = stt.build_grammar(words)
    # дедуп, без мусора (короткие/посторонние символы/смесь латиницы и кириллицы)
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


# ---------------------------------------------------------------------------
# Регрессия: выбор движка и обрезка многословных команд
# ---------------------------------------------------------------------------

def test_chain_table_defaults_and_fallback():
    """Цепочка бэкендов: дефолт + страховка запасными, неизвестный движок → дефолт."""
    assert stt.STTEngine({"engine": "vosk"})._chain() == ["vosk", "google"]
    assert stt.STTEngine({"engine": "google"})._chain() == ["google", "vosk"]
    assert stt.STTEngine({"engine": "hybrid"})._chain() == ["vosk", "vosk_plain", "google"]
    assert stt.STTEngine({"engine": "whisper"})._chain() == ["whisper", "vosk", "google"]
    # неизвестный/битый движок в старом конфиге — молча дефолт, а не падение
    assert stt.STTEngine({"engine": "непонятно"})._chain() == ["vosk", "google"]


def test_unknown_engine_in_config_falls_back_to_vosk(monkeypatch):
    eng = stt.STTEngine({"engine": "непонятно", "confidence_min": 0.3})
    monkeypatch.setattr(stt, "VoskBackend",
                        lambda cfg, grammar=None, use_grammar=True:
                        _fake_backend("vosk", "стоп", 0.9))
    res = eng.transcribe(b"\x00" * 100, 16000)
    assert res.text == "стоп" and res.engine == "vosk" and not res.rejected


def test_whisper_unavailable_falls_back_to_vosk(monkeypatch):
    """Выбран whisper, но пакет не установлен → работаем на запасном (vosk), без ошибки.

    Раньше это давало «Распознавание недоступно» на каждой фразе и Джарвис не реагировал.
    """
    eng = stt.STTEngine({"engine": "whisper", "confidence_min": 0.3})
    monkeypatch.setattr(stt, "WhisperBackend",
                        lambda cfg, prompt="":
                        _fake_backend("whisper", "", 0.0,
                                      errors=stt.STTError("Бэкенд whisper не установлен: pip install faster-whisper")))
    monkeypatch.setattr(stt, "VoskBackend",
                        lambda cfg, grammar=None, use_grammar=True:
                        _fake_backend("vosk", "открой настройки", 0.9))
    res = eng.transcribe(b"\x00" * 100, 16000)
    assert res.text == "открой настройки" and res.engine == "vosk" and not res.rejected


def test_engine_vosk_grammar_off_by_default(monkeypatch):
    """По умолчанию vosk распознаёт свободно (без жёсткой грамматики).

    Иначе многословные команды («открой настройки», «выключи компьютер»)
    обрубались до одного слова из списка грамматики.
    """
    eng = stt.STTEngine({"engine": "vosk"})
    seen = {}

    def fake_vosk(cfg, grammar=None, use_grammar=True):
        seen["use_grammar"] = use_grammar
        return _fake_backend("vosk", "открой настройки", 0.9)

    monkeypatch.setattr(stt, "VoskBackend", fake_vosk)
    eng.transcribe(b"\x00" * 100, 16000)
    assert seen.get("use_grammar") is False


def test_engine_vosk_grammar_on_when_enabled(monkeypatch):
    """Если в настройках включить stt.grammar — грамматика снова применяется."""
    eng = stt.STTEngine({"engine": "vosk", "grammar": True})
    seen = {}

    def fake_vosk(cfg, grammar=None, use_grammar=True):
        seen["use_grammar"] = use_grammar
        return _fake_backend("vosk", "пауза", 0.9)

    monkeypatch.setattr(stt, "VoskBackend", fake_vosk)
    eng.transcribe(b"\x00" * 100, 16000)
    assert seen.get("use_grammar") is True
