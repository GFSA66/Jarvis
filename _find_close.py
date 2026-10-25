with open("jarvis.py", encoding="utf-8") as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    if 'close_verb(text)' in line or 'resolve_close(text, aliases)' in line or 'cmd_close_discord(text)' in line:
        print(f"{i}: {line.rstrip()}")