with open("jarvis.py", encoding="utf-8") as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    if "def cmd_voice(t):" in line:
        print(f"FOUND at {i}: {line.rstrip()}")
        for j in range(i, min(i+5, len(lines))):
            print(f"  {j+1}: {lines[j].rstrip()}")