# Script to modify jarvis.py - add TTS duration estimation
import sys

with open("C:\\Users\\GF66s\\Downloads\\Jarvis\\jarvis.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find and replace the notify function
old_code = """def notify(message: str, ok: bool = True, force_speak: bool = False) -> None:
    print(((\"[ok] \" if ok else \"[!!] \") + message))
    if notifier:
        base = int(CFG.get(\"notifications\", {}).get(\"duration_ms\", 5000))
        notifier.show(message, ok, max(base, min(15000, 60 * len(message))))"""

new_code = """def _estimate_tts_duration(text: str, engine: str = None, rate: int = 175) -> int:
    \"\"\"Оцнет продолжительности речи в миллисекундах на основе количества слов и движка.\"\"\"
    if not text:
        return 0
    words = len(text.split())
    if words == 0:
        return 0
    
    if engine is None:
        engine = (CFG.get(\"voice\", {}).get(\"engine\") or \"piper\").lower()
    
    if engine == \"piper\":
        # Piper TTS: длина фонаем Determines скорость
        # length_scale 1.0 = нормальный темп (rate 175 wpm)
        wpm = rate
        if wpm <= 0:
            wpm = 175
        base_sec = (words / wpm) * 60
        # буфер на инициализацию и синтез модели
        return int(base_sec * 1000 * 1.2)
    
    elif engine == \"edge\":
        # Edge TTS - нейроголос Microsoft
        # Также ориентировано на ~150-175 wpm
        wpm = rate
        if wpm <= 0:
            wpm = 175
        base_sec = (words / wpm) * 60
        return int(base_sec * 1000 * 1.3)
    
    elif engine in (\"sapi\", \"windows\"):
        # Windows SAPI - классический TTS
        wpm = rate
        if wpm <= 0:
            wpm = 175
        base_sec = (words / wpm) * 60
        return int(base_sec * 1000 * 1.1)
    
    else:
        # fallback - простое приближение
        return max(3000, min(60000, 60 * len(text)))


def notify(message: str, ok: bool = True, force_speak: bool = False) -> None:
    print(((\"[ok] \" if ok else \"[!!] \") + message))
    if notifier:
        # Используем оценку длительности речи вместо фиксированного таймаута
        tts_engine = engine if engine else (CFG.get(\"voice\", {}).get(\"engine\") or \"piper\").lower()
        estimated_dur = _estimate_tts_duration(message, tts_engine)
        # Минимальное 3 сек, максимальное 60 сек
        base = max(3000, min(60000, estimated_dur))
        notifier.show(message, ok, base)"""

if old_code in content:
    new_content = content.replace(old_code, new_code)
    with open("C:\\Users\\GF66s\\Downloads\\Jarvis\\jarvis.py", "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Success! Modified notify function.")
else:
    print("Old code not found!")
    # Let's see what's actually there
    idx = content.find("def notify")
    if idx >= 0:
        print("Found notify at index:", idx)
        print("Context:")
        print(repr(content[idx:idx+500]))