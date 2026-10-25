with open("jarvis.py", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        if "def cmd_custom" in line:
            print(i, line.rstrip())
        if "CFG[\"commands\"]" in line:
            print(i, line.rstrip())
        if "def commands_text" in line:
            print(i, line.rstrip())
        if "def _settings_commands" in line:
            print(i, line.rstrip())