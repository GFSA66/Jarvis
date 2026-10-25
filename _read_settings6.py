with open("jarvis_settings.py", encoding="utf-8") as f:
    lines = f.readlines()
    for i, line in enumerate(lines, 1):
        if "def _build" in line or "def _general_form" in line or "return {" in line and "voice" in line.lower():
            print(i, line.rstrip())