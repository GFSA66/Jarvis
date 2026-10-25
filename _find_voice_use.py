import re
with open("jarvis.py", encoding="utf-8") as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    s = line.rstrip()
    if re.search(r'speaker\s*=|piper_voice|sapi|engine|runAndWait|setProperty', s) or re.search(r'volume', s, re.I):
        print(f"{i}: {s}")