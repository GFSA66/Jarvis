#!/usr/bin/env python
# Fix the notify function - remove undefined 'engine' variable reference

with open("C:\\Users\\GF66s\\Downloads\\Jarvis\\jarvis.py", "r", encoding="utf-8") as f:
    content = f.read()

old_code = """def notify(message: str, ok: bool = True, force_speak: bool = False) -> None:
    print(((\"[ok] \" if ok else \"[!!] \") + message))
    if notifier:
        # Используем оценку длительности речи вместо фиксированного таймаута
        tts_engine = engine if engine else (CFG.get("voice", {}).get("engine") or "piper").lower()
        estimated_dur = _estimate_tts_duration(message, tts_engine)
        # Минимальное 3 сек, максимальное 60 сек
        base = max(3000, min(60000, estimated_dur))
        notifier.show(message, ok, base)"""

new_code = """def notify(message: str, ok: bool = True, force_speak: bool = False) -> None:
    print(((\"[ok] \" if ok else \"[!!] \") + message))
    if notifier:
        # Используем оценку длительности речи вместо фиксированного таймаута
        tts_engine = (CFG.get("voice", {}).get("engine") or "piper").lower()
        estimated_dur = _estimate_tts_duration(message, tts_engine)
        # Минимальное 3 сек, максимальное 60 сек
        base = max(3000, min(60000, estimated_dur))
        notifier.show(message, ok, base)"""

if old_code in content:
    new_content = content.replace(old_code, new_code)
    with open("C:\\Users\\GF66s\\Downloads\\Jarvis\\jarvis.py", "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Success! Fixed notify function.")
else:
    print("Old code not found!")