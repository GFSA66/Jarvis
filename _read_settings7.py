with open("jarvis_settings.py", encoding="utf-8") as f:
    lines = f.readlines()
    for i, line in enumerate(lines, 1):
        if "self.sw_voice" in line or "self.v_engine" in line or "self.v_piper" in line or "self.v_delay" in line or "\"voice\"" in line:
            print(i, line.rstrip())