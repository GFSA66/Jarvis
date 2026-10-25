with open("jarvis_settings.py", encoding="utf-8") as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    if "self.t_cmd" in line or "self.t_games" in line or "self.t_sites" in line or "_build_table" in line or "def _build_table" in line:
        print(f"{i}: {line.rstrip()}")