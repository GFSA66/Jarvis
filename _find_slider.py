with open("jarvis_settings.py", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        if "CTkSlider" in line or "slider" in line.lower():
            print(i, line.rstrip())