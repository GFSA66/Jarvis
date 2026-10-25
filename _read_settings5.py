with open("jarvis_settings.py", encoding="utf-8") as f:
    lines = f.readlines()
    for i, line in enumerate(lines, 1):
        if "_general_form" in line or "def _build_commands" in line or "def _commands_form" in line or "v_commands" in line.lower() or "\"commands\"" in line:
            print(i, line.rstrip())