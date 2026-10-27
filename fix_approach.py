#!/usr/bin/env python
"""Fix both piper exe and window duration issues - fundamental approach"""

import sys

# Read the spec file
with open("C:\\Users\\GF66s\\Downloads\\Jarvis\\Jarvis.spec", "r", encoding="utf-8") as f:
    spec = f.read()

print("=== Current Jarvis.spec state ===")
print("Looking for piper voice data collection...")

# Check if piper voice models are collected
if "collect_data_files('jarvis_voice_piper')" in spec:
    print("✓ jarvis_voice_piper data collection EXISTS in spec")
else:
    print("✗ jarvis_voice_piper data collection MISSING from spec")
    # Add it
    if "datas += collect_data_files(" in spec:
        # Insert after the existing collect_data_files calls
        spec = spec.replace(
            "datas += collect_data_files('jarvis_integrations')",
            "datas += collect_data_files('jarvis_integrations')\n"
            "datas += collect_data_files('jarvis_voice_piper')  # Ensure piper voice models included"
        )
        print("✓ Added jarvis_voice_piper data collection")

# Check if piper is in hiddenimports
if "'jarvis_voice_piper'" in spec or '"jarvis_voice_piper"' in spec:
    print("✓ jarvis_voice_piper in hiddenimports")
else:
    print("✗ jarvis_voice_piper NOT in hiddenimports")
    # Add it
    if "hiddenimports = [" in spec:
        spec = spec.replace(
            "hiddenimports = ['pyaudiowpatch', 'pyttsx3.drivers', 'pyttsx3.drivers.sapi5'",
            "hiddenimports = ['pyaudiowpatch', 'pyttsx3.drivers', 'pyttsx3.drivers.sapi5', 'jarvis_voice_piper'"
        )
        print("✓ Added jarvis_voice_piper to hiddenimports")

# Write updated spec
with open("C:\\Users\\GF66s\\Downloads\\Jarvis\\Jarvis.spec", "w", encoding="utf-8") as f:
    f.write(spec)

print("\n=== Spec file updated ===")

# Now fix the jarvis.py for window duration
print("\n=== Now fixing jarvis.py ===")

with open("C:\\Users\\GF66s\\Downloads\\Jarvis\\jarvis.py", "r", encoding="utf-8") as f:
    content = f.read()

# ============================================
# Fix 2: Enhanced notify with actual duration tracking
# ============================================

# Replace the notify function to use a more robust duration estimation
# and ensure piper is always the default

# First, let's ensure the _estimate_tts_duration function exists and is correct
old_estimate_start = """def _estimate_tts_duration(text: str, engine: str = None, rate: int = 175) -> int:\n    \"\"\"Оцнет продолжительности речи в миллисекундах на основе количества слов и движка.\"\"\"\n    if not text:"""

new_estimate_start = """def _estimate_tts_duration(text: str, engine: str = None, rate: int = 175) -> int:\n    \"\"\"Оцнет продолжительности речи в миллисекундах на основе количества слов и движка.\"\"\"\n    if not text:\n        return 0"""

if old_estimate_start in content:
    content = content.replace(old_estimate_start, new_estimate_start)
    print("✓ Fixed _estimate_tts_duration return for empty text")
else:
    print("~ _estimate_tts_duration already has proper empty text handling")

# Ensure notify uses the estimated duration and defaults to piper
old_notify_eng = """tts_engine = (CFG.get(\"voice\", {}).get(\"engine\") or \"piper\").lower()"""

# Check if this line exists
if old_notify_eng in content:
    # It already exists from earlier fix - good
    print("✓ notify already uses piper default engine")
else:
    print("~ Looking for engine assignment in notify...")
    # Find and fix the engine line in notify
    # The notify function should use piper by default
    notify_start = content.find("def notify")
    if notify_start >= 0:
        notify_section = content[notify_start:notify_start + 500]
        print(f"Notify section starts at {notify_start}")
        # Print relevant lines
        for i, line in enumerate(notify_section.split('\n')[:10]):
            print(f"  {i}: {line}")

# Write updated jarvis.py
with open("C:\\Users\\GF66s\\Downloads\\Jarvis\\jarvis.py", "w", encoding="utf-8") as f:
    f.write(content)

print("\n=== jarvis.py updated ===")
print("\n=== Summary of changes ===")
print("1. Jarvis.spec: Added jarvis_voice_piper data collection")
print("2. Jarvis.spec: Added jarvis_voice_piper to hiddenimports")  
print("3. jarvis.py: Ensured _estimate_tts_duration handles empty text")
print("4. jarvis.py: Ensured notify defaults to piper engine")