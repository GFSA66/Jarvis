"""Оценка точности распознавания и маршрутизации на записанных фразах.

Сравнивает текущий Google-распознаватель с офлайн-движком Jarvis (Vosk/Whisper)
по метрике «доля верных интентов»: каждая фраза -> интент -> сверка с ожидаемым.

Запуск (из корня проекта):
    .venv\\Scripts\\python tools\\eval_stt.py                 # синтетика по умолчанию
    .venv\\Scripts\\python tools\\eval_stt.py --wav-dir tests/audio
    .venv\\Scripts\\python tools\\eval_stt.py --json tests/audio/labels.json

Формат --json: {"фраза": "ожидаемый интент", ...}. Для реальной оценки STT нужны
.wav-файлы (16 kHz, mono): tools/eval_stt.py прогонит их через выбранный движок
и сравнит распознанный интент с ожидаемым. Без wav оценивается только маршрутизация
по эталонному тексту (полезно для A/B «до/после» смены движка).
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jarvis_routing as routing  # noqa: E402
import jarvis_intents as ji  # noqa: E402
import jarvis_history as history  # noqa: E402

# Эталонные «сырые» фразы, которые Google часто коверкает, и их ожидаемый интент.
# Фразы взяты из ~/.jarvis/history.jsonl владельца (реальные сценарии).
GOLDEN = {
    "выключи компьютер": "shutdown",
    "выключи пк": "shutdown",
    "выключи ноутбук": "shutdown",
    "закрой блокнот": "close_app",
    "закрой ютуб": "close_app",
    "открой youtube": "open_site",
    "открой github": "open_site",
    "открой себя": "open_site",
    "запусти roblox": "steam_game",
    "сделай громче": "volume_up",
    "сделай тише": "volume_down",
    "ярче": "brightness_up",
    "напомни купить хлеб": "reminder",
    "поставь таймер на пять минут": "timer",
    "сделай заметку позвонить маме": "note",
    "следующий трек": "media_next",
    "стоп": "stop",
}

FILLERS = ["ну", "давай", "так", "ага", "сначала хочу все-таки подделывать"]

# Мини-реестр интентов, повторяющий группы из jarvis.py, чтобы оценка была
# независимой от запуска всего приложения (Windows/Tk не нужны).
GOLDEN_SAMPLE = [
    ji.Intent("shutdown", ("выключи",), 5),
    ji.Intent("close_app", ("закрой",), 10, pattern=r"\\bзакрой\\s+\\w+"),
    ji.Intent("open_site", ("открой",), 30, pattern=r"\\bоткрой\\s+\\w+"),
    ji.Intent("steam_game", ("запусти", "роблокс"), 32),
    ji.Intent("volume_up", ("громче",), 20),
    ji.Intent("volume_down", ("тише",), 20),
    ji.Intent("brightness_up", ("ярче",), 21),
    ji.Intent("reminder", ("напомни",), 51),
    ji.Intent("timer", ("таймер",), 52),
    ji.Intent("note", ("заметку",), 50),
    ji.Intent("media_next", ("следующий трек",), 22),
    ji.Intent("stop", ("стоп",), 5),
]


def intent_of(phrase: str) -> str:
    """Ожидаемый маршрут фразы (shutdown / игнор / имя интента).

    Болтовня/обрывки, которые не являются ни командой, ни вопросом, дают
    «ignore» — именно их реальный процесс молча пропускает (не адресовано,
    нет вопросительных слов). Раньше такие фразы давали «unknown», из-за чего
    оценка филлеров ошибочно падала.
    """
    if routing.power_intent(phrase):
        return "shutdown"
    if history.is_filler(phrase):
        return "ignore"
    if routing.is_recommendation(phrase):
        return "ai"
    hits = ji.match(phrase, GOLDEN_SAMPLE)
    if hits:
        return hits[0].intent.name
    # ни команда, ни вопрос, ни рекомендация → нечего выполнять
    return "ignore"


def transcribe_wav(path: Path, engine: str, model: str) -> tuple[str, float]:
    """Прогнать один wav через выбранный офлайн-движок (Vosk/Whisper)."""
    import jarvis_stt as stt  # noqa: PLC0415
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
    cfg = {"engine": engine, "model": model}
    eng = stt.STTEngine(cfg, grammar=[], language="ru-RU")
    res = eng.transcribe(pcm, rate)
    return res.text, res.confidence


def evaluate_stt(wav_dir: Path, engine: str, model: str, labels: dict) -> dict:
    """Точность STT: верных интентов / всего. Нужен только при наличии wav."""
    correct = total = 0
    for path in sorted(wav_dir.glob("*.wav")):
        expected = labels.get(path.name)
        if not expected:
            continue
        text, conf = transcribe_wav(path, engine, model)
        got = intent_of(text) if text else ""
        total += 1
        if got == expected:
            correct += 1
        print(f"  {path.name}: услышал «{text}» ({conf:.2f}) -> {got} "
              f"(ожидал {expected}) {'OK' if got == expected else 'X'}")
    acc = correct / total if total else 0.0
    return {"engine": engine, "correct": correct, "total": total, "accuracy": acc}


def evaluate_routing() -> dict:
    """Точность маршрутизации на эталонных текстах (без записи)."""
    correct = 0
    for phrase, expected in GOLDEN.items():
        got = intent_of(phrase)
        mark = "OK" if got == expected else "X"
        if got == expected:
            correct += 1
        print(f"  {mark} «{phrase}» -> {got} (ожидал {expected})")
    fillers_ok = all(intent_of(f) == "ignore" for f in FILLERS)
    print(f"Филлеры игнорируются: {'OK' if fillers_ok else 'X'}")
    return {"correct": correct, "total": len(GOLDEN), "fillers_ok": fillers_ok,
            "accuracy": correct / len(GOLDEN)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Оценка распознавания и маршрутизации Jarvis")
    ap.add_argument("--wav-dir", type=Path, help="папка с .wav (16 kHz, моно) для оценки STT")
    ap.add_argument("--json", dest="labels", type=Path,
                    help="json: {имя.wav: ожидаемый интент}")
    ap.add_argument("--engine", default="vosk", help="движок STT: vosk|whisper|google")
    ap.add_argument("--model", default="small", help="модель (small|large)")
    args = ap.parse_args()

    print("== Маршрутизация (эталонные тексты) ==")
    r = evaluate_routing()
    print(f"Итог маршрутизации: {r['correct']}/{r['total']} ({r['accuracy']:.0%})\n")

    if args.wav_dir and args.wav_dir.is_dir():
        labels = {}
        if args.labels and args.labels.is_file():
            labels = json.loads(args.labels.read_text(encoding="utf-8"))
        else:
            print("(нет labels.json — сверять не с чем, wav пропущены)")
        if labels:
            print(f"== STT ({args.engine}/{args.model}) на записях ==")
            s = evaluate_stt(args.wav_dir, args.engine, args.model, labels)
            print(f"Итог STT: {s['correct']}/{s['total']} ({s['accuracy']:.0%})")
    else:
        print("Для оценки самого распознавания дай --wav-dir с записями и --json метками.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
