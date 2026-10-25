with open("jarvis_settings.py", encoding="utf-8") as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    if '"voice":' in line or '"enabled": bool(self.sw_voice.get())' in line or 'delay = int(self.v_delay' in line:
        print(f"{i}: {line.rstrip()}")