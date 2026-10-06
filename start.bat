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
    echo [Jarvis] Первый запуск: создаю окружение и ставлю зависимости...
    %PY% -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)

".venv\Scripts\python.exe" jarvis.py %*
goto :end

:fail
echo.
echo [Jarvis] Не удалось подготовить окружение. Нужен Python 3.10-3.13 (3.14 пока не подходит). Если окно закрылось само, запусти батник из cmd.

:end
pause
