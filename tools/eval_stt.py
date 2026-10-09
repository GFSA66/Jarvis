#!/usr/bin/env python3
"""Оценка распознавания речи (STT) на наборе записанных команд.

Сравнивает движки (vosk / whisper / google / hybrid) и считает, какую долю фраз
каждый выводит верно. Оценка делается двумя способами:
  * по точному совпадению распознанного текста с ожидаемым (после нормализации);
  * по совпадению интента: сравниваем, какой интент даёт `jarvis_routing.diagnose`
    для ожидаемого и для распознанного текста (важнее побуквенной точности).

Формат датасета: папка с 16-кГц моно WAV; имя файла = ожидаемая фраза («__» вместо
пробелов, расширение отбрасывается). Либо dataset.json — список
[{"wav": "...", "text": "..."}].

Запуск:
    python tools/eval_stt.py путь/к/датасету
    python tools/eval_stt.py датасет --engines vosk,google
    python tools/eval_stt.py датасет --engine vosk --model large
    python tools/eval_stt.py датасет --save before.txt

Нужен как минимум один установленный бэкенд. Офлайн-модель качается при первом
запуске в ~/.jarvis/models; без интернета оценка офлайн-движков невозможна.
Отчёт печатается и сохраняется в tools/eval_stt_report.txt.
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

# репозиторий в sys.path, чтобы импортировать наши модули из tools/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jarvis_stt  # noqa: E402
import jarvis_routing  # noqa: E402


def _norm(text: str) -> str:
    return jarvis_routing.normalize(text)


def _intent(text: str) -> str:
    """Грубый интент по маршрутизатору: имя первой подошедшей команды или пусто."""
    try:
        _t, matches = jarvis_routing.diagnose(text)
        return matches[0].name if matches else ""
    except Exception:  # noqa: BLE001
        return ""


def read_wav(path: Path) -> tuple[bytes, int]:
    """Прочитать PCM (16-bit) из моно WAV и вернуть (данные, sample_rate)."""
    with wave.open(str(path), "rb") as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if channels != 1 or width != 2:
        raise ValueError(
            f"{path.name}: нужен моно 16-бит WAV (сейчас каналов={channels}, байт={width})")
    return raw, rate


def load_dataset(path: Path) -> list[tuple[Path, str]]:
    """Список (wav, ожидаемый текст) из папки, одиночного WAV или dataset.json."""
    items: list[tuple[Path, str]] = []
    if path.is_file() and path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data:
            items.append((path.parent / row["wav"], str(row.get("text", ""))))
        return items
    if path.is_file():
        return [(path, path.stem.replace("__", " ").replace("_", " "))]
    for wav in sorted(path.glob("*.wav")):
        items.append((wav, wav.stem.replace("__", " ").replace("_", " ").strip()))
    return items


def evaluate(engine, cfg, grammar, items):
    """Прогнать один движок по датасету; вернуть (строки, метрики, строки-данные)."""
    eng = jarvis_stt.STTEngine(cfg, grammar=grammar)
    lines: list[str] = []
    exact = intent_ok = total = 0
    rows = []
    for wav, expected in items:
        total += 1
        try:
            pcm, rate = read_wav(wav)
        except (ValueError, wave.Error) as e:
            lines.append(f"[skip] {e}")
            continue
        res = eng.transcribe(pcm, rate)
        got = res.text if not res.rejected else ""
        exp_n, got_n = _norm(expected), _norm(got)
        is_exact = bool(exp_n) and exp_n == got_n
        exp_int, got_int = _intent(expected), _intent(got)
        is_intent = bool(exp_int) and exp_int == got_int
        exact += int(is_exact)
        intent_ok += int(is_intent)
        flag = "OK " if is_intent else ("~  " if is_exact else "XX ")
        tail = f", отброшено: {res.rejected}" if res.rejected else ""
        lines.append(f"{flag}«{expected}» → «{got}» (conf {res.confidence:.2f}, "
                     f"{res.engine}{tail})")
        rows.append({"expected": expected, "got": got, "conf": round(res.confidence, 3),
                     "engine": res.engine, "rejected": res.rejected, "exact": is_exact,
                     "intent": is_intent, "expected_intent": exp_int, "got_intent": got_int})
    metrics = {"engine": engine, "total": total, "exact": exact, "intent_ok": intent_ok,
               "exact_pct": round(100 * exact / total, 1) if total else 0.0,
               "intent_pct": round(100 * intent_ok / total, 1) if total else 0.0}
    return lines, metrics, rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Оценка распознавания речи Джарвиса на WAV-наборе")
    ap.add_argument("dataset", help="папка с WAV, одиночный WAV или dataset.json")
    ap.add_argument("--engines", default="vosk,google",
                    help="движки через запятую: vosk,whisper,google,hybrid")
    ap.add_argument("--engine", help="один движок (переопределяет --engines)")
    ap.add_argument("--model", help="модель vosk: small|large")
    ap.add_argument("--whisper-model", help="модель whisper: small|medium")
    ap.add_argument("--confidence-min", type=float, help="порог уверенности")
    ap.add_argument("--save", help="сохранить отчёт в файл")
    args = ap.parse_args()

    dataset = Path(args.dataset)
    if not dataset.exists():
        print(f"Не найдено: {dataset}")
        return 2
    items = load_dataset(dataset)
    if not items:
        print("Датасет пуст — нет WAV-файлов.")
        return 2

    base_cfg: dict = dict(jarvis_stt.DEFAULTS)
    if args.model:
        base_cfg["model"] = args.model
    if args.whisper_model:
        base_cfg["whisper_model"] = args.whisper_model
    if args.confidence_min is not None:
        base_cfg["confidence_min"] = args.confidence_min

    # Грамматику Vosk строим из ожидаемых фраз датасета (эмуляция боевого словаря).
    words = {w for _, text in items for w in _norm(text).split()}
    grammar = jarvis_stt.build_grammar(words)

    engines = [args.engine] if args.engine else \
        [e.strip() for e in args.engines.split(",") if e.strip()]
    report: list[str] = []
    summary: list[dict] = []
    for engine in engines:
        cfg = dict(base_cfg, engine=engine)
        print(f"\n=== Движок: {engine} ===")
        try:
            lines, metrics, _rows = evaluate(engine, cfg, grammar, items)
        except jarvis_stt.STTError as e:
            print(f"  [пропуск] {e}")
            report.append(f"=== {engine}: пропуск ({e})")
            continue
        report.append(f"=== Движок: {engine} ===")
        report.extend(lines)
        report.append(
            f"ИТОГ {engine}: верный текст {metrics['exact']}/{metrics['total']} "
            f"({metrics['exact_pct']}%), верный интент {metrics['intent_ok']}/"
            f"{metrics['total']} ({metrics['intent_pct']}%)\n")
        summary.append(metrics)
        print("\n".join(lines))
        print(f"ИТОГ {engine}: текст {metrics['exact_pct']}%, интент {metrics['intent_pct']}%")

    print("\n===== Сравнение движков =====")
    header = f"{'движок':10} {'текст':>8} {'интент':>8}"
    report.append("\n===== Сравнение движков =====")
    report.append(header)
    print(header)
    print("-" * len(header))
    for m in summary:
        line = f"{m['engine']:10} {m['exact_pct']:>7}% {m['intent_pct']:>7}%"
        print(line)
        report.append(line)

    out = Path(args.save) if args.save else (Path(__file__).parent / "eval_stt_report.txt")
    out.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"\nОтчёт сохранён: {out}")
    if summary:
        best = max(summary, key=lambda m: m["intent_pct"])
        print(f"Лучший по интентам: {best['engine']} ({best['intent_pct']}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

