with open("jarvis_settings.py", encoding="utf-8") as f:
    lines = f.readlines()
    for i in range(700, 780):
        if i <= len(lines):
            print(f"{i}: {lines[i-1].rstrip()}")