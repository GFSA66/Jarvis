@echo off
cd /d "%~dp0"

rem Pick a tested Python (3.13 -> 3.10). The newest (3.14) often has no wheels for PyAudioWPatch/pywin32.
set "PY="
for %%V in (3.13 3.12 3.11 3.10) do if not defined PY (py -%%V -c "" >nul 2>&1 && set "PY=py -%%V")
if not defined PY (where python >nul 2>&1 && set "PY=python")
if not defined PY goto :fail
echo [Jarvis] Python: %PY%

if not exist ".venv\Scripts\python.exe" (
    echo [Jarvis] Creating environment and installing dependencies...
    %PY% -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)

".venv\Scripts\python.exe" -m pip install pyinstaller || goto :fail

rem jarvis.ico next to this file is used as the exe icon. Without it the exe is built with the default icon.
rem --collect-all customtkinter: the library keeps themes and fonts in its own files; without them the settings window will not open.
rem --collect-all piper: includes bundled espeak-ng-data phoneme tables required by Piper at runtime.
rem --noconsole: no black window (errors go to %USERPROFILE%\.jarvis\errors.log). Remove it to debug.
set "ICON_ARGS="
if exist "jarvis.ico" set "ICON_ARGS=--icon jarvis.ico --add-data jarvis.ico;."
if not exist "jarvis.ico" echo [Jarvis] jarvis.ico not found - building with the default icon.

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
    --name Jarvis ^
    %ICON_ARGS% ^
    --collect-all customtkinter ^
    --collect-all speech_recognition ^
    --collect-all vosk ^
    --collect-all faster_whisper ^
    --collect-all ctranslate2 ^
    --collect-all piper ^
    --collect-all onnxruntime ^
    --collect-all audioop ^
    --collect-all edge_tts ^
    --collect-data ytmusicapi ^
    --collect-data jarvis_settings ^
    --collect-data jarvis_utils ^
    --collect-data jarvis_system ^
    --collect-data jarvis_timers ^
    --collect-data jarvis_integrations ^
    --hidden-import pyaudiowpatch ^
    --hidden-import pyttsx3.drivers ^
    --hidden-import pyttsx3.drivers.sapi5 ^
    --hidden-import onnxruntime ^
    --hidden-import onnxruntime.capi._pybind_state ^
    --hidden-import faster_whisper ^
    --hidden-import ctranslate2 ^
    --hidden-import numpy ^
    --hidden-import av ^
    --hidden-import win32timezone ^
    --hidden-import pycaw ^
    --hidden-import comtypes ^
    --hidden-import comtypes.gen ^
    --hidden-import psutil ^
    --hidden-import screen_brightness_control ^
    --hidden-import keyring ^
    --hidden-import requests ^
    --hidden-import jarvis_utils ^
    --hidden-import jarvis_system ^
    --hidden-import jarvis_timers ^
    --hidden-import jarvis_integrations ^
    --hidden-import jarvis_stt ^
    --hidden-import jarvis_intents ^
    --hidden-import jarvis_routing ^
    --hidden-import jarvis_history ^
    --hidden-import audioop ^
    --hidden-import jarvis_voice_piper ^
    --hidden-import jarvis_voice_edge ^
    --hidden-import edge_tts ^
    --hidden-import jarvis_dictation ^
    jarvis.py jarvis_voice_piper.py jarvis_voice_edge.py jarvis_dictation.py jarvis_stt.py jarvis_intents.py jarvis_routing.py jarvis_history.py || goto :fail

echo.
echo [Jarvis] Done: dist\Jarvis.exe
rem Sources next to the exe: Jarvis can edit his own code in dist\src (rebuild after changes).
rem STT models are NOT bundled into the exe: vosk/whisper models download on first
rem run into %USERPROFILE%\.jarvis\models and stay outside the build (keeps exe small).
if not exist "dist\src" mkdir "dist\src"
copy /y "jarvis.py" "dist\src\" >nul
copy /y "jarvis_ai.py" "dist\src\" >nul
copy /y "jarvis_voice_piper.py" "dist\src\" >nul
copy /y "jarvis_voice_edge.py" "dist\src\" >nul
copy /y "jarvis_settings.py" "dist\src\" >nul
copy /y "jarvis_utils.py" "dist\src\" >nul
copy /y "jarvis_system.py" "dist\src\" >nul
copy /y "jarvis_timers.py" "dist\src\" >nul
copy /y "jarvis_integrations.py" "dist\src\" >nul
copy /y "jarvis_stt.py" "dist\src\" >nul
copy /y "jarvis_intents.py" "dist\src\" >nul
copy /y "jarvis_routing.py" "dist\src\" >nul
copy /y "jarvis_history.py" "dist\src\" >nul
copy /y "config.example.json" "dist\src\" >nul
copy /y "requirements.txt" "dist\src\" >nul
copy /y "build_exe.bat" "dist\src\" >nul
copy /y "README.md" "dist\src\" >nul
echo [Jarvis] Sources copied to dist\src - edit them, copy back to the project folder
echo           and run build_exe.bat again to rebuild the exe.
echo Put config.json next to it if you need one, then run it.
goto :end

:fail
echo.
echo [Jarvis] Build failed. Python 3.10-3.13 is required (3.14 is not supported yet).
echo If this window closes by itself, run the .bat from cmd.

:end
pause