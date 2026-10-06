@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Берём проверенную версию Python (3.13 -> 3.10). Самая новая (3.14) часто без готовых пакетов для PyAudioWPatch/pywin32.
set "PY="
for %%V in (3.13 3.12 3.11 3.10) do if not defined PY (py -%%V -c "" >nul 2>&1 && set "PY=py -%%V")
if not defined PY (where python >nul 2>&1 && set "PY=python")
if not defined PY goto :fail
echo [Jarvis] Python: %PY%

if not exist ".venv\Scripts\python.exe" (
    echo [Jarvis] Создаю окружение и ставлю зависимости...
    %PY% -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)

".venv\Scripts\python.exe" -m pip install pyinstaller || goto :fail

rem jarvis.ico должен лежать рядом с build_exe.bat: это иконка exe и окна настроек.
rem --collect-all customtkinter: библиотека хранит темы и шрифты в своих файлах, без них окно настроек не откроется.
rem --noconsole: без чёрного окна (ошибки пишутся в %USERPROFILE%\.jarvis\errors.log)
rem Уберите --noconsole, если нужна консоль для отладки.
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
    --name Jarvis ^
    --icon jarvis.ico ^
    --add-data "jarvis.ico;." ^
    --collect-all customtkinter ^
    --collect-all speech_recognition ^
    --collect-data ytmusicapi ^
    --hidden-import pyaudiowpatch ^
    --hidden-import pyttsx3.drivers ^
    --hidden-import pyttsx3.drivers.sapi5 ^
    --hidden-import win32timezone ^
    jarvis.py || goto :fail

echo.
echo [Jarvis] Готово: dist\Jarvis.exe
echo Положите рядом с ним config.json (если нужен) и запускайте.
goto :end

:fail
echo.
echo [Jarvis] Сборка не удалась. Нужен Python 3.10-3.13 (3.14 пока не подходит). Если окно закрылось само, запусти батник из cmd.

:end
pause
