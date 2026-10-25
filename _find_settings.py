with open("jarvis_settings.py", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        low = line.lower()
        if "command" in low and ("field" in low or "entry" in low or "button" in low or "switch" in low or "slider" in low):
            print(i, line.rstrip())