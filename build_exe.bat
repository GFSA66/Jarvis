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
rem --noconsole: no black window (errors go to %USERPROFILE%\.jarvis\errors.log). Remove it to debug.
set "ICON_ARGS="
if exist "jarvis.ico" set "ICON_ARGS=--icon jarvis.ico --add-data jarvis.ico;."
if not exist "jarvis.ico" echo [Jarvis] jarvis.ico not found - building with the default icon.

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
    --name Jarvis ^
    %ICON_ARGS% ^
    --collect-all customtkinter ^
    --collect-all speech_recognition ^
    --collect-data ytmusicapi ^
    --hidden-import pyaudiowpatch ^
    --hidden-import pyttsx3.drivers ^
    --hidden-import pyttsx3.drivers.sapi5 ^
    --hidden-import win32timezone ^
    jarvis.py || goto :fail

echo.
echo [Jarvis] Done: dist\Jarvis.exe
echo Put config.json next to it if you need one, then run it.
goto :end

:fail
echo.
echo [Jarvis] Build failed. Python 3.10-3.13 is required (3.14 is not supported yet).
echo If this window closes by itself, run the .bat from cmd.

:end
pause
