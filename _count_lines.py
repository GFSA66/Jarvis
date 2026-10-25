for fn in ["jarvis_settings.py", "jarvis.py"]:
    with open(fn, encoding="utf-8") as f:
        print(fn, len(f.readlines()))